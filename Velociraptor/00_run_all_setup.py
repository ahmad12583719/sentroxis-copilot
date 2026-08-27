#!/usr/bin/env python3
"""Run the Velociraptor installation/configuration steps after Task 01 sign-up."""
from __future__ import annotations

import argparse
import getpass
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VELO_DIR = ROOT / "Velociraptor"
DEFAULT_IDENTITY = ROOT / "backend" / "runtime" / "velociraptor" / "setup-identity.json"


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    return ask(f"{prompt} (y/n)", "y" if default else "n").lower() in {"y", "yes"}


def identity_email(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        email = str(payload["email"]).strip().lower()
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise RuntimeError(f"Invalid Task 01 identity handoff: {path}") from error
    if "@" not in email:
        raise RuntimeError(f"Task 01 identity does not contain a valid email: {path}")
    return email


def run(command: list[str], stdin_text: str | None = None) -> int:
    return subprocess.run(command, cwd=ROOT, input=stdin_text, text=True, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Velociraptor installation files and configuration using the Task 01 web identity.")
    parser.add_argument("--platform", default="auto", choices=["auto", "linux-amd64", "linux-arm64", "darwin-amd64", "darwin-arm64", "windows-amd64"])
    parser.add_argument("--force", action="store_true", help="Replace existing verified binary and configuration files.")
    parser.add_argument("--identity-path", type=Path, default=DEFAULT_IDENTITY, help="Task 01 identity handoff containing email only.")
    parser.add_argument("--password-stdin", action="store_true", help="Read the Task 01 password from standard input.")
    args = parser.parse_args()

    email = identity_email(args.identity_path.expanduser().resolve())
    password = sys.stdin.readline().rstrip("\n") if args.password_stdin else getpass.getpass(f"Password for {email}: ")
    if not password:
        print("ERROR: A password is required to verify the Task 01 Sentroxis account.")
        return 2

    print("==> Velociraptor Step 1/2: prepare verified installation files")
    install_command = [sys.executable, str(VELO_DIR / "01_installation_files.py"), "--platform", args.platform]
    if args.force:
        install_command.append("--force")
    result = run(install_command)
    if result:
        print(f"ERROR: Velociraptor installation-file step failed with exit code {result}")
        return result

    print("\n==> Velociraptor Step 2/2: create server, client, and API configuration")
    server_os = ask("Server operating system (linux/windows/darwin)", "linux").lower()
    datastore_default = str(Path.home() / ".sentroxis" / "velociraptor") if server_os == "linux" else "C:\\Velociraptor"
    datastore = ask("Datastore directory", datastore_default)
    logs = ask("Logs directory", str(Path(datastore).expanduser() / "logs"))
    certificate_years = ask("Internal certificate lifetime in years (1/2/10)", "1")
    frontend_host = ask("Public frontend DNS name or server IP")
    gui_port = ask("GUI port", "8889")
    websocket = ask_yes_no("Use experimental WebSocket communications", False)
    registry_writeback = ask_yes_no("Use Windows registry client writeback", False)
    setup_command = [
        sys.executable, str(VELO_DIR / "03_setup_velociraptor.py"),
        "--server-os", server_os, "--datastore-path", datastore, "--log-path", logs,
        "--certificate-years", certificate_years, "--frontend-host", frontend_host,
        "--gui-port", gui_port, "--identity-path", str(args.identity_path.expanduser().resolve()),
        "--password-stdin", "--websocket" if websocket else "--no-websocket",
        "--registry-writeback" if registry_writeback else "--no-registry-writeback",
    ]
    if args.force:
        setup_command.append("--force")
    result = run(setup_command, password + "\n")
    if result:
        print(f"ERROR: Velociraptor configuration step failed with exit code {result}")
        return result

    runtime = ROOT / "backend" / "runtime" / "velociraptor"
    print("\nVelociraptor setup completed successfully.")
    print(f"Server configuration path: {runtime / 'server.config.yaml'}")
    print(f"Endpoint client configuration path: {runtime / 'client.config.yaml'}")
    print(f"Local API configuration path: {runtime / 'api.config.yaml'}")
    print("Start the project with ./startup.sh after reviewing server.config.yaml.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nVelociraptor setup cancelled by user.")
        raise SystemExit(130)
