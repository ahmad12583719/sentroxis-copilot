#!/usr/bin/env python3
"""Unified Sentroxis installer entry point.

The installer creates a fresh local web-login account once, then offers an
installation menu. Plaintext passwords are held only in process memory and are
passed to the Velociraptor runner through standard input, never through a file
or command-line argument.
"""
from __future__ import annotations

import getpass
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VELO_DIR = ROOT / "Velociraptor"
BACKEND_DIR = ROOT / "backend"
DB_PATH = BACKEND_DIR / "sentroxis.db"
IDENTITY_PATH = BACKEND_DIR / "runtime" / "velociraptor" / "setup-identity.json"


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


def create_fresh_sentroxis_account() -> tuple[str, str]:
    reset_previous_sentroxis_state()
    ensure_auth_schema()
    from backend.core.auth import configure_auth_db, register_first_user

    configure_auth_db(str(DB_PATH))
    name = ask("Sentroxis display name")
    email = ask("Sentroxis login email").lower()
    while True:
        password = getpass.getpass("Sentroxis web-login password (minimum 12 characters): ")
        confirm = getpass.getpass("Confirm Sentroxis web-login password: ")
        if password != confirm:
            print("ERROR: Passwords do not match. Try again.")
            continue
        try:
            principal = register_first_user(name, email, password)
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


def run_wazuh() -> int:
    script = ROOT / "wazuh_installation.sh"
    if not script.is_file():
        print(f"ERROR: Wazuh installer not found: {script}")
        return 1
    if not os.access(script, os.X_OK):
        print(f"ERROR: Wazuh installer is not executable: {script}")
        print(f"Run: chmod 700 {script}")
        return 1
    print("\nStarting the existing Wazuh installation workflow. Wazuh owns its own files and prompts.")
    try:
        completed = subprocess.run(["sudo", str(script)], cwd=ROOT, check=False)
    except FileNotFoundError:
        print("ERROR: sudo is not available; run the Wazuh installer manually with the required privileges.")
        return 1
    return completed.returncode


def run_velociraptor(password: str) -> int:
    runner = VELO_DIR / "00_run_all_setup.py"
    command = [sys.executable, str(runner), "--identity-path", str(IDENTITY_PATH), "--password-stdin"]
    print("\nStarting the Velociraptor installation workflow with the same Sentroxis web-login identity.")
    completed = subprocess.run(command, cwd=ROOT, input=password + "\n", text=True, check=False)
    return completed.returncode


def installation_menu(password: str) -> int:
    while True:
        print("\nWhat would you like to install?")
        print("1. Install Wazuh")
        print("2. Install Velociraptor")
        print("3. Exit installer")
        choice = input("Select an option [1-3]: ").strip()
        if choice == "1":
            result = run_wazuh()
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
    print("=== Sentroxis fresh installation ===")
    print("Task 01: create the fresh Sentroxis web-login account")
    try:
        _, password = create_fresh_sentroxis_account()
        return installation_menu(password)
    except KeyboardInterrupt:
        print("\nInstaller cancelled by user.")
        return 130
    except (OSError, RuntimeError) as error:
        print(f"ERROR: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
