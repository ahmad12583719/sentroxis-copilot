from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Source(str, Enum):
    wazuh = "wazuh"
    velociraptor = "velociraptor"
    demo = "demo"


class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class AlertStatus(str, Enum):
    new = "new"
    triaged = "triaged"
    investigating = "investigating"
    resolved = "resolved"


class TimelineEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1, max_length=2000)
    source: Source
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class Alert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=120)
    source: Source
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)
    severity: Severity
    status: AlertStatus = AlertStatus.new
    rule_id: str = Field(default="unknown", max_length=80)
    agent_name: str = Field(default="unknown", max_length=120)
    agent_ip: str | None = Field(default=None, max_length=64)
    tactic: str = Field(default="Discovery", max_length=80)
    technique: str = Field(default="T1059", max_length=80)
    mitre_name: str = Field(default="Command and Scripting Interpreter", max_length=160)
    timestamp: datetime = Field(default_factory=utc_now)
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("raw")
    @classmethod
    def raw_is_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 50:
            raise ValueError("raw alert data is too large")
        return value


class AlertIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["wazuh", "velociraptor", "demo"]
    payload: dict[str, Any]

    @field_validator("payload")
    @classmethod
    def payload_is_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 100:
            raise ValueError("payload contains too many fields")
        return value


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    alert_id: str
    source: Source
    collected_at: datetime = Field(default_factory=utc_now)
    collection_method: str = Field(min_length=1, max_length=160)
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    content_preview: str = Field(default="", max_length=2000)
    provenance: str = Field(default="demo-fixture", max_length=240)


class Investigation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    alert_id: str
    state: Literal["open", "in_review", "closed"] = "open"
    owner: str = "SOC analyst"
    created_at: datetime = Field(default_factory=utc_now)
    hypothesis: str
    timeline: list[TimelineEvent] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class AIAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alert_id: str
    summary: str
    confidence: float = Field(ge=0, le=1)
    recommended_next_step: str
    evidence_refs: list[str] = Field(default_factory=list)
    is_actionable: bool = False
    safety_note: str = "AI output is advisory and cannot execute response actions."


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    alert_id: str | None = Field(default=None, max_length=120)


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    citations: list[str] = Field(default_factory=list)
    safety_note: str = "Telemetry is untrusted data; recommendations require analyst approval."


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    actor: str
    action: str
    target: str
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, str] = Field(default_factory=dict)
