from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("sentroxis_installer", ROOT / "install.py")
assert SPEC and SPEC.loader
installer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = installer
SPEC.loader.exec_module(installer)


def test_existing_user_login_verifies_password_and_writes_identity(tmp_path, monkeypatch):
    db_path = tmp_path / "sentroxis.db"
    identity_path = tmp_path / "runtime" / "setup-identity.json"
    monkeypatch.setattr(installer, "DB_PATH", db_path)
    monkeypatch.setattr(installer, "IDENTITY_PATH", identity_path)
    installer.ensure_auth_schema()
    principal = installer.register_local_user("Analyst", "analyst@example.com", "StrongPassword123!456")

    assert installer.authenticate_local_user(principal.email, "wrong-password") is None
    authenticated = installer.authenticate_local_user(principal.email, "StrongPassword123!456")
    assert authenticated is not None
    assert authenticated.subject == principal.subject

    installer.write_identity(authenticated)
    assert identity_path.is_file()
    assert "StrongPassword" not in identity_path.read_text(encoding="utf-8")


def test_new_account_can_be_added_without_deleting_existing_user(tmp_path, monkeypatch):
    db_path = tmp_path / "sentroxis.db"
    monkeypatch.setattr(installer, "DB_PATH", db_path)
    installer.ensure_auth_schema()
    first = installer.register_local_user("First", "first@example.com", "FirstPassword123!456")
    second = installer.register_local_user("Second", "second@example.com", "SecondPassword123!456")

    assert first.email != second.email
    assert installer.authenticate_local_user(first.email, "FirstPassword123!456") is not None
    assert installer.authenticate_local_user(second.email, "SecondPassword123!456") is not None
