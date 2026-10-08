"""Supabase Auth for the H9N API (Milestone 2.5).

Every protected route resolves the caller from their Supabase access token
(`Authorization: Bearer <token>`) and the organizations they are an active
member of. Routes then act only on data owned by one of those organizations,
so a user from one organization cannot reach another's deals, PDFs, or
retrieved passages.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

from fastapi import Header, HTTPException, status
from supabase import Client, create_client

from backend.app.h9n.rag.config import RagConfigurationError, RagSettings, get_rag_settings


@dataclass(frozen=True)
class AuthenticatedUser:
    """The signed-in caller and the organizations they may act for."""

    user_id: UUID
    organization_ids: frozenset[UUID]


class InvalidTokenError(Exception):
    """Raised when an access token is malformed, expired, or not a user token."""


class SupabaseAuthService:
    """Verifies Supabase access tokens and looks up organization memberships.

    Uses the server-only service-role client, like SupabaseRagRepository, so
    membership lookups are not themselves limited by RLS.
    """

    def __init__(self, settings: RagSettings, *, client: Client | None = None) -> None:
        settings.require("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
        self._client = client or create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )

    def verify_token(self, token: str) -> UUID:
        """Return the user id of a valid, signed-in user's access token.

        get_claims() checks expiry and the signature against the project's
        published signing keys (or asks Supabase directly for legacy
        shared-secret projects). It does not check who the token is for, so
        anon and service-role tokens are rejected here.
        """
        try:
            response = self._client.auth.get_claims(jwt=token)
        except Exception as exc:  # Any verification failure means "not signed in".
            raise InvalidTokenError("The access token is invalid or has expired.") from exc

        claims = (response or {}).get("claims") or {}
        if not claims or claims.get("role") != "authenticated" or not claims.get("sub"):
            raise InvalidTokenError("The access token is not a signed-in user's token.")
        try:
            return UUID(str(claims["sub"]))
        except ValueError as exc:
            raise InvalidTokenError("The access token has an invalid subject.") from exc

    def active_organization_ids(self, user_id: UUID) -> frozenset[UUID]:
        """Return the organizations this user is an active member of."""
        response = (
            self._client.table("organization_memberships")
            .select("organization_id")
            .eq("user_id", str(user_id))
            .eq("is_active", True)
            .execute()
        )
        return frozenset(UUID(row["organization_id"]) for row in response.data or [])


@lru_cache
def get_auth_service() -> SupabaseAuthService:
    """Build the Supabase client only when a protected route is first called."""
    return SupabaseAuthService(get_rag_settings())


def get_current_user(
    authorization: str | None = Header(default=None),
) -> AuthenticatedUser:
    """FastAPI dependency: the signed-in caller, or a 401."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in and send your access token as 'Authorization: Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        service = get_auth_service()
        user_id = service.verify_token(token.strip())
        organization_ids = service.active_organization_ids(user_id)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except RagConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return AuthenticatedUser(user_id=user_id, organization_ids=organization_ids)


def resolve_organization(user: AuthenticatedUser, requested: UUID | None) -> UUID:
    """The organization a request acts for.

    A requested organization must be one the user belongs to. When none is
    requested, a user with exactly one organization acts for that one.
    """
    if requested is not None:
        if requested not in user.organization_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of that organization.",
            )
        return requested

    if len(user.organization_ids) == 1:
        return next(iter(user.organization_ids))
    if not user.organization_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not a member of any organization.",
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="You belong to several organizations; specify organization_id.",
    )
