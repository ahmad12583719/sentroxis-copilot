from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Cookie, HTTPException, Response, status

SESSION_COOKIE = "sentroxis_session"
SESSION_TTL = timedelta(hours=8)
_AUTH_DB_PATH: str | None = None


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str
    name: str
    email: str


def configure_auth_db(path: str) -> None:
    global _AUTH_DB_PATH
    _AUTH_DB_PATH = path


def _db() -> sqlite3.Connection:
    if not _AUTH_DB_PATH:
        raise RuntimeError("Authentication database is not configured")
    db = sqlite3.connect(_AUTH_DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210_000)
    return f"pbkdf2_sha256$210000${salt.hex()}${digest.hex()}"


def _password_matches(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _validate_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters")
    if len(password) > 128:
        raise ValueError("Password must be 128 characters or fewer")


def registration_allowed() -> bool:
    with _db() as db:
        return db.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"] == 0


def register_first_user(name: str, email: str, password: str) -> Principal:
    normalized_email = email.strip().lower()
    normalized_name = " ".join(name.strip().split())
    if not normalized_name or len(normalized_name) > 120:
        raise ValueError("Name must be between 1 and 120 characters")
    if "@" not in normalized_email or len(normalized_email) > 320:
        raise ValueError("Enter a valid email address")
    _validate_password(password)
    with _db() as db:
        if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise PermissionError("Initial registration is already closed")
        user_id = f"usr-{secrets.token_hex(12)}"
        db.execute(
            "INSERT INTO users (id, name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, normalized_name, normalized_email, _password_hash(password), "admin", _now().isoformat()),
        )
    return Principal(subject=user_id, role="admin", name=normalized_name, email=normalized_email)


def authenticate(email: str, password: str) -> Principal | None:
    normalized_email = email.strip().lower()
    with _db() as db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (normalized_email,)).fetchone()
    if not row or not _password_matches(password, row["password_hash"]):
        return None
    return Principal(subject=row["id"], role=row["role"], name=row["name"], email=row["email"])


def create_session(principal: Principal) -> str:
    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    created_at = _now()
    expires_at = created_at + SESSION_TTL
    with _db() as db:
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (created_at.isoformat(),))
        db.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, principal.subject, created_at.isoformat(), expires_at.isoformat()),
        )
    return raw_token


def _principal_from_session(raw_token: str | None) -> Principal | None:
    if not raw_token:
        return None
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = _now()
    with _db() as db:
        row = db.execute(
            "SELECT users.id, users.name, users.email, users.role FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token_hash = ? AND sessions.expires_at > ?",
            (token_hash, now.isoformat()),
        ).fetchone()
    if not row:
        return None
    return Principal(subject=row["id"], role=row["role"], name=row["name"], email=row["email"])


def get_principal(
    sentroxis_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> Principal:
    principal = _principal_from_session(sentroxis_session)
    if principal:
        return principal
    if os.getenv("SENTROXIS_DEV_MODE", "false").lower() == "true":
        return Principal(subject="local-analyst", role="admin", name="Local analyst", email="local@sentroxis.local")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=os.getenv("SENTROXIS_COOKIE_SECURE", "false").lower() == "true",
        samesite="lax",
        path="/",
    )


def clear_session(response: Response, raw_token: str | None) -> None:
    if raw_token:
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        with _db() as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
    response.delete_cookie(SESSION_COOKIE, path="/")


def require_role(principal: Principal, *roles: str) -> Principal:
    if principal.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return principal


def principal_payload(principal: Principal) -> dict[str, Any]:
    return {"id": principal.subject, "name": principal.name, "email": principal.email, "role": principal.role}


__all__ = [
    "SESSION_COOKIE",
    "Principal",
    "authenticate",
    "clear_session",
    "configure_auth_db",
    "create_session",
    "get_principal",
    "principal_payload",
    "register_first_user",
    "registration_allowed",
    "require_role",
    "set_session_cookie",
]
