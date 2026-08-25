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


ServerKey = Literal["wazuh", "velociraptor"]


class SetupStatus(str, Enum):
    not_started = "not_started"
    ready = "ready"
    in_progress = "in_progress"
    configured = "configured"
    blocked = "blocked"


class WizardStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str
    required: bool = True
    safe_note: str = "No installation command is executed by the web wizard."


class SetupServer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: ServerKey
    name: str
    tagline: str
    description: str
    status: SetupStatus = SetupStatus.not_started
    endpoint: str | None = Field(default=None, max_length=255)
    version: str | None = Field(default=None, max_length=80)
    last_checked: datetime | None = None
    steps: list[WizardStep] = Field(default_factory=list)


class SetupState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str = "Sentroxis Copilot"
    current_step: int = Field(default=1, ge=1, le=10)
    total_steps: int = Field(default=4, ge=1, le=10)
    servers: list[SetupServer]
    updated_at: datetime = Field(default_factory=utc_now)


class SetupStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(min_length=1, max_length=255)
    version: str | None = Field(default=None, max_length=80)
    mode: Literal["readiness_only"] = "readiness_only"


class SetupActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: SetupServer
    message: str
    next_action: str
    audit_id: str


class VelociraptorPlatform(str, Enum):
    linux_amd64 = "linux-amd64"
    linux_arm64 = "linux-arm64"
    linux_amd64_musl = "linux-amd64-musl"
    windows_amd64 = "windows-amd64"
    darwin_amd64 = "darwin-amd64"
    darwin_arm64 = "darwin-arm64"


class VelociraptorAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: VelociraptorPlatform
    version: str
    filename: str
    download_url: str
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    is_host_platform: bool = False


class VelociraptorCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release: str
    host_platform: VelociraptorPlatform | None
    assets: list[VelociraptorAsset]
    source_url: str
    signature_key: str


class VelociraptorPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: VelociraptorPlatform
    confirm_download: bool = False


class VelociraptorInstallation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: VelociraptorPlatform
    version: str
    binary_path: str
    filename: str
    sha256: str
    verified: bool
    downloaded_at: datetime = Field(default_factory=utc_now)
    command_preview: str
    config_path: str
    server_command_preview: str
    frontend_port: int = Field(default=8010, ge=1, le=65535)


class VelociraptorPrepareResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    installation: VelociraptorInstallation
    message: str
    next_action: str
    audit_id: str


class VelociraptorWizardStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: VelociraptorPlatform
    confirm_start: bool = False


class VelociraptorWizardStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    command_preview: str
    output: str
    running: bool
    config_path: str
    frontend_port: int = Field(default=8010, ge=1, le=65535)
    message: str


class VelociraptorWizardInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=12, max_length=80)
    input: str = Field(max_length=500)


class VelociraptorWizardOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    output: str
    running: bool
    exit_code: int | None = None
    config_path: str
    config_ready: bool
    frontend_port: int = Field(default=8010, ge=1, le=65535)


class VelociraptorRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: VelociraptorPlatform
    confirm_run: bool = False


class VelociraptorRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    running: bool
    pid: int | None
    command_preview: str
    config_path: str
    message: str
    audit_id: str
