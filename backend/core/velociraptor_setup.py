from __future__ import annotations

import hashlib
import os
import platform as host_platform
import re
try:
    import pty
except ImportError:  # pragma: no cover - Windows does not provide pty
    pty = None
import select
import signal
import stat
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .models import (
    VelociraptorAsset,
    VelociraptorCatalog,
    VelociraptorInstallation,
    VelociraptorPlatform,
)


RELEASE = "0.77.2"
DEFAULT_FRONTEND_PORT = 8010
RELEASES_URL = "https://docs.velociraptor.app/downloads/"
SIGNATURE_KEY = "0572F28B4EF19A043F4CBBE0B22A7FB19CB6CFA1"

# This map is deliberately allowlisted and sourced from the official downloads
# page. Arbitrary URLs, branches, and commands never enter the subprocess path.
ASSET_DATA: dict[VelociraptorPlatform, tuple[str, str]] = {
    VelociraptorPlatform.linux_amd64: ("velociraptor-v0.77.2-linux-amd64", "6c4c23c466d892788ff56ddcd3a31f844e4c0d797ade454c5e2625eb9e427077"),
    VelociraptorPlatform.linux_arm64: ("velociraptor-v0.77.2-linux-arm64", "54d36c23f374a572a4a60106d896e0e39bc6fcafd0d6150cf56aec6c49454ea0"),
    VelociraptorPlatform.linux_amd64_musl: ("velociraptor-v0.77.2-linux-amd64-musl", "f3ffe0ed9942975214c1b7ba7a24b201eaff4ad827575342b43544158b64c524"),
    VelociraptorPlatform.windows_amd64: ("velociraptor-v0.77.2-windows-amd64.exe", "686e4f5888fdd66d07ace3b6c1cbd7d2dd0d8d5fb4d3b5d905a7df3341dfb86f"),
    VelociraptorPlatform.darwin_amd64: ("velociraptor-v0.77.2-darwin-amd64", "900efb29154939e6f594446096975439fc19c59fd74f5433d67bc15cacb4cd99"),
    VelociraptorPlatform.darwin_arm64: ("velociraptor-v0.77.2-darwin-arm64", "3ec2df0c19726b92e27c51ec4b6239aee3e4e40425de39781859eb200987070e"),
}


class WizardSession:
    def __init__(self, session_id: str, process: subprocess.Popen[bytes], config_path: Path, master_fd: int | None = None):
        self.session_id = session_id
        self.process = process
        self.config_path = config_path
        self.master_fd = master_fd
        self.lock = threading.Lock()
        self.output = ""
        self.reader = threading.Thread(target=self._read_output, daemon=True)
        self.reader.start()

    def _append(self, text: str) -> None:
        with self.lock:
            self.output = (self.output + text)[-120_000:]

    def _read_output(self) -> None:
        if self.master_fd is not None:
            while True:
                try:
                    readable, _, _ = select.select([self.master_fd], [], [], 0.25)
                    if not readable:
                        if self.process.poll() is not None:
                            break
                        continue
                    chunk = os.read(self.master_fd, 4096)
                    if not chunk:
                        break
                    self._append(chunk.decode("utf-8", errors="replace"))
                except (OSError, ValueError):
                    break
        elif self.process.stdout is not None:
            for chunk in iter(self.process.stdout.readline, b""):
                self._append(chunk.decode("utf-8", errors="replace"))

    def write(self, value: str) -> None:
        if self.master_fd is not None:
            os.write(self.master_fd, value.encode("utf-8"))
        elif self.process.stdin is not None:
            self.process.stdin.write(value.encode("utf-8"))
            self.process.stdin.flush()

    def snapshot(self) -> str:
        with self.lock:
            return self.output


class VelociraptorSetupService:
    def __init__(self, runtime_dir: Path):
        self.runtime_dir = runtime_dir
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.installation_path = self.runtime_dir / "installation.json"
        self.sessions: dict[str, WizardSession] = {}
        self.server_process: subprocess.Popen[bytes] | None = None
        self.server_command: list[str] | None = None

    @staticmethod
    def detect_host_platform() -> VelociraptorPlatform | None:
        system = host_platform.system().lower()
        machine = host_platform.machine().lower()
        if system == "linux" and machine in {"x86_64", "amd64"}:
            return VelociraptorPlatform.linux_amd64
        if system == "linux" and machine in {"aarch64", "arm64"}:
            return VelociraptorPlatform.linux_arm64
        if system == "darwin" and machine in {"x86_64", "amd64"}:
            return VelociraptorPlatform.darwin_amd64
        if system == "darwin" and machine in {"arm64", "aarch64"}:
            return VelociraptorPlatform.darwin_arm64
        if system == "windows" and machine in {"amd64", "x86_64", "x86-64"}:
            return VelociraptorPlatform.windows_amd64
        return None

    @staticmethod
    def _asset(platform: VelociraptorPlatform) -> VelociraptorAsset:
        try:
            filename, digest = ASSET_DATA[platform]
        except KeyError as exc:
            raise ValueError("Unsupported Velociraptor platform") from exc
        url = f"https://github.com/Velocidex/velociraptor/releases/download/v{RELEASE}/{filename}"
        parsed = urlparse(url)
        if parsed.hostname != "github.com" or not parsed.path.startswith("/Velocidex/velociraptor/releases/download/"):
            raise ValueError("Refusing a non-official Velociraptor download URL")
        return VelociraptorAsset(
            platform=platform,
            version=RELEASE,
            filename=filename,
            download_url=url,
            sha256=digest,
            is_host_platform=platform == VelociraptorSetupService.detect_host_platform(),
        )

    def catalog(self) -> VelociraptorCatalog:
        host = self.detect_host_platform()
        return VelociraptorCatalog(
            release=RELEASE,
            host_platform=host,
            assets=[self._asset(item) for item in ASSET_DATA],
            source_url=RELEASES_URL,
            signature_key=SIGNATURE_KEY,
        )

    @staticmethod
    def _binary_name(asset: VelociraptorAsset) -> str:
        return "velociraptor.exe" if asset.platform == VelociraptorPlatform.windows_amd64 else "velociraptor"

    def prepare(self, platform: VelociraptorPlatform, confirm_download: bool) -> VelociraptorInstallation:
        if not confirm_download:
            raise PermissionError("Explicit download confirmation is required")
        asset = self._asset(platform)
        target = self.runtime_dir / self._binary_name(asset)
        temporary = self.runtime_dir / f".{target.name}.{uuid.uuid4().hex}.part"
        if target.exists() and self._sha256(target) != asset.sha256.lower():
            target.unlink()
        if not target.exists():
            request = Request(asset.download_url, headers={"User-Agent": "Sentroxis-Copilot/0.1"})
            digest = hashlib.sha256()
            try:
                with urlopen(request, timeout=60) as response, temporary.open("wb") as destination:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        destination.write(chunk)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
            if digest.hexdigest().lower() != asset.sha256.lower():
                temporary.unlink(missing_ok=True)
                raise ValueError("SHA-256 verification failed; binary was not installed")
            os.replace(temporary, target)
        if platform != VelociraptorPlatform.windows_amd64:
            target.chmod(target.stat().st_mode | stat.S_IXUSR)
        config_path = self.runtime_dir / "server.config.yaml"
        executable = str(target)
        command_preview = f"{executable} config generate -i"
        server_command_preview = f"{executable} --config {config_path} frontend"
        installation = VelociraptorInstallation(
            platform=platform,
            version=asset.version,
            binary_path=str(target),
            filename=asset.filename,
            sha256=asset.sha256,
            verified=True,
            downloaded_at=datetime.now(timezone.utc),
            command_preview=command_preview,
            config_path=str(config_path),
            server_command_preview=server_command_preview,
        )
        self.installation_path.write_text(installation.model_dump_json(), encoding="utf-8")
        if os.name == "posix":
            self.installation_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return installation

    def load_installation(self) -> VelociraptorInstallation:
        if not self.installation_path.is_file():
            raise FileNotFoundError("Velociraptor has not been prepared")
        return VelociraptorInstallation.model_validate_json(self.installation_path.read_text(encoding="utf-8"))

    @staticmethod
    def _set_frontend_port(config_path: Path, port: int = DEFAULT_FRONTEND_PORT) -> bool:
        """Set Frontend.bind_port and synchronize default client URLs without exposing secrets."""
        content = config_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        in_client = False
        in_server_urls = False
        in_frontend = False
        found_frontend = False
        port_updated = False
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
            raise ValueError("Generated configuration has no Frontend section")
        if not port_updated:
            raise ValueError("Generated Frontend section has no numeric bind_port")
        updated = "".join(lines)
        if updated == content:
            return False
        temporary = config_path.with_suffix(config_path.suffix + ".tmp")
        temporary.write_text(updated, encoding="utf-8")
        os.replace(temporary, config_path)
        return True

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def start_wizard(self, installation: VelociraptorInstallation, confirm_start: bool) -> tuple[str, str]:
        if not confirm_start:
            raise PermissionError("Explicit wizard start confirmation is required")
        if not installation.verified:
            raise ValueError("Only a verified binary may start the config wizard")
        binary = Path(installation.binary_path)
        if not binary.is_file():
            raise FileNotFoundError("Verified Velociraptor binary is missing")
        config_path = Path(installation.config_path)
        command = [str(binary), "config", "generate", "-i"]
        if os.name == "posix" and pty is not None:
            master_fd, slave_fd = pty.openpty()
            process = subprocess.Popen(command, cwd=self.runtime_dir, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, start_new_session=True)
            os.close(slave_fd)
            session = WizardSession(uuid.uuid4().hex, process, config_path, master_fd)
        else:
            process = subprocess.Popen(command, cwd=self.runtime_dir, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            session = WizardSession(uuid.uuid4().hex, process, config_path)
        self.sessions[session.session_id] = session
        return session.session_id, " ".join(command)

    def get_session(self, session_id: str) -> WizardSession:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        if session.process.poll() is not None and session.process.returncode == 0 and session.config_path.is_file():
            self._set_frontend_port(session.config_path)
            if os.name == "posix":
                session.config_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return session

    def send_input(self, session_id: str, value: str) -> WizardSession:
        session = self.get_session(session_id)
        if len(value) > 500:
            raise ValueError("Wizard input is too long")
        if session.process.poll() is not None:
            raise ValueError("Wizard process has already exited")
        session.write(value)
        return session

    def stop_wizard(self, session_id: str) -> None:
        session = self.get_session(session_id)
        if session.process.poll() is None:
            os.killpg(os.getpgid(session.process.pid), signal.SIGTERM) if os.name == "posix" else session.process.terminate()

    def run_server(self, installation: VelociraptorInstallation, confirm_run: bool) -> int:
        if not confirm_run:
            raise PermissionError("Explicit server start confirmation is required")
        binary = Path(installation.binary_path)
        config_path = Path(installation.config_path)
        if not binary.is_file() or not config_path.is_file():
            raise FileNotFoundError("Verified binary and generated config are required")
        if self.server_process and self.server_process.poll() is None:
            return self.server_process.pid
        command = [str(binary), "--config", str(config_path), "frontend"]
        log_path = self.runtime_dir / "velociraptor-server.log"
        log_file = log_path.open("ab")
        self.server_process = subprocess.Popen(command, cwd=self.runtime_dir, stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT, start_new_session=os.name == "posix")
        self.server_command = command
        return self.server_process.pid

    def server_status(self) -> tuple[bool, int | None]:
        running = bool(self.server_process and self.server_process.poll() is None)
        return running, self.server_process.pid if running and self.server_process else None

    def stop_server(self) -> None:
        if self.server_process and self.server_process.poll() is None:
            if os.name == "posix":
                os.killpg(os.getpgid(self.server_process.pid), signal.SIGTERM)
            else:
                self.server_process.terminate()
