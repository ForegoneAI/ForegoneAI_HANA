"""Where saved deals live (Milestone 2.4).

SupabaseDealRepository is what the API uses: the deals, deal_corrections and
deal_status_changes tables, written only through the server-side service
role. InMemoryDealRepository follows the same rules without a database, for
tests and the offline command-line demo.

Every read takes the organizations the caller may act for, so a deal from
another organization looks exactly like one that doesn't exist. save() only
applies if the deal is still at the version the caller read, so two
reviewers can't silently overwrite each other.
"""

from __future__ import annotations

import copy
import itertools
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Protocol
from uuid import UUID

from postgrest.exceptions import APIError
from supabase import Client, create_client

from backend.app.h9n.rag.config import RagSettings
from backend.app.h9n.review.models import (
    DealChanges,
    DealHistory,
    DealNotFoundError,
    DealRecord,
    DealSummary,
    DealVersionConflictError,
    NewDeal,
)

CONFLICT_MESSAGE = "Someone else changed this deal since you opened it. Reload it to see their changes."


class DealRepository(Protocol):
    def create(self, deal: NewDeal) -> DealRecord: ...

    def get(self, deal_id: UUID, organization_ids: Iterable[UUID]) -> DealRecord: ...

    def list(self, organization_ids: Iterable[UUID]) -> list[DealSummary]: ...

    def save(self, deal: DealRecord, changes: DealChanges, *, expected_version: int) -> DealRecord: ...

    def history(self, deal: DealRecord) -> DealHistory: ...


def _change_payload(deal: DealRecord, changes: DealChanges, expected_version: int) -> dict[str, Any]:
    """The JSON save_deal_changes() takes."""
    return {
        "deal_id": str(deal.id),
        "organization_id": str(deal.organization_id),
        "expected_version": expected_version,
        "status": changes.status,
        "profile": changes.profile.model_dump(mode="json"),
        "corrections": [
            correction.model_dump(mode="json", exclude={"deal_version", "created_at"})
            for correction in changes.corrections
        ],
        "status_change": (
            changes.status_change.model_dump(mode="json", exclude={"deal_version", "created_at"})
            if changes.status_change
            else None
        ),
    }


class SupabaseDealRepository:
    """Deals in Supabase, through the service-role client. The service role
    bypasses RLS, so every query here filters by organization itself."""

    def __init__(self, settings: RagSettings, *, client: Client | None = None) -> None:
        settings.require("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
        self._client = client or create_client(settings.supabase_url, settings.supabase_service_role_key)

    def create(self, deal: NewDeal) -> DealRecord:
        row = {
            "id": str(deal.id),
            "organization_id": str(deal.organization_id),
            "status": "draft",
            "version": 1,
            "profile": deal.profile.model_dump(mode="json"),
            "source_filename": deal.source_filename,
            "source_pages": deal.source_pages,
            "extraction_run_id": str(deal.extraction_run_id) if deal.extraction_run_id else None,
            "created_by": str(deal.created_by),
        }
        response = self._client.table("deals").insert(row).execute()
        return DealRecord.model_validate(response.data[0])

    def get(self, deal_id: UUID, organization_ids: Iterable[UUID]) -> DealRecord:
        organizations = sorted(str(organization_id) for organization_id in organization_ids)
        if not organizations:
            raise DealNotFoundError(deal_id)
        response = (
            self._client.table("deals")
            .select("*")
            .eq("id", str(deal_id))
            .in_("organization_id", organizations)
            .limit(1)
            .execute()
        )
        if not response.data:
            raise DealNotFoundError(deal_id)
        return DealRecord.model_validate(response.data[0])

    def list(self, organization_ids: Iterable[UUID]) -> list[DealSummary]:
        organizations = sorted(str(organization_id) for organization_id in organization_ids)
        if not organizations:
            return []
        # Only the profile fields the list shows, not every profile and its pages.
        response = (
            self._client.table("deals")
            .select(
                "id, organization_id, status, updated_at,"
                " deal_name:profile->>deal_name, property_name:profile->>property_name"
            )
            .in_("organization_id", organizations)
            .order("updated_at", desc=True)
            .execute()
        )
        return [DealSummary.model_validate(row) for row in response.data or []]

    def save(self, deal: DealRecord, changes: DealChanges, *, expected_version: int) -> DealRecord:
        try:
            self._client.rpc("save_deal_changes", {"change": _change_payload(deal, changes, expected_version)}).execute()
        except APIError as exc:
            # PostgREST turns the function's PTxxx error codes into these.
            if exc.code == "PT409":
                raise DealVersionConflictError(CONFLICT_MESSAGE) from exc
            if exc.code == "PT404":
                raise DealNotFoundError(deal.id) from exc
            raise
        return self.get(deal.id, [deal.organization_id])

    def history(self, deal: DealRecord) -> DealHistory:
        def rows(table: str) -> list[dict[str, Any]]:
            response = (
                self._client.table(table)
                .select("*")
                .eq("deal_id", str(deal.id))
                .eq("organization_id", str(deal.organization_id))
                .order("created_at")
                .execute()
            )
            return response.data or []

        return DealHistory(corrections=rows("deal_corrections"), status_changes=rows("deal_status_changes"))


class InMemoryDealRepository:
    """The same rules as SupabaseDealRepository, held in memory: for tests,
    and for the command-line demo, which runs without Supabase."""

    def __init__(self) -> None:
        self.deals: dict[UUID, DealRecord] = {}
        self.history_by_deal: dict[UUID, DealHistory] = {}
        # A clock that always moves forward, so ordering by time is stable.
        self._ticks = itertools.count(1)
        self._epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def _now(self) -> datetime:
        return self._epoch + timedelta(seconds=next(self._ticks))

    def create(self, deal: NewDeal) -> DealRecord:
        now = self._now()
        record = DealRecord(
            **deal.model_dump(exclude={"profile"}),
            profile=deal.profile.model_copy(deep=True),
            status="draft",
            version=1,
            created_at=now,
            updated_at=now,
        )
        self.deals[record.id] = record
        self.history_by_deal[record.id] = DealHistory()
        return copy.deepcopy(record)

    def get(self, deal_id: UUID, organization_ids: Iterable[UUID]) -> DealRecord:
        record = self.deals.get(deal_id)
        if record is None or record.organization_id not in set(organization_ids):
            raise DealNotFoundError(deal_id)
        return copy.deepcopy(record)

    def list(self, organization_ids: Iterable[UUID]) -> list[DealSummary]:
        organizations = set(organization_ids)
        summaries = [
            DealSummary(
                id=record.id,
                organization_id=record.organization_id,
                status=record.status,
                deal_name=record.profile.deal_name,
                property_name=record.profile.property_name,
                updated_at=record.updated_at,
            )
            for record in self.deals.values()
            if record.organization_id in organizations
        ]
        return sorted(summaries, key=lambda summary: summary.updated_at, reverse=True)

    def save(self, deal: DealRecord, changes: DealChanges, *, expected_version: int) -> DealRecord:
        current = self.deals.get(deal.id)
        if current is None or current.organization_id != deal.organization_id:
            raise DealNotFoundError(deal.id)
        if current.version != expected_version:
            raise DealVersionConflictError(CONFLICT_MESSAGE)

        now = self._now()
        version = current.version + 1
        self.deals[deal.id] = current.model_copy(
            update={
                "profile": changes.profile.model_copy(deep=True),
                "status": changes.status,
                "version": version,
                "updated_at": now,
            }
        )
        history = self.history_by_deal[deal.id]
        history.corrections.extend(
            correction.model_copy(update={"deal_version": version, "created_at": now})
            for correction in changes.corrections
        )
        if changes.status_change:
            history.status_changes.append(
                changes.status_change.model_copy(update={"deal_version": version, "created_at": now})
            )
        return copy.deepcopy(self.deals[deal.id])

    def history(self, deal: DealRecord) -> DealHistory:
        return copy.deepcopy(self.history_by_deal.get(deal.id, DealHistory()))
