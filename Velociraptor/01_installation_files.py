#!/usr/bin/env python3
"""Step 1 of 2: download and verify the local Velociraptor binary.

Only the pinned official Velocidex release assets in ASSETS are accepted. The
script does not install operating-system packages, create services, alter firewall
rules, or start a server. Interrupted downloads are retained as an owner-only
partial file and safely resumed only when the server confirms HTTP range support.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform as host_platform
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

RELEASE = "0.77.2"
DOWNLOAD_ROOT = f"https://github.com/Velocidex/velociraptor/releases/download/v{RELEASE}"
USER_AGENT = "Sentroxis-Copilot/0.1"
CHUNK_SIZE = 1024 * 1024
PROGRESS_INTERVAL = 5 * 1024 * 1024


class DownloadCancelled(RuntimeError):
    """Raised after preserving an interrupted partial download for a later resume."""


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
        for block in iter(lambda: source.read(CHUNK_SIZE), b""):
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


def progress_label(downloaded: int, total: int | None) -> str:
    downloaded_mib = downloaded / (1024 * 1024)
    if total:
        return f"{downloaded_mib:.1f} MiB / {total / (1024 * 1024):.1f} MiB"
    return f"{downloaded_mib:.1f} MiB"


def download(asset: Asset, target: Path, force: bool) -> None:
    if target.is_file() and sha256_file(target).lower() == asset.sha256 and not force:
        print(f"Verified binary already exists: {target}")
        return

    partial_path = target.with_name(f".{target.name}.part")
    if force:
        target.unlink(missing_ok=True)
        partial_path.unlink(missing_ok=True)
    elif target.exists():
        # A complete but unverified file must never be treated as a partial resume.
        target.unlink()

    downloaded = partial_path.stat().st_size if partial_path.is_file() else 0
    digest = hashlib.sha256()
    if downloaded:
        print(f"Resuming interrupted download from {progress_label(downloaded, None)}: {partial_path}")
        with partial_path.open("rb") as existing:
            for block in iter(lambda: existing.read(CHUNK_SIZE), b""):
                digest.update(block)

    request = Request(f"{DOWNLOAD_ROOT}/{asset.filename}", headers={"User-Agent": USER_AGENT})
    if downloaded:
        request.add_header("Range", f"bytes={downloaded}-")

    try:
        with urlopen(request, timeout=60) as response:
            status = response.getcode()
            if downloaded and status != 206:
                # Never append a complete response to a partial file; restart safely.
                print("Remote server did not confirm resume support; restarting the download safely.")
                partial_path.unlink(missing_ok=True)
                return download(asset, target, force=False)
            content_length = response.headers.get("Content-Length")
            total = downloaded + int(content_length) if content_length and content_length.isdigit() else None
            mode = "ab" if downloaded else "wb"
            next_update = downloaded + PROGRESS_INTERVAL
            print(f"Downloading {asset.filename} ({progress_label(downloaded, total)}). Press Ctrl+C to cancel safely.")
            with partial_path.open(mode) as temporary:
                secure_file(partial_path)
                while True:
                    block = response.read(CHUNK_SIZE)
                    if not block:
                        break
                    digest.update(block)
                    temporary.write(block)
                    downloaded += len(block)
                    if downloaded >= next_update:
                        print(f"Download progress: {progress_label(downloaded, total)}")
                        next_update = downloaded + PROGRESS_INTERVAL
    except KeyboardInterrupt as error:
        print(f"\nDownload cancelled. Partial file retained for resume: {partial_path} ({progress_label(downloaded, None)} saved)")
        raise DownloadCancelled("Download cancelled by user") from error

    if digest.hexdigest().lower() != asset.sha256:
        partial_path.unlink(missing_ok=True)
        raise RuntimeError("SHA-256 verification failed; partial download was deleted")
    os.replace(partial_path, target)
    secure_file(target, executable=True)
    print(f"Downloaded and SHA-256 verified: {target}")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Step 1: prepare a verified local Velociraptor binary.")
    parser.add_argument("--install-dir", type=Path, default=root / "backend" / "runtime" / "velociraptor")
    parser.add_argument("--platform", choices=["auto", *ASSETS], default="auto")
    parser.add_argument("--force", action="store_true", help="Discard any unverified partial file and download again.")
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
    except DownloadCancelled:
        return 130
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
    print("Next: run ./install.py or Velociraptor/00_run_all_setup.py with a Task 01 identity")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nSetup cancelled. No verified installation state was created.")
        raise SystemExit(130)
