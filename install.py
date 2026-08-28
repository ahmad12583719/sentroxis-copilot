#!/usr/bin/env python3
"""Unified Sentroxis installer entry point.

The installer creates a fresh local web-login account once, then offers an
installation menu. The Sentroxis password is passed to the Velociraptor runner
through standard input and to the Wazuh installer through a protected temporary
environment file; secrets are never placed in command-line arguments.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import os
import secrets
import shutil
import shlex
import sqlite3
import string
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
VELO_DIR = ROOT / "Velociraptor"
BACKEND_DIR = ROOT / "backend"
DB_PATH = BACKEND_DIR / "sentroxis.db"
IDENTITY_PATH = BACKEND_DIR / "runtime" / "velociraptor" / "setup-identity.json"
WAZUH_HANDOFF_PATH = ROOT / "runtime" / ".wazuh-install.env"
WAZUH_PASSWORD_LENGTH = 32
WAZUH_PASSWORD_SPECIALS = "@#%+=:,._/-!"


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    answer = ask(f"{prompt} (y/n)", "y" if default else "n").lower()
    return answer in {"y", "yes"}


def ensure_auth_schema() -> None:
    BACKEND_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            """
        )


def reset_previous_sentroxis_state() -> None:
    """Remove only local Sentroxis account state after explicit confirmation."""
    if not DB_PATH.exists():
        return
    print(f"Existing local Sentroxis state found: {DB_PATH}")
    if not ask_yes_no("Forget the existing Sentroxis account and local application state? This cannot be undone", False):
        raise RuntimeError("Fresh sign-up cancelled; existing account was preserved")
    for path in (DB_PATH, Path(f"{DB_PATH}-wal"), Path(f"{DB_PATH}-shm")):
        path.unlink(missing_ok=True)
    print("Previous Sentroxis account state forgotten. Wazuh files and data were not changed.")


@dataclass(frozen=True)
class InstallerPrincipal:
    subject: str
    role: str
    name: str
    email: str


def register_local_first_user(name: str, email: str, password: str) -> InstallerPrincipal:
    """Create the same PBKDF2 account record without importing FastAPI."""
    normalized_name = " ".join(name.strip().split())
    normalized_email = email.strip().lower()
    if not normalized_name or len(normalized_name) > 120:
        raise ValueError("Name must be between 1 and 120 characters")
    if "@" not in normalized_email or len(normalized_email) > 320:
        raise ValueError("Enter a valid email address")
    if len(password) < 12 or len(password) > 128:
        raise ValueError("Password must be between 12 and 128 characters")
    with sqlite3.connect(DB_PATH) as db:
        if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise PermissionError("Initial registration is already closed")
        user_id = f"usr-{secrets.token_hex(12)}"
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210_000)
        stored_hash = f"pbkdf2_sha256$210000${salt.hex()}${digest.hex()}"
        db.execute(
            "INSERT INTO users (id, name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (user_id, normalized_name, normalized_email, stored_hash, "admin"),
        )
    return InstallerPrincipal(subject=user_id, role="admin", name=normalized_name, email=normalized_email)


def register_installer_user(name: str, email: str, password: str):
    """Prefer the backend auth implementation, with a fresh-checkout fallback."""
    try:
        from backend.core.auth import register_first_user
    except ModuleNotFoundError as error:
        if error.name != "fastapi":
            raise
        print("FastAPI is not installed yet; using the installer’s local authentication bootstrap.")
        return register_local_first_user(name, email, password)
    return register_first_user(name, email, password)


def validate_wazuh_compatible_password(password: str) -> None:
    """Ensure the shared password satisfies the Wazuh installer policy."""
    if len(password) < 20:
        raise ValueError("Password must contain at least 20 characters for Wazuh")
    if any(character.isspace() or not character.isprintable() for character in password):
        raise ValueError("Password must contain printable non-whitespace characters only")
    if not (
        any(character.isupper() for character in password)
        and any(character.islower() for character in password)
        and any(character.isdigit() for character in password)
        and any(not character.isalnum() for character in password)
    ):
        raise ValueError("Password must include uppercase, lowercase, a number, and a special character for Wazuh")


def generate_wazuh_password() -> str:
    """Generate a strong shell-safe Wazuh internal password."""
    alphabet = string.ascii_letters + string.digits + WAZUH_PASSWORD_SPECIALS
    characters = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(WAZUH_PASSWORD_SPECIALS),
    ]
    characters.extend(secrets.choice(alphabet) for _ in range(WAZUH_PASSWORD_LENGTH - len(characters)))
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


def write_wazuh_handoff(shared_password: str) -> None:
    """Write a temporary protected handoff for sudo without putting secrets in argv."""
    WAZUH_HANDOFF_PATH.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "WAZUH_INDEXER_PASSWORD": shared_password,
        "WAZUH_DASHBOARD_PASSWORD": generate_wazuh_password(),
        "WAZUH_API_PASSWORD": generate_wazuh_password(),
    }
    content = "".join(f"{key}={shlex.quote(value)}\n" for key, value in values.items())
    WAZUH_HANDOFF_PATH.write_text(content, encoding="utf-8")
    WAZUH_HANDOFF_PATH.chmod(0o600)


def sign_in_existing_account() -> tuple[str, str]:
    """Authenticate an existing local account for the shared installer workflow."""
    ensure_auth_schema()
    email = ask("Sentroxis login email").lower()
    while True:
        password = getpass.getpass("Sentroxis/Wazuh admin password: ")
        try:
            from backend.core.auth import authenticate, configure_auth_db
            configure_auth_db(str(DB_PATH))
            principal = authenticate(email, password)
        except ModuleNotFoundError as error:
            if error.name != "fastapi":
                raise
            with sqlite3.connect(DB_PATH) as db:
                row = db.execute("SELECT id, name, email, role, password_hash FROM users WHERE email = ?", (email,)).fetchone()
            principal = None
            if row:
                algorithm, iterations, salt_hex, digest_hex = row[4].split("$", 3)
                candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)).hex()
                if algorithm == "pbkdf2_sha256" and hmac.compare_digest(candidate, digest_hex):
                    principal = InstallerPrincipal(subject=row[0], name=row[1], email=row[2], role=row[3])
        if principal is not None:
            validate_wazuh_compatible_password(password)
            IDENTITY_PATH.parent.mkdir(parents=True, exist_ok=True)
            IDENTITY_PATH.write_text(json.dumps({"account_id": principal.subject, "email": principal.email, "name": principal.name, "role": principal.role}, indent=2) + "\n", encoding="utf-8")
            IDENTITY_PATH.chmod(0o600)
            print(f"Existing Sentroxis account signed in: {principal.email}")
            return principal.email, password
        print("ERROR: Invalid Sentroxis email or password. Try again.")


def choose_installer_account() -> tuple[str, str]:
    ensure_auth_schema()
    with sqlite3.connect(DB_PATH) as db:
        has_account = db.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
    if not has_account:
        return create_fresh_sentroxis_account()
    print("\nAn existing Sentroxis account was found.")
    print("1. Sign in with the existing account")
    print("2. Forget it and create a fresh account")
    print("3. Exit installer")
    choice = ask("Select an account action", "1")
    if choice == "1":
        return sign_in_existing_account()
    if choice == "2":
        return create_fresh_sentroxis_account()
    raise RuntimeError("Installer exited without changing the existing account")


def create_fresh_sentroxis_account() -> tuple[str, str]:
    reset_previous_sentroxis_state()
    ensure_auth_schema()
    try:
        from backend.core.auth import configure_auth_db
    except ModuleNotFoundError as error:
        if error.name != "fastapi":
            raise
        configure_auth_db = None
    if configure_auth_db is not None:
        configure_auth_db(str(DB_PATH))
    name = ask("Sentroxis display name")
    email = ask("Sentroxis login email").lower()
    while True:
        password = getpass.getpass("Sentroxis/Wazuh admin password (minimum 20 characters): ")
        confirm = getpass.getpass("Confirm Sentroxis/Wazuh admin password: ")
        if password != confirm:
            print("ERROR: Passwords do not match. Try again.")
            continue
        try:
            validate_wazuh_compatible_password(password)
            principal = register_installer_user(name, email, password)
        except (ValueError, PermissionError) as error:
            print(f"ERROR: {error}")
            if isinstance(error, PermissionError):
                raise
            continue
        break
    IDENTITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    IDENTITY_PATH.write_text(json.dumps({"account_id": principal.subject, "email": principal.email, "name": principal.name, "role": principal.role}, indent=2) + "\n", encoding="utf-8")
    IDENTITY_PATH.chmod(0o600)
    print(f"Fresh Sentroxis account created: {principal.email}")
    print(f"Identity handoff saved without password: {IDENTITY_PATH}")
    return principal.email, password


def run_wazuh(password: str) -> int:
    script = ROOT / "wazuh_installation.sh"
    if not script.is_file():
        print(f"ERROR: Wazuh installer not found: {script}")
        return 1
    if not os.access(script, os.X_OK):
        print(f"ERROR: Wazuh installer is not executable: {script}")
        print(f"Run: chmod 700 {script}")
        return 1
    print("\nStarting Wazuh with the shared Sentroxis/Wazuh admin password.")
    print("Wazuh Dashboard login: username admin; use the Sentroxis password.")
    print("Internal kibanaserver and wazuh-wui passwords will be generated and stored locally.")
    try:
        write_wazuh_handoff(password)
        handoff = shlex.quote(str(WAZUH_HANDOFF_PATH))
        installer = shlex.quote(str(script))
        command = [
            "sudo",
            "bash",
            "-c",
            f"set -a; source {handoff}; set +a; exec {installer}",
        ]
        completed = subprocess.run(command, cwd=ROOT, check=False)
    except FileNotFoundError:
        print("ERROR: sudo is not available; run the Wazuh installer manually with the required privileges.")
        return 1
    finally:
        WAZUH_HANDOFF_PATH.unlink(missing_ok=True)
    return completed.returncode


def run_velociraptor(password: str) -> int:
    runner = VELO_DIR / "00_run_all_setup.py"
    command = [sys.executable, str(runner), "--identity-path", str(IDENTITY_PATH), "--password-stdin"]
    print("\nStarting the Velociraptor installation workflow with the same Sentroxis web-login identity.")
    if os.name != "posix":
        # Windows has no portable pass_fds equivalent; stdin is used only for the password there.
        return subprocess.run(command, cwd=ROOT, input=password + "\n", text=True, check=False).returncode
    password_read, password_write = os.pipe()
    try:
        os.write(password_write, (password + "\n").encode("utf-8"))
    finally:
        os.close(password_write)
    environment = os.environ.copy()
    environment["SENTROXIS_PASSWORD_FD"] = str(password_read)
    try:
        # Leave stdin inherited so the child can ask for all remaining config values interactively.
        return subprocess.run(command, cwd=ROOT, text=True, check=False, env=environment, pass_fds=(password_read,)).returncode
    finally:
        os.close(password_read)


def installation_menu(password: str) -> int:
    while True:
        print("\nWhat would you like to install?")
        print("1. Install Wazuh")
        print("2. Install Velociraptor")
        print("3. Exit installer")
        try:
            choice = input("Select an option [1-3]: ").strip()
        except EOFError:
            print("\nInstaller input closed; returning to the shell.")
            return 0
        if choice == "1":
            result = run_wazuh(password)
            print(f"Wazuh installation finished with exit code {result}.")
            continue
        if choice == "2":
            result = run_velociraptor(password)
            print(f"Velociraptor installation finished with exit code {result}.")
            continue
        if choice == "3":
            print("Installer exited. The Sentroxis web account remains available for login.")
            return 0
        print("Please select 1, 2, or 3.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fresh Sentroxis sign-up followed by the Wazuh/Velociraptor installation menu.")
    parser.parse_args()
    print("=== Sentroxis fresh installation ===")
    print("Task 01: create the fresh Sentroxis web-login account")
    try:
        _, password = choose_installer_account()
        return installation_menu(password)
    except KeyboardInterrupt:
        print("\nInstaller cancelled by user.")
        return 130
    except (OSError, RuntimeError) as error:
        print(f"ERROR: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
