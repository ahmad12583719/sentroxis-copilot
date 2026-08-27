import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


installation_script = load_script("sentroxis_installation_files", "01_installation_files.py")
signup_script = load_script("sentroxis_signup_credentials", "02_signup_credentials.py")
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


def test_signup_password_hash_is_verifiable_and_not_plaintext():
    stored = signup_script.password_hash("strong-test-password")

    assert stored.startswith("pbkdf2_sha256$")
    assert "strong-test-password" not in stored
    assert signup_script.password_matches("strong-test-password", stored) is True
    assert signup_script.password_matches("wrong-password", stored) is False


def test_setup_step_enforces_fixed_frontend_port_and_valid_login_username():
    assert setup_script.FRONTEND_PORT == 8010
    assert setup_script.USERNAME_PATTERN.fullmatch("analyst@example.com")
    assert not setup_script.USERNAME_PATTERN.fullmatch("invalid username")


def test_master_runner_passes_password_only_through_standard_input(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)

    monkeypatch.setattr(runner_script.subprocess, "run", fake_run)
    runner_script.run(["python", "step.py", "--password-stdin"], "strong-test-password")

    assert captured["input"] == "strong-test-password\n"
    assert captured["text"] is True
    assert "strong-test-password" not in captured["command"]


def test_signup_rejects_short_password_before_creating_database(tmp_path, monkeypatch):
    db_path = tmp_path / "sentroxis.db"
    handoff_path = tmp_path / "identity.json"
    monkeypatch.setattr(signup_script.sys, "argv", [
        "02_signup_credentials.py",
        "--db-path", str(db_path),
        "--handoff-path", str(handoff_path),
        "--name", "Test Analyst",
        "--email", "test@example.com",
    ])
    monkeypatch.setattr(signup_script.getpass, "getpass", lambda _: "too-short")

    assert signup_script.main() == 2
    assert not db_path.exists()
    assert not handoff_path.exists()


def test_signup_discovers_existing_account_for_safe_reuse(tmp_path):
    db_path = tmp_path / "sentroxis.db"
    import sqlite3

    with sqlite3.connect(db_path) as db:
        signup_script.ensure_users_table(db)
        db.execute(
            "INSERT INTO users (id, name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("usr-test", "Test Analyst", "test@example.com", signup_script.password_hash("strong-test-password"), "admin", "2026-01-01T00:00:00+00:00"),
        )

    account = signup_script.existing_account(db_path)

    assert account is not None
    assert account[1:3] == ("Test Analyst", "test@example.com")


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
