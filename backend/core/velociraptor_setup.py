from __future__ import annotations

import hashlib
import json
import os
import platform as host_platform
import re
import secrets
import tempfile
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
import zipfile
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
        self.server_pid_path = self.runtime_dir / "velociraptor-server.pid"

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
        server_command_preview = f"{executable} --config {config_path} frontend -v"
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

    def _download_verified_asset(self, asset: VelociraptorAsset, target: Path) -> Path:
        """Download an allowlisted release asset into a private runtime cache."""
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and self._sha256(target).lower() == asset.sha256.lower():
            return target
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
        digest = hashlib.sha256()
        try:
            request = Request(asset.download_url, headers={"User-Agent": "Sentroxis-Copilot/0.1"})
            with urlopen(request, timeout=90) as response, temporary.open("wb") as destination:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    destination.write(chunk)
            if digest.hexdigest().lower() != asset.sha256.lower():
                raise ValueError(f"SHA-256 verification failed for {asset.filename}")
            os.replace(temporary, target)
            if asset.platform != VelociraptorPlatform.windows_amd64:
                target.chmod(target.stat().st_mode | stat.S_IXUSR)
            return target
        finally:
            temporary.unlink(missing_ok=True)

    def build_endpoint_bundle(self, platform: VelociraptorPlatform, installation: VelociraptorInstallation | None = None) -> dict[str, Any]:
        """Build a password-free endpoint ZIP from verified/generated artifacts."""
        if platform not in {VelociraptorPlatform.linux_amd64, VelociraptorPlatform.windows_amd64}:
            raise ValueError("Endpoint bundles are currently available for Linux amd64 and Windows amd64")
        installation = installation or self.load_installation()
        config_path = self.runtime_dir / "server.config.yaml"
        client_config_path = self.runtime_dir / "client.config.yaml"
        api_config_path = self.runtime_dir / "api.config.yaml"
        for required in (config_path, client_config_path, api_config_path):
            if not required.is_file():
                raise FileNotFoundError("Generate server, client, and API configurations before building endpoint bundles")

        asset = self._asset(platform)
        cache_path = self.runtime_dir / "bundle-cache" / asset.filename
        binary_path = self._download_verified_asset(asset, cache_path)
        bundle_dir = self.runtime_dir / "bundles"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        bundle_name = f"sentroxis-velociraptor-{platform.value}-v{installation.version}.zip"
        archive_path = bundle_dir / bundle_name
        with tempfile.TemporaryDirectory(prefix=f"bundle-{platform.value}-", dir=bundle_dir) as staging:
            root = Path(staging)
            shutil_binary = root / ("velociraptor.exe" if platform == VelociraptorPlatform.windows_amd64 else "velociraptor")
            shutil_binary.write_bytes(binary_path.read_bytes())
            if platform == VelociraptorPlatform.linux_amd64:
                shutil_binary.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            (root / "client.config.yaml").write_bytes(client_config_path.read_bytes())
            (root / "api.config.yaml").write_bytes(api_config_path.read_bytes())
            msi_mode: str | None = None
            if platform == VelociraptorPlatform.windows_amd64:
                msi_asset = f"velociraptor-v{installation.version}-windows-amd64.msi"
                msi_url = f"https://github.com/Velocidex/velociraptor/releases/download/v{installation.version}/{msi_asset}"
                official_msi = root / "velociraptor-official.msi"
                try:
                    with urlopen(Request(msi_url, headers={"User-Agent": "Sentroxis-Copilot/0.1"}), timeout=90) as response, official_msi.open("wb") as destination:
                        while True:
                            chunk = response.read(1024 * 1024)
                            if not chunk:
                                break
                            destination.write(chunk)
                    repacked = root / "velociraptor-windows.msi"
                    repack = subprocess.run(
                        [str(installation.binary_path), "config", "repack", "--msi", str(official_msi), str(client_config_path), str(repacked)],
                        cwd=self.runtime_dir, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                        timeout=120, check=False,
                    )
                    if repack.returncode == 0 and repacked.is_file() and repacked.stat().st_size:
                        official_msi.unlink(missing_ok=True)
                        msi_mode = "repacked"
                    else:
                        official_msi.rename(root / "velociraptor-windows-official.msi")
                        msi_mode = "official"
                except (OSError, subprocess.TimeoutExpired):
                    official_msi.unlink(missing_ok=True)
            readme = root / "README.md"
            readme.write_text(self._bundle_readme(platform, installation.version, msi_mode), encoding="utf-8")
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for item in sorted(root.iterdir()):
                    archive.write(item, item.name)
        if os.name == "posix":
            archive_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return {"platform": platform.value, "version": installation.version, "filename": bundle_name, "path": str(archive_path), "download_url": f"/api/velociraptor/endpoints/bundle/download/{platform.value}", "includes_msi": msi_mode is not None, "msi_mode": msi_mode}

    def list_endpoint_bundles(self) -> list[dict[str, Any]]:
        """List saved bundles using metadata derived from their filenames."""
        try:
            version = self.load_installation().version
        except FileNotFoundError:
            return []
        bundle_dir = self.runtime_dir / "bundles"
        result: list[dict[str, Any]] = []
        for platform in (VelociraptorPlatform.linux_amd64, VelociraptorPlatform.windows_amd64):
            filename = f"sentroxis-velociraptor-{platform.value}-v{version}.zip"
            path = bundle_dir / filename
            if path.is_file():
                result.append({
                    "platform": platform.value,
                    "version": version,
                    "filename": filename,
                    "download_url": f"/api/velociraptor/endpoints/bundle/download/{platform.value}",
                    "includes_msi": platform == VelociraptorPlatform.windows_amd64,
                    "msi_mode": None,
                })
        return result

    @staticmethod
    def _bundle_readme(platform: VelociraptorPlatform, version: str, msi_mode: str | None) -> str:
        if platform == VelociraptorPlatform.windows_amd64:
            install = ("Run PowerShell as Administrator and execute: `msiexec /i .\\velociraptor-windows.msi /qn`" if msi_mode == "repacked" else "The official MSI is included as `velociraptor-windows-official.msi`, but it has a placeholder configuration. Copy `client.config.yaml` beside the installed executable before starting the service. For a configured install, use the included executable and config directly.")
            run = "`& 'C:\\Program Files\\Velociraptor\\velociraptor.exe' --config 'C:\\Program Files\\Velociraptor\\client.config.yaml' client -v`"
        else:
            install = "Make the binary executable: `chmod 700 ./velociraptor`"
            run = "`sudo ./velociraptor --config ./client.config.yaml client -v`"
        return f"""# Sentroxis Velociraptor endpoint bundle\n\nVersion: {version}\n\nThis package contains the official, SHA-256-verified Velociraptor client binary, the generated client configuration, the local API configuration, and the Windows installer when available. The API configuration contains private key material; keep this archive restricted and never commit it to source control.\n\n## Install\n\n{install}\n\n## Run interactively\n\n{run}\n\nThe client connects to the server URL embedded in `client.config.yaml`. The first connection enrolls the endpoint. Use an approved service-management workflow for persistent deployment, and remove this README/package from shared locations after installation.\n"""

    def load_installation(self) -> VelociraptorInstallation:
        if not self.installation_path.is_file():
            raise FileNotFoundError("Velociraptor has not been prepared")
        return VelociraptorInstallation.model_validate_json(self.installation_path.read_text(encoding="utf-8"))

    def generate_self_signed_config(
        self,
        installation: VelociraptorInstallation,
        *,
        server_os: str,
        datastore_path: str,
        log_path: str | None,
        certificate_years: int,
        use_registry_writeback: bool,
        frontend_hostname: str,
        use_websocket: bool,
        gui_port: int,
        admin_username: str,
        password_confirmation: str,
    ) -> dict[str, str]:
        """Create a bounded self-signed configuration and its client subset.

        The official binary generates all deployment keys. This service only supplies
        user-approved values, including the fixed frontend listener on 8010. The
        Sentroxis password is converted to the official salted hash representation
        before the temporary merge file is written; plaintext is never persisted.
        """
        if not installation.verified:
            raise ValueError("Only a verified binary may generate configuration")
        binary = Path(installation.binary_path)
        if not binary.is_file():
            raise FileNotFoundError("Verified Velociraptor binary is missing")
        if server_os not in {"linux", "windows", "darwin"}:
            raise ValueError("Unsupported server operating system")
        if certificate_years not in {1, 2, 10}:
            raise ValueError("Certificate validity must be 1, 2, or 10 years")
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", frontend_hostname):
            raise ValueError("Frontend hostname must be an IP address or DNS name")
        if not re.fullmatch(r"[A-Za-z0-9@.\\-_#+]{1,120}", admin_username):
            raise ValueError("The signed-in email cannot be used as a Velociraptor username")
        if not 1 <= gui_port <= 65535:
            raise ValueError("GUI port must be between 1 and 65535")

        config_path = Path(installation.config_path)
        client_config_path = self.runtime_dir / "client.config.yaml"
        api_config_path = self.runtime_dir / "api.config.yaml"
        if config_path.exists() or client_config_path.exists() or api_config_path.exists():
            raise FileExistsError("A server, client, or API configuration already exists; back it up or remove it before generating a new one")

        normalized_datastore = str(Path(datastore_path).expanduser())
        normalized_logs = str(Path(log_path).expanduser()) if log_path else str(Path(normalized_datastore) / "logs")
        try:
            Path(normalized_datastore).mkdir(parents=True, exist_ok=True)
            Path(normalized_logs).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(
                "Datastore or logging directory cannot be created. Choose a user-writable path, "
                "such as a directory under your home folder."
            ) from exc
        protocol = "wss" if use_websocket else "https"
        frontend_url = f"{protocol}://{frontend_hostname}:{DEFAULT_FRONTEND_PORT}/"
        salt = secrets.token_bytes(32)
        password_hash = hashlib.sha256(salt + password_confirmation.encode("utf-8")).hexdigest()
        merge_payload: dict[str, Any] = {
            "Datastore": {
                "implementation": "FileBaseDataStore",
                "location": normalized_datastore,
                "filestore_directory": normalized_datastore,
            },
            "Logging": {"output_directory": normalized_logs, "separate_logs_per_component": True},
            "Security": {"certificate_validity_days": certificate_years * 365},
            "Frontend": {
                "hostname": frontend_hostname,
                "bind_address": "0.0.0.0",
                "bind_port": DEFAULT_FRONTEND_PORT,
            },
            "GUI": {
                "bind_address": "127.0.0.1",
                "bind_port": gui_port,
                "base_path": "/velociraptor-console",
                "public_url": "https://127.0.0.1:5173/velociraptor-console/app/index.html",
                "authenticator": {"type": "Basic"},
                "initial_users": [{
                    "name": admin_username,
                    "password_hash": password_hash,
                    "password_salt": salt.hex(),
                }],
            },
            "Client": {
                "server_urls": [frontend_url],
                "use_self_signed_ssl": True,
            },
        }
        if use_registry_writeback:
            merge_payload["Client"]["writeback_windows"] = "HKLM\\SOFTWARE\\Velocidex\\Velociraptor"

        merge_path: Path | None = None
        config_temp: Path | None = None
        client_temp: Path | None = None
        api_temp: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.runtime_dir, prefix=".config-merge.", suffix=".json", delete=False) as merge_file:
                merge_path = Path(merge_file.name)
                json.dump(merge_payload, merge_file)
            if os.name == "posix":
                merge_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

            with tempfile.NamedTemporaryFile(mode="wb", dir=self.runtime_dir, prefix=".server.", suffix=".yaml", delete=False) as output_file:
                config_temp = Path(output_file.name)
                generated = subprocess.run(
                    [str(binary), "config", "generate", "--merge_file", str(merge_path)],
                    cwd=self.runtime_dir,
                    stdin=subprocess.DEVNULL,
                    stdout=output_file,
                    stderr=subprocess.PIPE,
                    timeout=90,
                    check=False,
                )
            if generated.returncode != 0:
                raise RuntimeError("Velociraptor server configuration generation failed")
            os.replace(config_temp, config_path)
            config_temp = None
            if os.name == "posix":
                config_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

            with tempfile.NamedTemporaryFile(mode="wb", dir=self.runtime_dir, prefix=".client.", suffix=".yaml", delete=False) as output_file:
                client_temp = Path(output_file.name)
                client_generated = subprocess.run(
                    [str(binary), "--config", str(config_path), "config", "client"],
                    cwd=self.runtime_dir,
                    stdin=subprocess.DEVNULL,
                    stdout=output_file,
                    stderr=subprocess.PIPE,
                    timeout=90,
                    check=False,
                )
            if client_generated.returncode != 0:
                raise RuntimeError("Velociraptor client configuration generation failed")
            os.replace(client_temp, client_config_path)
            client_temp = None
            if os.name == "posix":
                client_config_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

            # The API config includes a client certificate and private key. Use the
            # fixed local API identity and its minimal API role; never print it.
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.runtime_dir, prefix=".api-client.", suffix=".yaml", delete=False) as output_file:
                api_temp = Path(output_file.name)
            api_generated = subprocess.run(
                [
                    str(binary), "--config", str(config_path), "config", "api_client",
                    "--name", "sentroxis-copilot-api", "--role", "api", str(api_temp),
                ],
                cwd=self.runtime_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
            )
            if api_generated.returncode != 0 or not api_temp.is_file() or not api_temp.stat().st_size:
                raise RuntimeError("Velociraptor API client configuration generation failed")
            os.replace(api_temp, api_config_path)
            api_temp = None
            if os.name == "posix":
                api_config_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            endpoint_bundles = [
                self.build_endpoint_bundle(target, installation=installation)
                for target in (VelociraptorPlatform.linux_amd64, VelociraptorPlatform.windows_amd64)
            ]
            return {
                "config_path": str(config_path),
                "client_config_path": str(client_config_path),
                "api_config_path": str(api_config_path),
                "frontend_url": frontend_url,
                "admin_username": admin_username,
                "endpoint_bundles": endpoint_bundles,
            }
        finally:
            # The merge payload contains password-derived material; remove it after use.
            if merge_path:
                merge_path.unlink(missing_ok=True)
            if config_temp:
                config_temp.unlink(missing_ok=True)
            if client_temp:
                client_temp.unlink(missing_ok=True)
            if api_temp:
                api_temp.unlink(missing_ok=True)

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

    @staticmethod
    def _read_config_value(config_path: Path, section: str, key: str) -> str | None:
        """Read a simple scalar in a generated YAML section without loading secrets."""
        in_section = False
        section_heading = re.compile(rf"^{re.escape(section)}:\s*(?:#.*)?$")
        heading = re.compile(r"^[A-Za-z][A-Za-z0-9_]*:\s*(?:#.*)?$")
        value_line = re.compile(rf"^\s+{re.escape(key)}\s*:\s*(.+?)\s*(?:#.*)?$")
        try:
            lines = config_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        for line in lines:
            if section_heading.match(line):
                in_section = True
                continue
            if in_section and heading.match(line):
                break
            if in_section:
                match = value_line.match(line)
                if match:
                    return match.group(1).strip().strip("'\"")
        return None

    def server_details(self, installation: VelociraptorInstallation) -> dict[str, Any]:
        """Return safe process and GUI metadata for the authenticated dashboard."""
        config_path = Path(installation.config_path)
        running, pid = self.server_status()
        gui_port_text = self._read_config_value(config_path, "GUI", "bind_port")
        try:
            gui_port = int(gui_port_text) if gui_port_text else None
        except ValueError:
            gui_port = None
        # The dashboard embeds only the local GUI listener. The server configuration
        # may carry a deployment-facing public_url, which must not redirect this UI.
        gui_url = f"https://127.0.0.1:{gui_port}/app/index.html" if gui_port else None
        log_path = self.runtime_dir / "velociraptor-server.log"
        api_config_path = self.runtime_dir / "api.config.yaml"
        command = self.server_command or [str(Path(installation.binary_path)), "--config", str(config_path), "frontend", "-v"]
        return {
            "configured": config_path.is_file(),
            "running": running,
            "pid": pid,
            "platform": installation.platform,
            "command_preview": " ".join(command),
            "config_path": str(config_path),
            "frontend_port": DEFAULT_FRONTEND_PORT,
            "gui_port": gui_port,
            "gui_url": gui_url,
            "gui_proxy_url": "/velociraptor-console/app/index.html" if gui_port else None,
            "log_path": str(log_path),
            "api_config_path": str(api_config_path) if api_config_path.is_file() else None,
            "api_config_ready": api_config_path.is_file(),
        }

    def _ensure_logging_directory(self, config_path: Path) -> None:
        logging_directory = self._read_config_value(config_path, "Logging", "output_directory")
        if not logging_directory:
            return
        try:
            Path(logging_directory).expanduser().mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OSError(
                f"Velociraptor logging directory cannot be created: {logging_directory}. "
                "Choose a user-writable datastore/log path and regenerate server.config.yaml."
            ) from exc

    def _stored_server_pid(self) -> int | None:
        try:
            pid = int(self.server_pid_path.read_text(encoding="utf-8").strip())
            return pid if pid > 1 else None
        except (OSError, ValueError):
            return None

    def _is_current_server_pid(self, pid: int, config_path: Path) -> bool:
        """Confirm a persisted PID still belongs to this local Velociraptor config."""
        if os.name != "posix":
            return False
        proc_cmdline = Path(f"/proc/{pid}/cmdline")
        try:
            command = proc_cmdline.read_bytes().decode("utf-8", errors="replace")
            return "velociraptor" in command and str(config_path) in command and "frontend" in command
        except OSError:
            return False

    def run_server(self, installation: VelociraptorInstallation, confirm_run: bool) -> int:
        if not confirm_run:
            raise PermissionError("Explicit server start confirmation is required")
        binary = Path(installation.binary_path)
        config_path = Path(installation.config_path)
        if not binary.is_file() or not config_path.is_file():
            raise FileNotFoundError("Verified binary and generated config are required")
        running, existing_pid = self.server_status()
        if running and existing_pid:
            return existing_pid
        self._ensure_logging_directory(config_path)
        command = [str(binary), "--config", str(config_path), "frontend", "-v"]
        log_path = self.runtime_dir / "velociraptor-server.log"
        log_file = log_path.open("ab")
        self.server_process = subprocess.Popen(command, cwd=self.runtime_dir, stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT, start_new_session=os.name == "posix")
        self.server_command = command
        self.server_pid_path.write_text(f"{self.server_process.pid}\n", encoding="utf-8")
        if os.name == "posix":
            self.server_pid_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return self.server_process.pid

    def server_status(self) -> tuple[bool, int | None]:
        if self.server_process and self.server_process.poll() is None:
            return True, self.server_process.pid
        stored_pid = self._stored_server_pid()
        if stored_pid:
            try:
                installation = self.load_installation()
                if self._is_current_server_pid(stored_pid, Path(installation.config_path)):
                    return True, stored_pid
            except FileNotFoundError:
                pass
        self.server_pid_path.unlink(missing_ok=True)
        return False, None

    def stop_server(self) -> None:
        running, pid = self.server_status()
        if running and pid:
            if os.name == "posix":
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            elif self.server_process and self.server_process.poll() is None:
                self.server_process.terminate()
        self.server_process = None
        self.server_pid_path.unlink(missing_ok=True)
