from backend.core.mitre_engine import correlate, severity_from_payload
from backend.core.models import Severity
from backend.ingestion.wazuh_service import WazuhService


def test_wazuh_normalizer_maps_rule_agent_and_mitre():
    alert = WazuhService().normalize_alert({
        "id": "fixture-1",
        "rule": {"id": "100001", "description": "PowerShell execution", "level": 14},
        "agent": {"name": "workstation-1", "ip": "10.0.0.8"},
        "full_log": "powershell.exe -EncodedCommand AAE=",
    })
    assert alert.id == "wazuh-fixture-1"
    assert alert.severity is Severity.critical
    assert alert.technique == "T1059"
    assert alert.tactic == "Execution"
    assert alert.agent_name == "workstation-1"


def test_keyword_correlation_is_bounded_and_deterministic():
    match = correlate({"message": "schtasks /create", "extra": "safe"})
    assert match.technique == "T1053.005"
    assert match.confidence > 0.8


def test_unknown_severity_is_safe_low():
    assert severity_from_payload({"severity": "not-a-number"}) is Severity.low
