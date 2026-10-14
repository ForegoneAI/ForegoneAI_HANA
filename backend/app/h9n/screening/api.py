"""FastAPI routes for investment mandates (Milestone 3.1).

    GET  /api/h9n/mandates                      list active mandates (?include_archived=true for all)
                                                -> {"mandates": [...], "skipped": n}
    POST /api/h9n/mandates                      create one
    GET  /api/h9n/mandates/{id}                 fetch one
    PUT  /api/h9n/mandates/{id}                 edit one (send the version you edited)
    POST /api/h9n/mandates/{id}/archive         retire one (kept for history)
    GET  /api/h9n/mandates/{id}/for-screening   select one for a screening
    GET  /api/h9n/mandates/vocabulary           the allowed property types and markets

Every route except /vocabulary acts for one organization: `?organization_id=...`,
which may be left out when the caller belongs to only one. The list returns {"mandates": [...], "skipped": n},
where `skipped` counts saved mandates that couldn't be read, so a UI can say
so (in the body, not a header, so browsers on another domain can see it).

Access (M2.5): every route - including /vocabulary, for consistency - needs a
signed-in user (`Authorization: Bearer <token>`), and acts only for an
organization that user is an active member of, like the deal and RAG routes.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Callable, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from backend.app.h9n.auth import AuthenticatedUser, get_current_user, resolve_organization
from backend.app.h9n.rag.config import RagConfigurationError, get_rag_settings
from backend.app.h9n.screening.mandate import Mandate, MandateInput, MandateUpdate
from backend.app.h9n.screening.vocabulary import ASSET_TYPES, MARKETS
from backend.app.h9n.screening.mandate_repository import (
    ArchivedUnreadableMandate,
    MandateArchivedError,
    MandateConflictError,
    MandateDataError,
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
    organization_id: UUID | None = Query(
        None, description="The organization whose mandates to use. Only needed if you belong to several."
    ),
    user: AuthenticatedUser = Depends(get_current_user),
) -> UUID:
    """The organization a request acts for: one the signed-in user belongs to,
    or a 403 (see resolve_organization)."""
    return resolve_organization(user, organization_id)


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
    except MandateDataError as exc:
        # Our stored data is at fault, not the request: a clear 500 that says
        # which mandate and how to recover, instead of "could not be reached".
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RagConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # Database details go to the log, never to the caller.
        logger.exception("Mandate storage failed")
        raise HTTPException(status_code=502, detail="Mandates could not be reached. Try again shortly.") from exc


class MandateList(BaseModel):
    """The list reply: the readable mandates, and how many saved ones were
    left out because their data couldn't be read (see the repository)."""

    mandates: list[Mandate]
    skipped: int = 0


@router.get("", response_model=MandateList)
def list_mandates(
    include_archived: bool = False,
    organization_id: UUID = Depends(_organization_for_request),
) -> MandateList:
    mandates, skipped = _call(
        lambda repository: repository.list_with_skipped(organization_id, include_archived=include_archived)
    )
    return MandateList(mandates=mandates, skipped=skipped)


@router.get("/vocabulary", dependencies=[Depends(get_current_user)])
def mandate_vocabulary() -> dict[str, list[str]]:
    """The property types and markets a mandate may use (for a UI's pickers).
    The same fixed lists for every organization, so no organization is needed.
    Exact aliases ("Apartments", "DFW") are also accepted and saved as these."""
    return {"asset_types": ASSET_TYPES, "markets": MARKETS}


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


@router.post("/{mandate_id}/archive", response_model=Mandate | ArchivedUnreadableMandate)
def archive_mandate(
    mandate_id: UUID,
    organization_id: UUID = Depends(_organization_for_request),
) -> Mandate | ArchivedUnreadableMandate:
    """Archives a mandate. An unreadable one is archived too; the reply then
    has `problem` instead of its criteria."""
    return _call(lambda repository: repository.archive(organization_id, mandate_id))


@router.get("/{mandate_id}/for-screening", response_model=Mandate)
def select_for_screening(
    mandate_id: UUID,
    organization_id: UUID = Depends(_organization_for_request),
) -> Mandate:
    """Selects a mandate for screening: 409 if it's archived. M3.2's screening
    endpoint should call `select_mandate_for_screening` the same way."""
    return _call(lambda repository: select_mandate_for_screening(repository, organization_id, mandate_id))
