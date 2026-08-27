#!/usr/bin/env python3
"""Master runner: execute the verified three-step local setup workflow.

Password handoff uses process standard input only. The password is never saved to
files, printed, or passed as a command-line argument.
"""

from __future__ import annotations

import argparse
import getpass
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    return ask(f"{prompt} (y/n)", "y" if default else "n").lower() in {"y", "yes"}


def run(command: list[str], password: str | None = None) -> None:
    subprocess.run(command, cwd=ROOT, input=(password + "\n") if password is not None else None, text=True, check=True)


def existing_identity() -> tuple[str, str] | None:
    """Read the one local account, if any, without changing the database."""
    db_path = ROOT / "backend" / "sentroxis.db"
    if not db_path.is_file():
        return None
    try:
        with sqlite3.connect(db_path) as db:
            has_users = db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'").fetchone()
            if not has_users:
                return None
            row = db.execute("SELECT name, email FROM users ORDER BY created_at LIMIT 1").fetchone()
            return tuple(row) if row else None
    except sqlite3.Error:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run all Sentroxis self-signed Velociraptor setup scripts.")
    parser.add_argument("--platform", default="auto", choices=["auto", "linux-amd64", "linux-arm64", "darwin-amd64", "darwin-arm64", "windows-amd64"])
    parser.add_argument("--force", action="store_true", help="Replace any existing verified binary or configuration files.")
    args = parser.parse_args()

    print("==> Step 1/3: prepare verified Velociraptor installation files")
    install_command = [sys.executable, str(SCRIPTS / "01_installation_files.py"), "--platform", args.platform]
    if args.force:
        install_command.append("--force")
    try:
        run(install_command)
    except subprocess.CalledProcessError as error:
        print(f"ERROR: Step 1 failed with exit code {error.returncode}")
        return error.returncode or 1

    print("\n==> Step 2/3: create or verify Sentroxis account")
    account = existing_identity()
    if account:
        existing_name, existing_email = account
        print(f"Existing Sentroxis account detected: {existing_email}")
        name = ask("Sentroxis display name", existing_name)
        email = ask("Sentroxis login email", existing_email).lower()
    else:
        name = ask("Sentroxis display name")
        email = ask("Sentroxis login email").lower()
    password = getpass.getpass("Sentroxis password (minimum 12 characters): ")
    try:
        run([sys.executable, str(SCRIPTS / "02_signup_credentials.py"), "--name", name, "--email", email, "--password-stdin"], password)
    except subprocess.CalledProcessError as error:
        print(f"ERROR: Step 2 failed with exit code {error.returncode}")
        return error.returncode or 1

    print("\n==> Step 3/3: create self-signed Velociraptor server and client configuration")
    server_os = ask("Server operating system (linux/windows/darwin)", "linux").lower()
    datastore_default = str(Path.home() / ".sentroxis" / "velociraptor") if server_os == "linux" else "C:\\Velociraptor"
    datastore = ask("Datastore directory", datastore_default)
    logs = ask("Logs directory", str(Path(datastore) / "logs"))
    certificate_years = ask("Internal certificate lifetime in years (1/2/10)", "1")
    frontend_host = ask("Public frontend DNS name or server IP")
    gui_port = ask("GUI port", "8889")
    websocket = ask_yes_no("Use experimental WebSocket communications", False)
    registry_writeback = ask_yes_no("Use Windows registry client writeback", False)
    setup_command = [
        sys.executable, str(SCRIPTS / "03_setup_velociraptor.py"),
        "--server-os", server_os,
        "--datastore-path", datastore,
        "--log-path", logs,
        "--certificate-years", certificate_years,
        "--frontend-host", frontend_host,
        "--gui-port", gui_port,
        "--password-stdin",
        "--websocket" if websocket else "--no-websocket",
        "--registry-writeback" if registry_writeback else "--no-registry-writeback",
    ]
    if args.force:
        setup_command.append("--force")
    try:
        run(setup_command, password)
    except subprocess.CalledProcessError as error:
        print(f"ERROR: Step 3 failed with exit code {error.returncode}")
        return error.returncode or 1

    print("\nAll setup scripts completed successfully.")
    print(f"Endpoint client configuration path: {ROOT / 'backend' / 'runtime' / 'velociraptor' / 'client.config.yaml'}")
    print(f"Local API configuration path: {ROOT / 'backend' / 'runtime' / 'velociraptor' / 'api.config.yaml'}")
    print("Review server.config.yaml before starting the project with ./startup.sh.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nSetup cancelled by user. Re-run this command to resume any interrupted download.")
        raise SystemExit(130)
