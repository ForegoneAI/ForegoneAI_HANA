"""Supabase persistence for investment mandates (Milestone 3.1).

Mandates live in public.investment_mandates (see
supabase/migrations/20261013_create_h9n_investment_mandates.sql). Every call
is scoped to one organization: a mandate id from another organization is
treated exactly like one that doesn't exist.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from postgrest.exceptions import APIError
from supabase import Client, create_client

from backend.app.h9n.rag.config import RagSettings
from backend.app.h9n.screening.mandate import Mandate, MandateInput, MandateUpdate

TABLE = "investment_mandates"

# Postgres error codes: a unique-constraint violation (a duplicate name), and
# a foreign-key violation (an organization id that doesn't exist).
_UNIQUE_VIOLATION = "23505"
_FOREIGN_KEY_VIOLATION = "23503"


class MandateError(Exception):
    """Base class for mandate problems whose message is safe to show a user."""


class MandateNotFoundError(MandateError):
    """No mandate with that id in this organization."""


class MandateConflictError(MandateError):
    """The save clashes with another mandate or with someone else's edit."""


class MandateOrganizationError(MandateError):
    """The organization the mandate was saved for doesn't exist."""


class MandateArchivedError(MandateError):
    """An archived mandate can't be edited or selected for a new screening."""


class MandateRepository(Protocol):
    """What the API needs from mandate storage (a fake is used in tests)."""

    def list(self, organization_id: UUID, *, include_archived: bool = False) -> list[Mandate]: ...

    def get(self, organization_id: UUID, mandate_id: UUID) -> Mandate: ...

    def create(self, organization_id: UUID, mandate: MandateInput) -> Mandate: ...

    def update(self, organization_id: UUID, mandate_id: UUID, update: MandateUpdate) -> Mandate: ...

    def archive(self, organization_id: UUID, mandate_id: UUID) -> Mandate: ...


def _row_for(mandate: MandateInput) -> dict[str, Any]:
    return {
        "name": mandate.name,
        "description": mandate.description,
        "criteria": mandate.criteria.model_dump(mode="json", exclude_none=True),
        "is_demo": mandate.is_demo,
    }


def _raise_if_duplicate_name(exc: APIError, name: str) -> None:
    if getattr(exc, "code", None) == _UNIQUE_VIOLATION:
        raise MandateConflictError(
            f"An active mandate named {name!r} already exists in this organization."
        ) from exc


class SupabaseMandateRepository:
    """Reads and writes mandates through the server-only service-role client.

    Like the other Supabase repositories, the service role bypasses RLS, so
    callers must establish which organization the request belongs to first.
    """

    def __init__(self, settings: RagSettings, *, client: Client | None = None) -> None:
        settings.require("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
        self._client = client or create_client(settings.supabase_url, settings.supabase_service_role_key)

    def list(self, organization_id: UUID, *, include_archived: bool = False) -> list[Mandate]:
        query = self._client.table(TABLE).select("*").eq("organization_id", str(organization_id))
        if not include_archived:
            query = query.eq("is_archived", False)
        response = query.order("name").execute()
        return [Mandate.model_validate(row) for row in response.data or []]

    def get(self, organization_id: UUID, mandate_id: UUID) -> Mandate:
        response = (
            self._client.table(TABLE)
            .select("*")
            .eq("organization_id", str(organization_id))
            .eq("id", str(mandate_id))
            .execute()
        )
        if not response.data:
            raise MandateNotFoundError(f"No mandate found with id {mandate_id}.")
        return Mandate.model_validate(response.data[0])

    def create(self, organization_id: UUID, mandate: MandateInput) -> Mandate:
        row = {**_row_for(mandate), "organization_id": str(organization_id)}
        try:
            response = self._client.table(TABLE).insert(row).execute()
        except APIError as exc:
            _raise_if_duplicate_name(exc, mandate.name)
            if getattr(exc, "code", None) == _FOREIGN_KEY_VIOLATION:
                raise MandateOrganizationError("That organization doesn't exist.") from exc
            raise
        return Mandate.model_validate(response.data[0])

    def update(self, organization_id: UUID, mandate_id: UUID, update: MandateUpdate) -> Mandate:
        current = self.get(organization_id, mandate_id)
        if current.is_archived:
            raise MandateArchivedError("This mandate is archived and can't be edited.")
        if current.version != update.version:
            raise MandateConflictError(
                f"This mandate was changed by someone else (now version {current.version}, "
                f"your edit was based on version {update.version}). Reload it and try again."
            )
        row = {**_row_for(update), "version": update.version + 1}
        try:
            # Matching on the version too means two edits that both read the
            # same version can't both succeed: the second one updates nothing.
            response = (
                self._client.table(TABLE)
                .update(row)
                .eq("organization_id", str(organization_id))
                .eq("id", str(mandate_id))
                .eq("version", update.version)
                .eq("is_archived", False)
                .execute()
            )
        except APIError as exc:
            _raise_if_duplicate_name(exc, update.name)
            raise
        if not response.data:
            raise MandateConflictError("This mandate was changed by someone else. Reload it and try again.")
        return Mandate.model_validate(response.data[0])

    def archive(self, organization_id: UUID, mandate_id: UUID) -> Mandate:
        current = self.get(organization_id, mandate_id)
        if current.is_archived:
            return current
        response = (
            self._client.table(TABLE)
            .update({"is_archived": True})
            .eq("organization_id", str(organization_id))
            .eq("id", str(mandate_id))
            .execute()
        )
        return Mandate.model_validate(response.data[0])


def select_mandate_for_screening(
    repository: MandateRepository, organization_id: UUID, mandate_id: UUID
) -> Mandate:
    """The mandate a new screening (M3.2) will be judged against.

    Only an active mandate of the caller's own organization can be selected;
    the returned Mandate carries its `version`, which the screening result
    should store alongside the outcome.
    """
    mandate = repository.get(organization_id, mandate_id)
    if mandate.is_archived:
        raise MandateArchivedError("This mandate is archived; pick an active mandate to screen against.")
    return mandate
