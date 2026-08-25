#!/usr/bin/env python3
"""Step 3 of 3: generate self-signed Velociraptor server and client configuration.

This script uses the verified binary recorded by Step 1 and the email identity
recorded by Step 2. The same password is requested again (or received directly
from the master runner), verified against Sentroxis, and converted to Velociraptor's
salted password hash without ever being written as plaintext.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

FRONTEND_PORT = 8010
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9@.\-_#+]{1,120}$")
HOST_PATTERN = re.compile(r"^[A-Za-z0-9.-]{1,253}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def password_matches(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (TypeError, ValueError):
        return False


def secure_file(path: Path) -> None:
    if os.name == "posix":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    answer = ask(f"{prompt} (y/n)", "y" if default else "n").lower()
    return answer in {"y", "yes"}


def load_identity(path: Path) -> dict[str, str]:
    try:
        identity = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(identity.get("email"), str) or not identity["email"]:
            raise ValueError("email missing")
        return identity
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Unable to read Step 2 identity handoff: {error}") from error


def verify_account(db_path: Path, email: str, password: str) -> None:
    try:
        with sqlite3.connect(db_path) as db:
            row = db.execute("SELECT password_hash FROM users WHERE email = ?", (email,)).fetchone()
    except sqlite3.Error as error:
        raise RuntimeError(f"Unable to read Sentroxis account database: {error}") from error
    if not row or not password_matches(password, row[0]):
        raise RuntimeError("Password does not match the Step 2 Sentroxis account")


def run_config_command(command: list[str], output_path: Path, runtime_dir: Path) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=f".{output_path.name}.", suffix=".tmp", dir=runtime_dir, delete=False) as output:
            temporary_path = Path(output.name)
            result = subprocess.run(command, cwd=runtime_dir, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.PIPE, timeout=90, check=False)
        if result.returncode != 0:
            raise RuntimeError("Velociraptor configuration command failed")
        os.replace(temporary_path, output_path)
        temporary_path = None
        secure_file(output_path)
    finally:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Step 3: create self-signed Velociraptor server and client configuration.")
    parser.add_argument("--install-dir", type=Path, default=root / "backend" / "runtime" / "velociraptor")
    parser.add_argument("--db-path", type=Path, default=root / "backend" / "sentroxis.db")
    parser.add_argument("--identity-path", type=Path, default=root / "backend" / "runtime" / "setup_identity.json")
    parser.add_argument("--server-os", choices=["linux", "windows", "darwin"], help="The operating system where the server will be deployed.")
    parser.add_argument("--datastore-path", help="Directory for Velociraptor datastore files.")
    parser.add_argument("--log-path", help="Directory for Velociraptor logs; defaults to <datastore>/logs.")
    parser.add_argument("--certificate-years", type=int, choices=[1, 2, 10], help="Internal certificate validity period.")
    parser.add_argument("--frontend-host", help="Public frontend DNS name or server IP address.")
    parser.add_argument("--gui-port", type=int, help="Velociraptor GUI port; frontend remains fixed at 8010.")
    parser.add_argument("--websocket", action=argparse.BooleanOptionalAction, default=None, help="Use experimental WebSocket client communications.")
    parser.add_argument("--registry-writeback", action=argparse.BooleanOptionalAction, default=None, help="Use Windows registry client writeback.")
    parser.add_argument("--password-stdin", action="store_true", help="Read the current Step 2 password from standard input.")
    parser.add_argument("--force", action="store_true", help="Replace existing server/client configuration files.")
    args = parser.parse_args()

    runtime_dir = args.install_dir.expanduser().resolve()
    state_path = runtime_dir / "installation.json"
    try:
        installation = json.loads(state_path.read_text(encoding="utf-8"))
        binary = Path(installation["binary_path"])
        expected_hash = str(installation["sha256"]).lower()
        if not installation.get("verified") or not binary.is_file() or sha256_file(binary).lower() != expected_hash:
            raise RuntimeError("Step 1 verified binary is missing or its SHA-256 no longer matches")
        identity = load_identity(args.identity_path.expanduser().resolve())
    except (KeyError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}")
        return 1

    password = sys.stdin.readline().rstrip("\r\n") if args.password_stdin else getpass.getpass("Confirm current Sentroxis password: ")
    try:
        verify_account(args.db_path.expanduser().resolve(), identity["email"], password)
    except RuntimeError as error:
        print(f"ERROR: {error}")
        return 1

    server_os = args.server_os or ask("Server operating system (linux/windows/darwin)", "linux").lower()
    datastore_path = args.datastore_path or ask("Datastore directory", "/opt/velociraptor" if server_os == "linux" else "C:\\Velociraptor")
    log_path = args.log_path if args.log_path is not None else ask("Logs directory", str(Path(datastore_path) / "logs"))
    certificate_years = args.certificate_years or int(ask("Internal certificate lifetime in years", "1"))
    frontend_host = args.frontend_host or ask("Public frontend DNS name or server IP")
    gui_port = args.gui_port or int(ask("GUI port", "8889"))
    websocket = args.websocket if args.websocket is not None else ask_yes_no("Use experimental WebSocket communications", False)
    registry_writeback = args.registry_writeback if args.registry_writeback is not None else ask_yes_no("Use Windows registry client writeback", False)

    if server_os not in {"linux", "windows", "darwin"}:
        print("ERROR: Server OS must be linux, windows, or darwin")
        return 2
    if certificate_years not in {1, 2, 10}:
        print("ERROR: Certificate lifetime must be 1, 2, or 10 years")
        return 2
    if not HOST_PATTERN.fullmatch(frontend_host):
        print("ERROR: Frontend host must be a DNS name or IP address")
        return 2
    if not 1 <= gui_port <= 65535:
        print("ERROR: GUI port must be between 1 and 65535")
        return 2
    if not USERNAME_PATTERN.fullmatch(identity["email"]):
        print("ERROR: Step 2 email cannot be used as a Velociraptor username")
        return 2

    config_path = runtime_dir / "server.config.yaml"
    client_path = runtime_dir / "client.config.yaml"
    if (config_path.exists() or client_path.exists()) and not args.force:
        print("ERROR: Existing server.config.yaml or client.config.yaml found. Back it up, remove it, or pass --force.")
        return 1
    for path in (config_path, client_path):
        if path.exists() and args.force:
            path.unlink()

    frontend_url = f"{'wss' if websocket else 'https'}://{frontend_host}:{FRONTEND_PORT}/"
    salt = secrets.token_bytes(32)
    password_hash = hashlib.sha256(salt + password.encode("utf-8")).hexdigest()
    merge_payload: dict[str, object] = {
        "Datastore": {"implementation": "FileBaseDataStore", "location": str(Path(datastore_path).expanduser()), "filestore_directory": str(Path(datastore_path).expanduser())},
        "Logging": {"output_directory": str(Path(log_path).expanduser()), "separate_logs_per_component": True},
        "Security": {"certificate_validity_days": certificate_years * 365},
        "Frontend": {"hostname": frontend_host, "bind_address": "0.0.0.0", "bind_port": FRONTEND_PORT},
        "GUI": {
            "bind_address": "127.0.0.1",
            "bind_port": gui_port,
            "public_url": f"https://{frontend_host}:{gui_port}/app/index.html",
            "authenticator": {"type": "Basic"},
            "initial_users": [{"name": identity["email"], "password_hash": password_hash, "password_salt": salt.hex()}],
        },
        "Client": {"server_urls": [frontend_url], "use_self_signed_ssl": True},
    }
    if registry_writeback:
        merge_payload["Client"]["writeback_windows"] = "HKLM\\SOFTWARE\\Velocidex\\Velociraptor"

    merge_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".setup-merge.", suffix=".json", dir=runtime_dir, delete=False) as merge_file:
            merge_path = Path(merge_file.name)
            json.dump(merge_payload, merge_file)
        secure_file(merge_path)
        run_config_command([str(binary), "config", "generate", "--merge_file", str(merge_path)], config_path, runtime_dir)
        run_config_command([str(binary), "--config", str(config_path), "config", "client"], client_path, runtime_dir)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        config_path.unlink(missing_ok=True)
        client_path.unlink(missing_ok=True)
        print(f"ERROR: {error}")
        return 1
    finally:
        if merge_path:
            merge_path.unlink(missing_ok=True)

    summary_path = runtime_dir / "setup-summary.json"
    summary_path.write_text(
        json.dumps({"server_os": server_os, "deployment": "self_signed_basic", "frontend_url": frontend_url, "frontend_port": FRONTEND_PORT, "gui_port": gui_port, "administrator": identity["email"], "server_config": str(config_path), "client_config": str(client_path)}, indent=2) + "\n",
        encoding="utf-8",
    )
    secure_file(summary_path)
    print("Self-Signed Basic configuration completed.")
    print(f"Initial Velociraptor administrator: {identity['email']}")
    print(f"Frontend client URL: {frontend_url}")
    print(f"Server configuration saved: {config_path}")
    print(f"Client configuration saved: {client_path}")
    print("Copy client.config.yaml securely to the client packaging/deployment process; it is not printed to the terminal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
