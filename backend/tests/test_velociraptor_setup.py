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
