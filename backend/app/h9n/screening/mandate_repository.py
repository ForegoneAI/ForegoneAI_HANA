"""Supabase persistence for investment mandates (Milestone 3.1).

Mandates live in public.investment_mandates (see
supabase/migrations/20261013_create_h9n_investment_mandates.sql). Every call
is scoped to one organization: a mandate id from another organization is
treated exactly like one that doesn't exist.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol
from uuid import UUID

from postgrest.exceptions import APIError
from pydantic import BaseModel, ValidationError
from supabase import Client, create_client

from backend.app.h9n.rag.config import RagSettings
from backend.app.h9n.screening.mandate import Mandate, MandateInput, MandateUpdate

logger = logging.getLogger(__name__)

# What a stored row that no longer fits the form can raise when read: a
# validation error, or OverflowError for a hand-edited number too large for
# Python to compare. Anything else is a real bug and is left to surface.
_UNREADABLE = (ValidationError, OverflowError)

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


class MandateDataError(MandateError):
    """A saved mandate's data no longer fits the mandate form (for example it
    was edited by hand in the database), so it can't be used as-is."""


class ArchivedUnreadableMandate(BaseModel):
    """The reply when an unreadable mandate (see MandateDataError) is archived:
    the archive worked, but its criteria can't be shown."""

    id: UUID
    organization_id: UUID
    is_archived: bool = True
    version: int
    problem: str


class MandateArchivedError(MandateError):
    """An archived mandate can't be edited or selected for a new screening."""


class MandateRepository(Protocol):
    """What the API needs from mandate storage (a fake is used in tests)."""

    def list(self, organization_id: UUID, *, include_archived: bool = False) -> list[Mandate]: ...

    def list_with_skipped(
        self, organization_id: UUID, *, include_archived: bool = False
    ) -> tuple[list[Mandate], int]: ...

    def get(self, organization_id: UUID, mandate_id: UUID) -> Mandate: ...

    def create(self, organization_id: UUID, mandate: MandateInput) -> Mandate: ...

    def update(self, organization_id: UUID, mandate_id: UUID, update: MandateUpdate) -> Mandate: ...

    def archive(self, organization_id: UUID, mandate_id: UUID) -> "Mandate | ArchivedUnreadableMandate": ...


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
        """The organization's readable mandates (see list_with_skipped)."""
        return self.list_with_skipped(organization_id, include_archived=include_archived)[0]

    def list_with_skipped(
        self, organization_id: UUID, *, include_archived: bool = False
    ) -> tuple[list[Mandate], int]:
        """(the organization's mandates, how many unreadable ones were left
        out). An unreadable row is skipped and logged, so one bad row never
        hides all the others; the count lets a UI say that some are missing."""
        query = self._client.table(TABLE).select("*").eq("organization_id", str(organization_id))
        if not include_archived:
            query = query.eq("is_archived", False)
        response = query.order("name").execute()
        mandates = []
        skipped = 0
        for row in response.data or []:
            try:
                mandates.append(Mandate.model_validate(row))
            except _UNREADABLE as exc:
                skipped += 1
                logger.error(
                    "Skipping unreadable mandate %s (organization %s): %s",
                    row.get("id"),
                    organization_id,
                    _problems(exc),
                )
        return mandates, skipped

    def get(self, organization_id: UUID, mandate_id: UUID) -> Mandate:
        row = self._fetch_row(organization_id, mandate_id)
        try:
            return Mandate.model_validate(row)
        except _UNREADABLE as exc:
            logger.error("Unreadable mandate %s (organization %s): %s", mandate_id, organization_id, _problems(exc))
            raise MandateDataError(
                f"Mandate {mandate_id} is saved in a form this version of H9N can't read "
                f"({_problems(exc)}). Fix it by saving a corrected version (PUT), or archive it."
            ) from exc

    def _fetch_row(self, organization_id: UUID, mandate_id: UUID) -> dict[str, Any]:
        """The raw row, unchecked, so even an unreadable mandate can still be
        corrected or archived."""
        response = (
            self._client.table(TABLE)
            .select("*")
            .eq("organization_id", str(organization_id))
            .eq("id", str(mandate_id))
            .execute()
        )
        if not response.data:
            raise MandateNotFoundError(f"No mandate found with id {mandate_id}.")
        return response.data[0]

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
        current = self._fetch_row(organization_id, mandate_id)
        if current.get("is_archived"):
            raise MandateArchivedError("This mandate is archived and can't be edited.")
        if current.get("version") != update.version:
            raise MandateConflictError(
                f"This mandate was changed by someone else (now version {current.get('version')}, "
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

    def archive(self, organization_id: UUID, mandate_id: UUID) -> "Mandate | ArchivedUnreadableMandate":
        current = self._fetch_row(organization_id, mandate_id)
        if not current.get("is_archived"):
            response = (
                self._client.table(TABLE)
                .update({"is_archived": True})
                .eq("organization_id", str(organization_id))
                .eq("id", str(mandate_id))
                .execute()
            )
            if not response.data:
                # The row vanished between the read and the update (e.g. its
                # organization was deleted).
                raise MandateNotFoundError(f"No mandate found with id {mandate_id}.")
            current = response.data[0]
        try:
            return Mandate.model_validate(current)
        except _UNREADABLE as exc:
            # Archiving is exactly what should happen to a broken mandate, so
            # it succeeds; the reply just can't include the unreadable criteria.
            logger.warning("Archived unreadable mandate %s: %s", mandate_id, _problems(exc))
            return ArchivedUnreadableMandate(
                id=mandate_id,
                organization_id=organization_id,
                version=current.get("version") or 1,
                problem=_problems(exc),
            )


def _problems(exc: Exception, limit: int = 3) -> str:
    """A short, value-free summary of why a stored row didn't validate."""
    if not isinstance(exc, ValidationError):
        return type(exc).__name__
    errors = exc.errors(include_input=False, include_url=False)
    parts = [f"{'.'.join(str(p) for p in error['loc']) or 'row'}: {error['msg']}" for error in errors[:limit]]
    if len(errors) > limit:
        parts.append(f"and {len(errors) - limit} more")
    return "; ".join(parts)


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
