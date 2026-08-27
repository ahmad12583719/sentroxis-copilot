import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "Velociraptor"


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


installation_script = load_script("sentroxis_installation_files", "01_installation_files.py")
installer_script = load_script("sentroxis_unified_installer", "install.py")
setup_script = load_script("sentroxis_setup_velociraptor", "03_setup_velociraptor.py")
runner_script = load_script("sentroxis_run_all_setup", "00_run_all_setup.py")


def test_detected_platform_maps_known_linux_host(monkeypatch):
    monkeypatch.setattr(installation_script.host_platform, "system", lambda: "Linux")
    monkeypatch.setattr(installation_script.host_platform, "machine", lambda: "x86_64")

    assert installation_script.detected_platform() == "linux-amd64"
    assert installation_script.ASSETS["linux-amd64"].filename == "velociraptor-v0.77.2-linux-amd64"


def test_detected_platform_rejects_unsupported_host(monkeypatch):
    monkeypatch.setattr(installation_script.host_platform, "system", lambda: "FreeBSD")
    monkeypatch.setattr(installation_script.host_platform, "machine", lambda: "amd64")

    with pytest.raises(RuntimeError, match="Unsupported host platform"):
        installation_script.detected_platform()


def test_unified_installer_uses_project_database_for_web_login(tmp_path, monkeypatch):
    import sqlite3
    from backend.core.auth import configure_auth_db, register_first_user, authenticate

    db_path = tmp_path / "sentroxis.db"
    monkeypatch.setattr(installer_script, "DB_PATH", db_path)
    installer_script.ensure_auth_schema()
    configure_auth_db(str(db_path))
    principal = register_first_user("Test Analyst", "test@example.com", "strong-test-password")

    assert principal.email == "test@example.com"
    assert authenticate("test@example.com", "strong-test-password") is not None
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_setup_step_enforces_fixed_frontend_port_and_valid_login_username():
    assert setup_script.FRONTEND_PORT == 8010
    assert setup_script.USERNAME_PATTERN.fullmatch("analyst@example.com")
    assert not setup_script.USERNAME_PATTERN.fullmatch("invalid username")


def test_master_runner_passes_password_only_through_standard_input(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        from types import SimpleNamespace
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner_script.subprocess, "run", fake_run)
    runner_script.run(["python", "step.py", "--password-stdin"], "strong-test-password")

    assert captured["input"] == "strong-test-password"
    assert captured["text"] is True
    assert "strong-test-password" not in captured["command"]


class _Response:
    def __init__(self, chunks, status=206, content_length=None):
        self.chunks = iter(chunks)
        self.status = status
        self.headers = {"Content-Length": str(content_length if content_length is not None else sum(len(chunk) for chunk in chunks))}

    def getcode(self):
        return self.status

    def read(self, _size):
        return next(self.chunks, b"")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_installation_resumes_partial_download_with_range_request(tmp_path, monkeypatch):
    import hashlib

    target = tmp_path / "velociraptor"
    partial = tmp_path / ".velociraptor.part"
    partial.write_bytes(b"abc")
    asset = installation_script.Asset("fixture", hashlib.sha256(b"abcdef").hexdigest(), "velociraptor")
    captured_headers = {}

    def fake_urlopen(request, timeout):
        captured_headers.update(dict(request.header_items()))
        assert timeout == 60
        return _Response([b"def"], status=206, content_length=3)

    monkeypatch.setattr(installation_script, "urlopen", fake_urlopen)

    installation_script.download(asset, target, force=False)

    assert target.read_bytes() == b"abcdef"
    assert not partial.exists()
    assert captured_headers["Range"] == "bytes=3-"


def test_installation_keeps_partial_file_after_keyboard_interrupt(tmp_path, monkeypatch):
    import hashlib

    target = tmp_path / "velociraptor"
    asset = installation_script.Asset("fixture", hashlib.sha256(b"unused").hexdigest(), "velociraptor")

    class InterruptedResponse(_Response):
        def read(self, _size):
            raise KeyboardInterrupt

    monkeypatch.setattr(installation_script, "urlopen", lambda *_args, **_kwargs: InterruptedResponse([], status=200, content_length=0))

    with pytest.raises(installation_script.DownloadCancelled):
        installation_script.download(asset, target, force=False)

    assert (tmp_path / ".velociraptor.part").exists()
