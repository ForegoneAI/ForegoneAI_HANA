"""Server-only Supabase persistence for underwriting data."""

from __future__ import annotations
import os
from uuid import UUID
from supabase import create_client
from .models import UnderwritingRequest, UnderwritingResponse

# Handle underwriting data storage in Supabase.
class UnderwritingRepository:

    # Initialize the Supabase client using environment credentials.
    def __init__(self, client=None):
        self.client = client or create_client(
            os.environ['SUPABASE_URL'],
            os.environ['SUPABASE_SERVICE_ROLE_KEY']
        )

    # Save underwriting inputs, assumptions, and results.
    def save(
        self,
        organization_id: UUID,
        request: UnderwritingRequest,
        result: UnderwritingResponse,
        reviewer_id: UUID
    ) -> UUID:

        # Generate a unique ID for this underwriting version.
        from uuid import uuid4
        version_id = uuid4()

        # Prepare the record with organization and reviewer details.
        payload = {
            'id': str(version_id),
            'organization_id': str(organization_id),
            'deal_id': request.deal_id,
            'created_by': str(reviewer_id),

            # Store input values and their provenance.
            'inputs': request.inputs.model_dump(mode='json'),

            # Store scenario assumptions separately from results.
            'scenario_assumptions': {
                k: v.model_dump(mode='json')
                for k, v in request.scenarios.items()
            },

            # Store calculated financial metrics and cash flows.
            'results': result.model_dump(mode='json'),
        }

        # Insert the underwriting record into Supabase.
        self.client.table('underwriting_runs').insert(payload).execute()

        # Return the ID of the saved underwriting version.
        return version_id
