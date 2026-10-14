"""An in-memory stand-in for the Supabase client, just big enough for
SupabaseMandateRepository: table().select/insert/update, .eq(), .order(),
.execute(). It mirrors the parts of the real table the repository relies on -
generated ids, version default, updated_at changing on every update, and the
unique active-name index - so the repository's own logic is what's tested."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Optional
from uuid import uuid4

from postgrest.exceptions import APIError


class FakeMandateTable:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self._clock = datetime(2026, 10, 13, tzinfo=timezone.utc)
        self.fail_with: Optional[Exception] = None
        self.fail_on_insert: Optional[Exception] = None

    def now(self) -> str:
        self._clock += timedelta(seconds=1)
        return self._clock.isoformat()

    def check_unique_name(self, candidate: dict[str, Any]) -> None:
        if candidate.get("is_archived"):
            return
        for row in self.rows:
            if (
                row["id"] != candidate["id"]
                and not row["is_archived"]
                and row["organization_id"] == candidate["organization_id"]
                and row["name"].lower() == candidate["name"].lower()
            ):
                raise APIError({"code": "23505", "message": "duplicate key value violates unique constraint"})


class _Query:
    def __init__(self, table: FakeMandateTable, action: str, payload: Optional[dict[str, Any]] = None):
        self._table = table
        self._action = action
        self._payload = payload
        self._filters: list[tuple[str, Any]] = []
        self._order: Optional[str] = None

    def eq(self, column: str, value: Any) -> "_Query":
        self._filters.append((column, value))
        return self

    def order(self, column: str) -> "_Query":
        self._order = column
        return self

    def _matches(self, row: dict[str, Any]) -> bool:
        return all(str(row.get(column)) == str(value) if not isinstance(value, bool) else row.get(column) is value
                   for column, value in self._filters)

    def execute(self) -> SimpleNamespace:
        table = self._table
        if table.fail_with is not None:
            raise table.fail_with

        if self._action == "insert":
            if table.fail_on_insert is not None:
                raise table.fail_on_insert
            now = table.now()
            row = {
                "id": str(uuid4()),
                "description": None,
                "is_demo": False,
                "is_archived": False,
                "version": 1,
                "created_at": now,
                "updated_at": now,
                **copy.deepcopy(self._payload),
            }
            table.check_unique_name(row)
            table.rows.append(row)
            return SimpleNamespace(data=[copy.deepcopy(row)])

        matched = [row for row in table.rows if self._matches(row)]
        if self._action == "select":
            if self._order:
                matched.sort(key=lambda row: row[self._order])
            return SimpleNamespace(data=copy.deepcopy(matched))

        # update
        updated = []
        for row in matched:
            candidate = {**row, **copy.deepcopy(self._payload), "updated_at": table.now()}
            table.check_unique_name(candidate)
            row.update(candidate)
            updated.append(copy.deepcopy(row))
        return SimpleNamespace(data=updated)


class _TableRef:
    def __init__(self, table: FakeMandateTable):
        self._table = table

    def select(self, columns: str) -> _Query:
        return _Query(self._table, "select")

    def insert(self, row: dict[str, Any]) -> _Query:
        return _Query(self._table, "insert", row)

    def update(self, row: dict[str, Any]) -> _Query:
        return _Query(self._table, "update", row)


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.mandates = FakeMandateTable()

    def table(self, name: str) -> _TableRef:
        assert name == "investment_mandates", name
        return _TableRef(self.mandates)
