"""H9N M4 - Underwriting API endpoints."""

from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from backend.app.h9n.auth import AuthenticatedUser, get_current_user, resolve_organization
from .models import UnderwritingRequest, UnderwritingResponse
from .finance import calculate
from .repository import UnderwritingRepository

# Define underwriting API routes.
router = APIRouter(prefix='/api/h9n/underwriting', tags=['underwriting'])

# Create a repository for saving underwriting results.
def repository() -> UnderwritingRepository:
    return UnderwritingRepository()

# Preview financial scenarios without saving results.
@router.post('/calculate', response_model=UnderwritingResponse)
def calculate_underwriting(req: UnderwritingRequest, user: AuthenticatedUser = Depends(get_current_user)):
    # Require an authenticated organization member.
    if not user.organization_ids:
        raise HTTPException(403, 'No organization membership')

    # Calculate metrics for each scenario.
    return UnderwritingResponse(deal_id=req.deal_id, scenarios={
        name: calculate(req.inputs, name, adjustments)
        for name, adjustments in req.scenarios.items()
    })

# Save underwriting results for an approved deal.
@router.post('/save', response_model=dict)
def save_underwriting(req: UnderwritingRequest, organization_id: UUID | None = None,
                      user: AuthenticatedUser = Depends(get_current_user),
                      repo: UnderwritingRepository = Depends(repository)):

    # Verify the user's organization.
    org = resolve_organization(user, organization_id)

    from backend.app.main import _review_store
    from backend.app.h9n.schemas.repe_deal import REPEDealProfile

    # Confirm the deal belongs to the organization.
    if _review_store.owner_of(req.deal_id) != org:
        raise HTTPException(404, 'Deal not found')

    deal: REPEDealProfile = _review_store.get(req.deal_id)

    # Require approval before saving underwriting.
    if deal.review_status != 'approved':
        raise HTTPException(409, 'Approve the deal profile before saving underwriting')

    # Calculate all requested financial scenarios.
    result = UnderwritingResponse(deal_id=req.deal_id, scenarios={
        name: calculate(req.inputs, name, adjustments)
        for name, adjustments in req.scenarios.items()
    })

    # Save the analysis and return its version ID.
    version_id = repo.save(org, req, result, user.user_id)
    return {'version_id': str(version_id), 'result': result.model_dump(mode='json')}
