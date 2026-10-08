"""Signed-in users and a fake extraction-run store for API tests (Milestone 2.5)."""

from uuid import UUID, uuid4

from backend.app.h9n.auth import AuthenticatedUser

# The organization every test's signed-in user belongs to, unless a test
# signs in someone else.
TEST_ORGANIZATION_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_ORGANIZATION_ID = UUID("22222222-2222-2222-2222-222222222222")


def user_in(*organization_ids: UUID) -> AuthenticatedUser:
    return AuthenticatedUser(user_id=uuid4(), organization_ids=frozenset(organization_ids))


TEST_USER = user_in(TEST_ORGANIZATION_ID)


class FakeRunRepository:
    """Stands in for Supabase when an extraction run is recorded."""

    def __init__(self, *, fail: bool = False):
        self.runs = []
        self.run_id = uuid4()
        self._fail = fail

    def record(self, run) -> UUID:
        if self._fail:
            raise RuntimeError("database unavailable")
        self.runs.append(run)
        return self.run_id
