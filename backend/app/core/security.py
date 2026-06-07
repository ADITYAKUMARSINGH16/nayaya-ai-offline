"""Supabase JWT verification + per-route dependencies.

How it works:
- The browser holds a Supabase JWT after sign-in.
- The frontend sends it in `Authorization: Bearer <jwt>` on every API call.
- This module verifies the HS256 signature with `SUPABASE_JWT_SECRET` and
  exposes the user's claims as a FastAPI dependency.

Soft-auth mode (`auth_required=false`, the default for local dev):
- Missing OR unverifiable token → request proceeds as an anonymous user.
  (e.g. tokens signed with the new ES256 scheme can't be verified here yet —
  we just drop to anonymous instead of 401ing the demo.)

Strict mode (`auth_required=true`):
- Missing OR invalid token → 401.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import settings
from app.services import db


class CurrentUser(BaseModel):
    id: str | None = None
    email: str | None = None
    role: str = "user"
    is_admin: bool = False
    is_anonymous: bool = True


def _try_decode(token: str) -> dict | None:
    """Verify the token and return its claims, or None if verification fails.

    Returns None on:
      - missing JWT secret
      - signature mismatch
      - wrong algorithm (e.g. new ES256 tokens — we only check HS256)
      - expired token
      - bad audience
    """
    if not settings.auth_required:
        try:
            return jwt.get_unverified_claims(token)
        except JWTError:
            pass

    if not settings.supabase_jwt_secret:
        return None
    try:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience=settings.supabase_jwt_audience,
        )
    except JWTError:
        return None


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """Resolve the caller. Honours `auth_required` for strict vs soft mode."""
    # No header at all
    if not authorization or not authorization.lower().startswith("bearer "):
        if settings.auth_required:
            raise HTTPException(status_code=401, detail="Missing bearer token")
        return CurrentUser()

    token = authorization.split(" ", 1)[1].strip()
    claims = _try_decode(token)
    if claims is None:
        if settings.auth_required:
            raise HTTPException(status_code=401, detail="Invalid token")
        # Soft mode: token can't be verified locally — treat as anonymous.
        return CurrentUser()

    email = (claims.get("email") or "").lower()
    user_id = claims.get("sub")
    
    # Fetch role from DB
    role = "user"
    if user_id:
        role = db.get_user_role(user_id)
        if not role or role == "user":
            role = claims.get("user_metadata", {}).get("role", "user")
        if role:
            role = role.lower()

    # Note: a stray `print("DEBUG ROLE RESOLUTION: ...")` previously lived here
    # and (a) leaked the user's id + full JWT claims to stdout on every request
    # and (b) called db.get_user_role() a second time inside the f-string,
    # silently doubling the DB load per authenticated request. Removed.

    return CurrentUser(
        id=user_id,
        email=email or None,
        role=role,
        is_admin=email in settings.admin_emails_list or role == "admin",
        is_anonymous=False,
    )


def require_user(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    if user.is_anonymous:
        raise HTTPException(status_code=401, detail="Sign-in required")
    return user


def require_admin(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    if user.is_anonymous or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def require_lawyer(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    if user.is_anonymous or (user.role not in ["lawyer", "admin"] and not user.is_admin):
        raise HTTPException(status_code=403, detail="Lawyer access only")
    return user


def require_judge(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    if user.is_anonymous or (user.role not in ["judge", "admin"] and not user.is_admin):
        raise HTTPException(status_code=403, detail="Judge access only")
    return user
