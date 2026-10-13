"""FastAPI routes for investment mandates (Milestone 3.1).

    GET  /api/h9n/mandates                      list active mandates (?include_archived=true for all)
    POST /api/h9n/mandates                      create one
    GET  /api/h9n/mandates/{id}                 fetch one
    PUT  /api/h9n/mandates/{id}                 edit one (send the version you edited)
    POST /api/h9n/mandates/{id}/archive         retire one (kept for history)
    GET  /api/h9n/mandates/{id}/for-screening   select one for a screening

Every route acts for one organization, given as `?organization_id=...`.

Access: until customer sign-in lands (M2.5, PR #6), these routes use the same
internal operator key as the RAG and run-recording routes (X-H9N-API-Key).
That check lives only in `_organization_for_request` below, so switching to
signed-in users is a one-function change.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Callable, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from backend.app.h9n.rag.api import require_internal_rag_access
from backend.app.h9n.rag.config import RagConfigurationError, get_rag_settings
from backend.app.h9n.screening.mandate import Mandate, MandateInput, MandateUpdate
from backend.app.h9n.screening.mandate_repository import (
    MandateArchivedError,
    MandateConflictError,
    MandateNotFoundError,
    MandateOrganizationError,
    MandateRepository,
    SupabaseMandateRepository,
    select_mandate_for_screening,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

router = APIRouter(prefix="/api/h9n/mandates", tags=["H9N Mandates"])


@lru_cache
def get_mandate_repository() -> MandateRepository:
    """Built on first use so the app starts (and tests run) without Supabase."""
    return SupabaseMandateRepository(get_rag_settings())


def _organization_for_request(
    organization_id: UUID = Query(..., description="The organization whose mandates to use."),
    x_h9n_api_key: str | None = Header(default=None, alias="X-H9N-API-Key"),
) -> UUID:
    """The organization a request acts for. The only place access is checked."""
    require_internal_rag_access(x_h9n_api_key)
    return organization_id


def _call(action: Callable[[MandateRepository], T]) -> T:
    """Runs one storage action, turning any failure into a safe HTTP error."""
    try:
        repository = get_mandate_repository()
        return action(repository)
    except MandateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (MandateConflictError, MandateArchivedError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MandateOrganizationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RagConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # Database details go to the log, never to the caller.
        logger.exception("Mandate storage failed")
        raise HTTPException(status_code=502, detail="Mandates could not be reached. Try again shortly.") from exc


@router.get("", response_model=list[Mandate])
def list_mandates(
    include_archived: bool = False,
    organization_id: UUID = Depends(_organization_for_request),
) -> list[Mandate]:
    return _call(lambda repository: repository.list(organization_id, include_archived=include_archived))


@router.post("", response_model=Mandate, status_code=status.HTTP_201_CREATED)
def create_mandate(
    mandate: MandateInput,
    organization_id: UUID = Depends(_organization_for_request),
) -> Mandate:
    return _call(lambda repository: repository.create(organization_id, mandate))


@router.get("/{mandate_id}", response_model=Mandate)
def get_mandate(
    mandate_id: UUID,
    organization_id: UUID = Depends(_organization_for_request),
) -> Mandate:
    return _call(lambda repository: repository.get(organization_id, mandate_id))


@router.put("/{mandate_id}", response_model=Mandate)
def update_mandate(
    mandate_id: UUID,
    update: MandateUpdate,
    organization_id: UUID = Depends(_organization_for_request),
) -> Mandate:
    return _call(lambda repository: repository.update(organization_id, mandate_id, update))


@router.post("/{mandate_id}/archive", response_model=Mandate)
def archive_mandate(
    mandate_id: UUID,
    organization_id: UUID = Depends(_organization_for_request),
) -> Mandate:
    return _call(lambda repository: repository.archive(organization_id, mandate_id))


@router.get("/{mandate_id}/for-screening", response_model=Mandate)
def select_for_screening(
    mandate_id: UUID,
    organization_id: UUID = Depends(_organization_for_request),
) -> Mandate:
    """Selects a mandate for screening: 409 if it's archived. M3.2's screening
    endpoint should call `select_mandate_for_screening` the same way."""
    return _call(lambda repository: select_mandate_for_screening(repository, organization_id, mandate_id))
