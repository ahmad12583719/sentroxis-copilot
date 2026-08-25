#!/usr/bin/env python3
"""Step 1 of 3: download and verify the local Velociraptor binary.

Only the pinned official Velocidex release assets in ASSETS are accepted. The
script does not install operating-system packages, create services, alter firewall
rules, or start a server.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform as host_platform
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

RELEASE = "0.77.2"
DOWNLOAD_ROOT = f"https://github.com/Velocidex/velociraptor/releases/download/v{RELEASE}"
USER_AGENT = "Sentroxis-Copilot/0.1"


@dataclass(frozen=True)
class Asset:
    filename: str
    sha256: str
    binary_name: str


ASSETS: dict[str, Asset] = {
    "linux-amd64": Asset("velociraptor-v0.77.2-linux-amd64", "6c4c23c466d892788ff56ddcd3a31f844e4c0d797ade454c5e2625eb9e427077", "velociraptor"),
    "linux-arm64": Asset("velociraptor-v0.77.2-linux-arm64", "54d36c23f374a572a4a60106d896e0e39bc6fcafd0d6150cf56aec6c49454ea0", "velociraptor"),
    "darwin-amd64": Asset("velociraptor-v0.77.2-darwin-amd64", "900efb29154939e6f594446096975439fc19c59fd74f5433d67bc15cacb4cd99", "velociraptor"),
    "darwin-arm64": Asset("velociraptor-v0.77.2-darwin-arm64", "3ec2df0c19726b92e27c51ec4b6239aee3e4e40425de39781859eb200987070e", "velociraptor"),
    "windows-amd64": Asset("velociraptor-v0.77.2-windows-amd64.exe", "686e4f5888fdd66d07ace3b6c1cbd7d2dd0d8d5fb4d3b5d905a7df3341dfb86f", "velociraptor.exe"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def detected_platform() -> str:
    system = host_platform.system().lower()
    machine = host_platform.machine().lower().replace("_", "-")
    if machine in {"x86-64", "amd64"}:
        machine = "amd64"
    elif machine in {"aarch64", "arm64"}:
        machine = "arm64"
    if system == "windows" and machine == "amd64":
        return "windows-amd64"
    if system == "linux" and machine in {"amd64", "arm64"}:
        return f"linux-{machine}"
    if system == "darwin" and machine in {"amd64", "arm64"}:
        return f"darwin-{machine}"
    raise RuntimeError(f"Unsupported host platform: {system}/{machine}")


def secure_file(path: Path, executable: bool = False) -> None:
    if os.name == "posix":
        mode = stat.S_IRUSR | stat.S_IWUSR
        if executable:
            mode |= stat.S_IXUSR
        path.chmod(mode)


def download(asset: Asset, target: Path, force: bool) -> None:
    if target.is_file() and sha256_file(target).lower() == asset.sha256 and not force:
        print(f"Verified binary already exists: {target}")
        return
    if target.exists():
        target.unlink()
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{target.name}.", suffix=".part", dir=target.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            digest = hashlib.sha256()
            request = Request(f"{DOWNLOAD_ROOT}/{asset.filename}", headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=60) as response:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
                    temporary.write(block)
        if digest.hexdigest().lower() != asset.sha256:
            raise RuntimeError("SHA-256 verification failed; downloaded binary was deleted")
        os.replace(temporary_path, target)
        print(f"Downloaded and SHA-256 verified: {target}")
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Step 1: prepare a verified local Velociraptor binary.")
    parser.add_argument("--install-dir", type=Path, default=root / "backend" / "runtime" / "velociraptor")
    parser.add_argument("--platform", choices=["auto", *ASSETS], default="auto")
    parser.add_argument("--force", action="store_true", help="Download again even if an existing binary verifies.")
    parser.add_argument("--dry-run", action="store_true", help="Show the selected official asset without downloading it.")
    args = parser.parse_args()

    try:
        platform_name = detected_platform() if args.platform == "auto" else args.platform
        asset = ASSETS[platform_name]
    except (KeyError, RuntimeError) as error:
        print(f"ERROR: {error}")
        return 2
    install_dir = args.install_dir.expanduser().resolve()
    target = install_dir / asset.binary_name
    print(f"Selected platform: {platform_name}")
    print(f"Official release: {RELEASE}")
    print(f"Expected SHA-256: {asset.sha256}")
    print(f"Install directory: {install_dir}")
    if args.dry_run:
        print("Dry run complete. No binary was downloaded.")
        return 0

    install_dir.mkdir(parents=True, exist_ok=True)
    try:
        download(asset, target, args.force)
        secure_file(target, executable=True)
    except (OSError, RuntimeError) as error:
        print(f"ERROR: {error}")
        return 1

    installation = {
        "platform": platform_name,
        "version": RELEASE,
        "binary_path": str(target),
        "filename": asset.filename,
        "sha256": asset.sha256,
        "verified": True,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "command_preview": f"{target} config generate --merge_file <approved-merge.json>",
        "config_path": str(install_dir / "server.config.yaml"),
        "server_command_preview": f"{target} --config {install_dir / 'server.config.yaml'} frontend",
        "frontend_port": 8010,
    }
    state_path = install_dir / "installation.json"
    state_path.write_text(json.dumps(installation, indent=2) + "\n", encoding="utf-8")
    secure_file(state_path)
    print(f"Installation state saved: {state_path}")
    print("Next: run scripts/02_signup_credentials.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
