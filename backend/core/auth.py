from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import Header, HTTPException, status


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str


def get_principal(x_sentroxis_token: str | None = Header(default=None)) -> Principal:
    """Authenticate a local/demo request without persisting credentials.

    Production deployments should replace this adapter with OIDC/JWT validation and
    keep the authorization checks server-side. The demo token is intentionally
    opt-in through SENTROXIS_DEMO_TOKEN and is never logged.
    """
    expected = os.getenv("SENTROXIS_DEMO_TOKEN")
    if expected and x_sentroxis_token == expected:
        return Principal(subject="demo-analyst", role="analyst")
    if not expected and os.getenv("SENTROXIS_DEV_MODE", "true").lower() == "true":
        return Principal(subject="local-analyst", role="analyst")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_role(principal: Principal, *roles: str) -> Principal:
    if principal.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return principal
