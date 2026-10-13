"""
create_demo_mandate.py

Saves the built-in demo mandate ("Demo - Sun Belt Value-Add Multifamily", see
backend/app/h9n/screening/mandate.py) for one organization in Supabase, so
there is always at least one mandate to select for screening (M3.1).

    python -m backend.scripts.create_demo_mandate --organization-id <uuid>

Needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env, and the
20261013_create_h9n_investment_mandates.sql migration applied. Running it
again is safe: if the organization already has an active mandate with the
demo's name, it says so and changes nothing.
"""

from __future__ import annotations

import argparse
import sys
from uuid import UUID

from backend.app.h9n.rag.config import RagSettings
from backend.app.h9n.screening.mandate import DEMO_MANDATE
from backend.app.h9n.screening.mandate_repository import (
    MandateConflictError,
    MandateRepository,
    SupabaseMandateRepository,
)


def create_demo_mandate(repository: MandateRepository, organization_id: UUID) -> tuple[bool, str]:
    """(created?, message). Leaves an existing demo mandate untouched."""
    for mandate in repository.list(organization_id):
        if mandate.name.lower() == DEMO_MANDATE.name.lower():
            kind = "Demo mandate" if mandate.is_demo else "A non-demo mandate with the demo's name"
            return False, f"{kind} already exists (id {mandate.id}, version {mandate.version}); nothing changed."
    try:
        mandate = repository.create(organization_id, DEMO_MANDATE)
    except MandateConflictError:
        # Someone saved one between the check above and this save.
        return False, "Demo mandate already exists; nothing changed."
    return True, f"Created demo mandate {mandate.name!r} with id {mandate.id}."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--organization-id", type=UUID, required=True, help="Organization to save it for.")
    args = parser.parse_args(argv)

    repository = SupabaseMandateRepository(RagSettings.from_environment())
    _, message = create_demo_mandate(repository, args.organization_id)
    print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
