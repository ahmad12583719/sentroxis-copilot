from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Alert, Severity


@dataclass(frozen=True)
class MitreMatch:
    tactic: str
    technique: str
    name: str
    confidence: float
    reason: str


RULE_MAP: dict[str, MitreMatch] = {
    "100001": MitreMatch("Execution", "T1059", "Command and Scripting Interpreter", 0.94, "Shell execution rule matched"),
    "100002": MitreMatch("Persistence", "T1053.005", "Scheduled Task/Job: Scheduled Task", 0.9, "Scheduled task creation rule matched"),
    "100003": MitreMatch("Credential Access", "T1003", "OS Credential Dumping", 0.92, "Credential access rule matched"),
    "100004": MitreMatch("Defense Evasion", "T1070.004", "File and Directory Discovery", 0.78, "Suspicious file deletion rule matched"),
}

KEYWORD_MAP: tuple[tuple[tuple[str, ...], MitreMatch], ...] = (
    (("powershell", "encodedcommand"), MitreMatch("Execution", "T1059.001", "PowerShell", 0.88, "PowerShell execution indicators found")),
    (("schtasks", "scheduled task"), MitreMatch("Persistence", "T1053.005", "Scheduled Task/Job: Scheduled Task", 0.82, "Scheduled task indicator found")),
    (("lsass", "sekurlsa", "credential dump"), MitreMatch("Credential Access", "T1003", "OS Credential Dumping", 0.84, "Credential dumping indicator found")),
    (("whoami", "ipconfig", "net user"), MitreMatch("Discovery", "T1033", "System Owner/User Discovery", 0.72, "Discovery command indicator found")),
)


def _searchable_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in payload.items():
        if isinstance(value, (str, int, float, bool)):
            parts.extend((str(key), str(value)))
    return " ".join(parts).lower()[:12000]


def correlate(payload: dict[str, Any]) -> MitreMatch:
    rule_id = str(payload.get("rule_id") or payload.get("rule", {}).get("id") or "")
    if rule_id in RULE_MAP:
        return RULE_MAP[rule_id]

    text = _searchable_text(payload)
    for keywords, match in KEYWORD_MAP:
        if any(keyword in text for keyword in keywords):
            return match

    return MitreMatch("Discovery", "T1087", "Account Discovery", 0.42, "Fallback mapping; analyst review required")


def severity_from_payload(payload: dict[str, Any]) -> Severity:
    raw = payload.get("severity") or payload.get("rule", {}).get("level") or payload.get("rule", {}).get("severity") or 3
    try:
        numeric = int(raw)
    except (TypeError, ValueError):
        numeric = 3
    if numeric >= 12:
        return Severity.critical
    if numeric >= 8:
        return Severity.high
    if numeric >= 5:
        return Severity.medium
    return Severity.low


def enrich_alert(alert: Alert) -> Alert:
    match = correlate(alert.raw)
    return alert.model_copy(update={
        "tactic": match.tactic,
        "technique": match.technique,
        "mitre_name": match.name,
    })
