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
