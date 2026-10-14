"""Milestone 2.5: GET /me tells the web app who is signed in and which
organizations they may act for, so a member of several can choose one."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.h9n import auth
from backend.app.h9n.auth import SupabaseAuthService, get_current_user
from backend.app.h9n.rag.config import RagConfigurationError
from backend.tests.auth_fakes import OTHER_ORGANIZATION_ID, TEST_ORGANIZATION_ID, user_in
from backend.tests.test_auth import _settings

UNNAMED_ORGANIZATION_ID = UUID("33333333-3333-3333-3333-333333333333")


class FakeNames:
    def __init__(self, names):
        self.names = names
        self.asked_for = None

    def organization_names(self, organization_ids):
        self.asked_for = organization_ids
        return {org: name for org, name in self.names.items() if org in organization_ids}


@pytest.fixture
def names(monkeypatch) -> FakeNames:
    fake = FakeNames({TEST_ORGANIZATION_ID: "Northwind Capital", OTHER_ORGANIZATION_ID: "Acme Partners"})
    monkeypatch.setattr(auth, "get_auth_service", lambda: fake)
    return fake


def _me_as(user):
    main.app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(main.app).get("/api/h9n/me")


def test_lists_the_users_organizations_by_name(names):
    user = user_in(TEST_ORGANIZATION_ID, OTHER_ORGANIZATION_ID)

    response = _me_as(user)

    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(user.user_id),
        "organizations": [
            {"id": str(OTHER_ORGANIZATION_ID), "name": "Acme Partners"},
            {"id": str(TEST_ORGANIZATION_ID), "name": "Northwind Capital"},
        ],
    }


def test_only_the_users_own_organizations_are_looked_up(names):
    _me_as(user_in(TEST_ORGANIZATION_ID))

    assert names.asked_for == frozenset({TEST_ORGANIZATION_ID})


def test_an_organization_without_a_name_is_still_listed(names):
    response = _me_as(user_in(UNNAMED_ORGANIZATION_ID))

    assert response.json()["organizations"] == [
        {"id": str(UNNAMED_ORGANIZATION_ID), "name": str(UNNAMED_ORGANIZATION_ID)}
    ]


def test_a_user_with_no_organizations_gets_an_empty_list(names):
    assert _me_as(user_in()).json()["organizations"] == []


def test_requires_sign_in():
    main.app.dependency_overrides.pop(get_current_user)

    assert TestClient(main.app).get("/api/h9n/me").status_code == 401


def test_missing_supabase_configuration_is_a_503(monkeypatch):
    def unconfigured():
        raise RagConfigurationError("Supabase is not configured.")

    monkeypatch.setattr(auth, "get_auth_service", unconfigured)

    assert _me_as(user_in(TEST_ORGANIZATION_ID)).status_code == 503


class FakeOrganizationsTable:
    def __init__(self, rows):
        self.rows = rows
        self.ids = None

    def table(self, name):
        assert name == "organizations"
        return self

    def select(self, columns):
        return self

    def in_(self, column, values):
        assert column == "id"
        self.ids = values
        return self

    def execute(self):
        return type("Response", (), {"data": [row for row in self.rows if row["id"] in self.ids]})()


def test_organization_names_reads_only_the_requested_rows():
    client = FakeOrganizationsTable(
        [
            {"id": str(TEST_ORGANIZATION_ID), "name": "Northwind Capital"},
            {"id": str(OTHER_ORGANIZATION_ID), "name": "Acme Partners"},
        ]
    )
    service = SupabaseAuthService(_settings(), client=client)

    assert service.organization_names(frozenset({TEST_ORGANIZATION_ID})) == {TEST_ORGANIZATION_ID: "Northwind Capital"}
    assert client.ids == [str(TEST_ORGANIZATION_ID)]
    assert service.organization_names(frozenset()) == {}
