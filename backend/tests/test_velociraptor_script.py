import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "setup_velociraptor.py"
SPEC = importlib.util.spec_from_file_location("sentroxis_velociraptor_script", SCRIPT_PATH)
assert SPEC and SPEC.loader
setup_script = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = setup_script
SPEC.loader.exec_module(setup_script)


def test_detect_asset_maps_known_linux_platform(monkeypatch):
    monkeypatch.setattr(setup_script.platform, "system", lambda: "Linux")
    monkeypatch.setattr(setup_script.platform, "machine", lambda: "x86_64")

    asset = setup_script.detect_asset()

    assert asset.filename == "velociraptor-v0.77.2-linux-amd64"
    assert asset.executable_name == "velociraptor"


def test_detect_asset_rejects_unsupported_platform(monkeypatch):
    monkeypatch.setattr(setup_script.platform, "system", lambda: "FreeBSD")
    monkeypatch.setattr(setup_script.platform, "machine", lambda: "amd64")

    with pytest.raises(RuntimeError, match="Unsupported host platform"):
        setup_script.detect_asset()


def test_replace_frontend_port_changes_only_frontend_section(tmp_path):
    config = tmp_path / "server.config.yaml"
    config.write_text(
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

    changed = setup_script.replace_frontend_port(config, 8010)

    assert changed is True
    content = config.read_text(encoding="utf-8")
    assert "Frontend:\n  bind_address: 127.0.0.1\n  bind_port: 8010\n" in content
    assert "https://example.test:8010/" in content
    assert "GUI:\n  bind_port: 8889" in content


def test_replace_frontend_port_rejects_missing_frontend_port(tmp_path):
    config = tmp_path / "server.config.yaml"
    config.write_text("Frontend:\n  bind_address: 127.0.0.1\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="no numeric bind_port"):
        setup_script.replace_frontend_port(config, 8010)


def test_dry_run_uses_default_frontend_port(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(setup_script.platform, "system", lambda: "Linux")
    monkeypatch.setattr(setup_script.platform, "machine", lambda: "x86_64")

    result = setup_script.main(["--dry-run", "--install-dir", str(tmp_path)])

    output = capsys.readouterr().out
    assert result == 0
    assert "Frontend port policy: 8010" in output
    assert "No file was downloaded" in output
