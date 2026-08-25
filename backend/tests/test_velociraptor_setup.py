from pathlib import Path

import pytest

from backend.core.models import VelociraptorPlatform, VelociraptorInstallation
from backend.core.velociraptor_setup import VelociraptorSetupService


def test_catalog_uses_official_allowlisted_assets(tmp_path):
    service = VelociraptorSetupService(tmp_path / "runtime")
    catalog = service.catalog()
    assert catalog.release == "0.77.2"
    assert catalog.source_url.startswith("https://docs.velociraptor.app/")
    assert all(asset.download_url.startswith("https://github.com/Velocidex/velociraptor/releases/download/") for asset in catalog.assets)
    assert {asset.platform for asset in catalog.assets} >= {VelociraptorPlatform.linux_amd64, VelociraptorPlatform.windows_amd64}


def test_prepare_requires_explicit_download_confirmation(tmp_path):
    service = VelociraptorSetupService(tmp_path / "runtime")
    with pytest.raises(PermissionError, match="confirmation"):
        service.prepare(VelociraptorPlatform.linux_amd64, confirm_download=False)


def test_wizard_and_server_require_explicit_confirmation(tmp_path):
    service = VelociraptorSetupService(tmp_path / "runtime")
    installation = VelociraptorInstallation(
        platform=VelociraptorPlatform.linux_amd64,
        version="0.77.2",
        binary_path=str(tmp_path / "velociraptor"),
        filename="velociraptor-v0.77.2-linux-amd64",
        sha256="0" * 64,
        verified=True,
        command_preview="velociraptor config generate -i",
        config_path=str(tmp_path / "server.config.yaml"),
        server_command_preview="velociraptor --config server.config.yaml frontend",
    )
    with pytest.raises(PermissionError, match="confirmation"):
        service.start_wizard(installation, confirm_start=False)
    with pytest.raises(PermissionError, match="confirmation"):
        service.run_server(installation, confirm_run=False)


def test_host_platform_is_known_for_supported_linux(tmp_path, monkeypatch):
    service = VelociraptorSetupService(tmp_path / "runtime")
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    assert service.detect_host_platform() is VelociraptorPlatform.linux_amd64


def test_finalize_config_sets_only_frontend_port(tmp_path):
    config_path = tmp_path / "server.config.yaml"
    config_path.write_text(
        "Client:\n"
        "  server_urls:\n"
        "    - https://example.test:8000/\n"
        "Frontend:\n"
        "  bind_address: 127.0.0.1\n"
        "  bind_port: 8000\n"
        "GUI:\n"
        "  bind_port: 8889\n",
        encoding="utf-8",
    )

    changed = VelociraptorSetupService._set_frontend_port(config_path)

    assert changed is True
    content = config_path.read_text(encoding="utf-8")
    assert "Frontend:\n  bind_address: 127.0.0.1\n  bind_port: 8010\n" in content
    assert "https://example.test:8010/" in content
    assert "GUI:\n  bind_port: 8889" in content


def test_finalize_config_rejects_missing_frontend_port(tmp_path):
    config_path = tmp_path / "server.config.yaml"
    config_path.write_text("Frontend:\n  bind_address: 127.0.0.1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no numeric bind_port"):
        VelociraptorSetupService._set_frontend_port(config_path)


def test_generate_self_signed_config_creates_server_and_client_files(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    runtime_dir = tmp_path / "runtime"
    service = VelociraptorSetupService(runtime_dir)
    binary = runtime_dir / "velociraptor"
    binary.write_bytes(b"verified-test-binary")
    installation = VelociraptorInstallation(
        platform=VelociraptorPlatform.linux_amd64,
        version="0.77.2",
        binary_path=str(binary),
        filename="velociraptor-v0.77.2-linux-amd64",
        sha256="0" * 64,
        verified=True,
        command_preview="velociraptor config generate -i",
        config_path=str(runtime_dir / "server.config.yaml"),
        server_command_preview="velociraptor --config server.config.yaml frontend",
    )
    captured_merge: dict[str, object] = {}

    def fake_run(command, **kwargs):
        if command[1:3] == ["config", "generate"]:
            captured_merge.update(json.loads(Path(command[-1]).read_text(encoding="utf-8")))
            kwargs["stdout"].write(b"Frontend:\n  bind_port: 8010\n")
        else:
            assert command[1:4] == ["--config", str(runtime_dir / "server.config.yaml"), "config"]
            assert command[4] == "client"
            kwargs["stdout"].write(b"Client:\n  server_urls:\n  - https://192.168.1.20:8010/\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("backend.core.velociraptor_setup.subprocess.run", fake_run)

    result = service.generate_self_signed_config(
        installation,
        server_os="linux",
        datastore_path="/srv/velo-data",
        log_path="/srv/velo-logs",
        certificate_years=10,
        use_registry_writeback=True,
        frontend_hostname="192.168.1.20",
        use_websocket=False,
        gui_port=9443,
        admin_username="analyst@example.com",
        password_confirmation="strong-test-password",
    )

    assert result["frontend_url"] == "https://192.168.1.20:8010/"
    assert result["admin_username"] == "analyst@example.com"
    assert Path(result["config_path"]).is_file()
    assert Path(result["client_config_path"]).is_file()
    assert captured_merge["Frontend"] == {"hostname": "192.168.1.20", "bind_address": "0.0.0.0", "bind_port": 8010}
    assert captured_merge["GUI"]["bind_port"] == 9443
    assert captured_merge["Client"]["server_urls"] == ["https://192.168.1.20:8010/"]
    assert captured_merge["Client"]["writeback_windows"] == "HKLM\\SOFTWARE\\Velocidex\\Velociraptor"
    assert captured_merge["GUI"]["initial_users"][0]["name"] == "analyst@example.com"
    assert captured_merge["GUI"]["initial_users"][0]["password_hash"] != "strong-test-password"


def test_generate_self_signed_config_rejects_existing_config(tmp_path):
    runtime_dir = tmp_path / "runtime"
    service = VelociraptorSetupService(runtime_dir)
    binary = runtime_dir / "velociraptor"
    binary.write_bytes(b"verified-test-binary")
    config_path = runtime_dir / "server.config.yaml"
    config_path.write_text("existing", encoding="utf-8")
    installation = VelociraptorInstallation(
        platform=VelociraptorPlatform.linux_amd64,
        version="0.77.2",
        binary_path=str(binary),
        filename="velociraptor-v0.77.2-linux-amd64",
        sha256="0" * 64,
        verified=True,
        command_preview="velociraptor config generate -i",
        config_path=str(config_path),
        server_command_preview="velociraptor --config server.config.yaml frontend",
    )

    with pytest.raises(FileExistsError, match="already exists"):
        service.generate_self_signed_config(
            installation,
            server_os="linux",
            datastore_path="/srv/velo-data",
            log_path=None,
            certificate_years=1,
            use_registry_writeback=False,
            frontend_hostname="velo.example.com",
            use_websocket=False,
            gui_port=8889,
            admin_username="analyst@example.com",
            password_confirmation="strong-test-password",
        )
