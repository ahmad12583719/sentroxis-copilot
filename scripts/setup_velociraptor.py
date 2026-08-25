#!/usr/bin/env python3
"""Prepare a verified local Velociraptor server configuration for Sentroxis Copilot.

The script intentionally downloads only an allowlisted Velocidex release, verifies
its SHA-256 hash, then opens Velociraptor's official interactive configuration
wizard. The operator supplies all deployment-specific answers in that wizard. Once
the wizard writes the configuration, this script sets Frontend.bind_port to 8010.

It does not install OS packages, create a service, open firewall rules, or start a
server. Those actions remain explicit operator decisions.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.request import Request, urlopen

RELEASE = "0.77.2"
DOWNLOAD_ROOT = f"https://github.com/Velocidex/velociraptor/releases/download/v{RELEASE}"
USER_AGENT = "Sentroxis-Copilot/0.1"
DEFAULT_FRONTEND_PORT = 8010


@dataclass(frozen=True)
class Asset:
    """A release asset that is pinned to the official download URL and SHA-256."""

    filename: str
    sha256: str
    executable_name: str


ASSETS: dict[tuple[str, str], Asset] = {
    ("linux", "amd64"): Asset(
        "velociraptor-v0.77.2-linux-amd64",
        "6c4c23c466d892788ff56ddcd3a31f844e4c0d797ade454c5e2625eb9e427077",
        "velociraptor",
    ),
    ("linux", "arm64"): Asset(
        "velociraptor-v0.77.2-linux-arm64",
        "54d36c23f374a572a4a60106d896e0e39bc6fcafd0d6150cf56aec6c49454ea0",
        "velociraptor",
    ),
    ("darwin", "amd64"): Asset(
        "velociraptor-v0.77.2-darwin-amd64",
        "900efb29154939e6f594446096975439fc19c59fd74f5433d67bc15cacb4cd99",
        "velociraptor",
    ),
    ("darwin", "arm64"): Asset(
        "velociraptor-v0.77.2-darwin-arm64",
        "3ec2df0c19726b92e27c51ec4b6239aee3e4e40425de39781859eb200987070e",
        "velociraptor",
    ),
    ("windows", "amd64"): Asset(
        "velociraptor-v0.77.2-windows-amd64.exe",
        "686e4f5888fdd66d07ace3b6c1cbd7d2dd0d8d5fb4d3b5d905a7df3341dfb86f",
        "velociraptor.exe",
    ),
}


def normalise_machine(value: str) -> str:
    """Map platform.machine() variants to the release catalog naming."""
    machine = value.lower().replace("_", "-")
    if machine in {"x86-64", "x86_64", "amd64"}:
        return "amd64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    return machine


def detect_asset() -> Asset:
    system = platform.system().lower()
    machine = normalise_machine(platform.machine())
    try:
        return ASSETS[(system, machine)]
    except KeyError as exc:
        supported = ", ".join(f"{name}/{arch}" for name, arch in sorted(ASSETS))
        raise RuntimeError(
            f"Unsupported host platform: {system}/{machine}. Supported platforms: {supported}."
        ) from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_verified(asset: Asset, destination: Path) -> None:
    """Download an allowlisted official binary and atomically install it after hashing."""
    url = f"{DOWNLOAD_ROOT}/{asset.filename}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and sha256_file(destination).lower() == asset.sha256:
        print(f"Verified binary already present: {destination}")
        return

    if destination.exists():
        destination.unlink()
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}.", suffix=".part", dir=destination.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            request = Request(url, headers={"User-Agent": USER_AGENT})
            digest = hashlib.sha256()
            with urlopen(request, timeout=60) as response:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    temporary.write(chunk)
        actual = digest.hexdigest().lower()
        if actual != asset.sha256:
            raise RuntimeError(
                "SHA-256 verification failed. The downloaded file was deleted and no binary was installed."
            )
        os.replace(temporary_path, destination)
        print(f"Downloaded and SHA-256 verified: {destination}")
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def secure_file(path: Path, executable: bool = False) -> None:
    """Restrict generated binary/config files on POSIX hosts."""
    if os.name != "posix":
        return
    mode = stat.S_IRUSR | stat.S_IWUSR
    if executable:
        mode |= stat.S_IXUSR
    path.chmod(mode)


def replace_frontend_port(config_path: Path, port: int) -> bool:
    """Set Frontend.bind_port and synchronize default client URLs without exposing secrets."""
    content = config_path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    in_client = False
    in_server_urls = False
    in_frontend = False
    found_frontend = False
    port_updated = False
    client_urls_updated = 0
    top_level_heading = re.compile(r"^[A-Za-z][A-Za-z0-9_]*:\s*(?:#.*)?(?:\r?\n)?$")
    client_heading = re.compile(r"^Client:\s*(?:#.*)?(?:\r?\n)?$")
    frontend_heading = re.compile(r"^Frontend:\s*(?:#.*)?(?:\r?\n)?$")
    server_urls_heading = re.compile(r"^\s+server_urls:\s*(?:#.*)?(?:\r?\n)?$")
    port_line = re.compile(r"^(\s+bind_port\s*:\s*)\d+(\s*(?:#.*)?)(\r?\n)?$")
    default_client_url = re.compile(
        r"^(\s*-\s*(?:https|wss)://(?:\[[^\]]+\]|[^/:\s]+)):8000((?:/\S*)?)(\s*(?:#.*)?)(\r?\n)?$"
    )

    for index, line in enumerate(lines):
        if top_level_heading.match(line):
            in_client = bool(client_heading.match(line))
            in_frontend = bool(frontend_heading.match(line))
            in_server_urls = False
            found_frontend = found_frontend or in_frontend
            continue
        if in_client and server_urls_heading.match(line):
            in_server_urls = True
            continue
        if in_server_urls and line.lstrip().startswith("-"):
            match = default_client_url.match(line)
            if match:
                newline = match.group(4) or "\n"
                lines[index] = f"{match.group(1)}:{port}{match.group(2)}{match.group(3)}{newline}"
                client_urls_updated += 1
            continue
        if in_server_urls and line.strip() and not line.startswith((" ", "\t")):
            in_server_urls = False
        if not in_frontend:
            continue
        match = port_line.match(line)
        if match:
            newline = match.group(3) or "\n"
            lines[index] = f"{match.group(1)}{port}{match.group(2)}{newline}"
            port_updated = True
            in_frontend = False

    if not found_frontend:
        raise RuntimeError("The generated configuration has no Frontend section; port was not changed.")
    if not port_updated:
        raise RuntimeError("The generated Frontend section has no numeric bind_port; port was not changed.")

    replacement = "".join(lines)
    if replacement == content:
        return False
    temporary = config_path.with_suffix(config_path.suffix + ".tmp")
    temporary.write_text(replacement, encoding="utf-8")
    os.replace(temporary, config_path)
    if client_urls_updated:
        print(f"Synchronized {client_urls_updated} default client URL(s) to frontend port {port}.")
    return True


def run_wizard(binary: Path, workdir: Path) -> int:
    print("\nVelociraptor's official interactive configuration wizard is starting now.")
    print("Provide your deployment-specific values in the wizard, including its normal security prompts.")
    print("For the output filename, accept 'server.config.yaml' unless you passed --config with another path.\n")
    result = subprocess.run([str(binary), "config", "generate", "-i"], cwd=workdir, check=False)
    return result.returncode


def build_parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Download, verify, and interactively configure Velociraptor for Sentroxis Copilot."
    )
    parser.add_argument(
        "--install-dir",
        type=Path,
        default=root / "backend" / "runtime" / "velociraptor",
        help="Directory for the verified binary and generated configuration.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Configuration file path. Defaults to <install-dir>/server.config.yaml.",
    )
    parser.add_argument(
        "--frontend-port",
        type=int,
        default=DEFAULT_FRONTEND_PORT,
        help=f"Frontend client bind port to enforce after the wizard (default: {DEFAULT_FRONTEND_PORT}).",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Use an already present binary only after its pinned SHA-256 is verified.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the detected platform and official asset without downloading or starting the wizard.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.frontend_port <= 65535:
        print("ERROR: --frontend-port must be between 1 and 65535.", file=sys.stderr)
        return 2

    try:
        asset = detect_asset()
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    install_dir = args.install_dir.expanduser().resolve()
    config_path = (args.config.expanduser().resolve() if args.config else install_dir / "server.config.yaml")
    binary = install_dir / asset.executable_name
    url = f"{DOWNLOAD_ROOT}/{asset.filename}"

    print(f"Detected platform: {platform.system().lower()}/{normalise_machine(platform.machine())}")
    print(f"Allowlisted release: Velociraptor {RELEASE}")
    print(f"Official asset: {url}")
    print(f"Expected SHA-256: {asset.sha256}")
    print(f"Configuration path: {config_path}")
    print(f"Frontend port policy: {args.frontend_port}")

    if args.dry_run:
        print("Dry run complete. No file was downloaded and no wizard was started.")
        return 0

    try:
        if args.skip_download:
            if not binary.is_file():
                raise RuntimeError(f"No existing binary found at {binary}.")
            if sha256_file(binary).lower() != asset.sha256:
                raise RuntimeError("Existing binary checksum does not match the allowlisted official release.")
            print(f"Existing binary SHA-256 verified: {binary}")
        else:
            download_verified(asset, binary)
        secure_file(binary, executable=True)
    except (OSError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    exit_code = run_wizard(binary, install_dir)
    if exit_code:
        print(f"The configuration wizard exited with code {exit_code}; no configuration was modified.", file=sys.stderr)
        return exit_code
    if not config_path.is_file():
        print(
            f"ERROR: Expected configuration was not found at {config_path}. "
            "Run again and use the displayed configuration filename in the wizard.",
            file=sys.stderr,
        )
        return 1

    try:
        changed = replace_frontend_port(config_path, args.frontend_port)
        secure_file(config_path)
    except (OSError, RuntimeError) as error:
        print(f"ERROR: The generated configuration was not changed: {error}", file=sys.stderr)
        return 1

    state = "updated" if changed else "already set"
    print(f"\nConfiguration complete. Frontend.bind_port is {state} to {args.frontend_port}.")
    print(f"Keep this configuration file private: {config_path}")
    print("The script deliberately does not start Velociraptor. Review the config before starting it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
