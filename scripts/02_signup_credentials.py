#!/usr/bin/env python3
"""Step 2 of 3: create or verify the initial local Sentroxis account.

The password is handled only in memory. The script stores a PBKDF2-SHA256 hash in
the project database and writes a 0600 handoff file containing the email identity
only. Script 3 prompts for the password again when run independently; the master
runner passes it directly through standard input without writing it to disk.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

ITERATIONS = 210_000


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def password_matches(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (TypeError, ValueError):
        return False


def validate(name: str, email: str, password: str) -> tuple[str, str]:
    normalized_name = " ".join(name.strip().split())
    normalized_email = email.strip().lower()
    if not normalized_name or len(normalized_name) > 120:
        raise ValueError("Name must be between 1 and 120 characters")
    if "@" not in normalized_email or len(normalized_email) > 320:
        raise ValueError("Enter a valid email address")
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must be between 12 and 128 characters. This matches the Sentroxis login policy.")
    return normalized_name, normalized_email


def ensure_users_table(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def existing_account(db_path: Path) -> tuple[str, str, str, str, str] | None:
    """Return the local initial account without creating or modifying a database."""
    if not db_path.is_file():
        return None
    try:
        with sqlite3.connect(db_path) as db:
            has_users = db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'").fetchone()
            if not has_users:
                return None
            row = db.execute("SELECT id, name, email, password_hash, role FROM users ORDER BY created_at LIMIT 1").fetchone()
            return tuple(row) if row else None
    except sqlite3.Error as error:
        raise RuntimeError(f"Unable to inspect the Sentroxis account database: {error}") from error


def secure_file(path: Path) -> None:
    if os.name == "posix":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def prompt_with_default(prompt: str, default: str) -> str:
    value = input(f"{prompt} [{default}]: ").strip()
    return value or default


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Step 2: create or verify the initial Sentroxis account.")
    parser.add_argument("--db-path", type=Path, default=root / "backend" / "sentroxis.db")
    parser.add_argument("--handoff-path", type=Path, default=root / "backend" / "runtime" / "setup_identity.json")
    parser.add_argument("--name", help="Display name. Omit to enter it at runtime.")
    parser.add_argument("--email", help="Login email. Omit to enter it at runtime.")
    parser.add_argument("--password-stdin", action="store_true", help="Read one password line from standard input; used by the master runner.")
    args = parser.parse_args()

    db_path = args.db_path.expanduser().resolve()
    try:
        account = existing_account(db_path)
    except RuntimeError as error:
        print(f"ERROR: {error}")
        return 1

    if account:
        account_id, existing_name, existing_email, existing_hash, role = account
        print(f"Existing Sentroxis account detected: {existing_email}")
        name = args.name if args.name is not None else prompt_with_default("Sentroxis display name", existing_name)
        email = args.email if args.email is not None else prompt_with_default("Sentroxis login email", existing_email)
    else:
        name = args.name if args.name is not None else input("Sentroxis display name: ").strip()
        email = args.email if args.email is not None else input("Sentroxis login email: ").strip()

    password = sys.stdin.readline().rstrip("\r\n") if args.password_stdin else getpass.getpass("Sentroxis password: ")
    try:
        name, email = validate(name, email, password)
    except ValueError as error:
        print(f"ERROR: {error}")
        return 2

    if account and email != existing_email:
        print(f"ERROR: The existing initial account is {existing_email}. Re-run with that email and its password; this script will not overwrite it.")
        return 1

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as db:
        ensure_users_table(db)
        row = db.execute("SELECT id, name, password_hash, role FROM users WHERE email = ?", (email,)).fetchone()
        count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if row:
            if not password_matches(password, row[2]):
                print("ERROR: Password does not match the existing Sentroxis account. Use the password for this email; the account was not changed.")
                return 1
            account_id, display_name, role = row[0], row[1], row[3]
            print(f"Verified existing Sentroxis account: {email}")
        elif count:
            # This branch is defensive for concurrent changes after the initial lookup.
            print("ERROR: An initial Sentroxis account was created by another process. Re-run and use that account.")
            return 1
        else:
            account_id = f"usr-{secrets.token_hex(12)}"
            role = "admin"
            display_name = name
            db.execute(
                "INSERT INTO users (id, name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (account_id, display_name, email, password_hash(password), role, datetime.now(timezone.utc).isoformat()),
            )
            print(f"Created initial Sentroxis administrator: {email}")

    handoff_path = args.handoff_path.expanduser().resolve()
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(
        json.dumps({"account_id": account_id, "email": email, "name": display_name, "role": role}, indent=2) + "\n",
        encoding="utf-8",
    )
    secure_file(handoff_path)
    print(f"Identity handoff saved (no password): {handoff_path}")
    print(f"Velociraptor initial administrator will be: {email}")
    print("Next: run scripts/03_setup_velociraptor.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
