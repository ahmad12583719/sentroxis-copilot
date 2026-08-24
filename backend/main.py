from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.core.auth import Principal, get_principal, require_role
from backend.core.llm_agent import agent
from backend.core.setup_service import default_state, start_readiness
from backend.core.models import (
    AIAnalysis,
    Alert,
    AlertIngestRequest,
    AlertStatus,
    AuditEvent,
    ChatRequest,
    ChatResponse,
    Evidence,
    Investigation,
    ServerKey,
    SetupActionResponse,
    SetupStartRequest,
    SetupState,
    Source,
    TimelineEvent,
)
from backend.ingestion.velociraptor_service import VelociraptorService
from backend.ingestion.wazuh_service import WazuhService


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("SENTROXIS_DB_PATH", str(BASE_DIR / "sentroxis.db")))


class StatusResponse(BaseModel):
    service: str
    status: str
    mode: str
    timestamp: datetime


class AlertListResponse(BaseModel):
    items: list[Alert]
    total: int


class InvestigationCreate(BaseModel):
    alert_id: str = Field(min_length=1, max_length=120)
    hypothesis: str = Field(min_length=1, max_length=1000)


class ActionProposal(BaseModel):
    alert_id: str = Field(min_length=1, max_length=120)
    action: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=1000)
    requires_approval: bool = True


wazuh = WazuhService()
velociraptor = VelociraptorService()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db() -> None:
    with connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS investigations (
                id TEXT PRIMARY KEY,
                alert_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(alert_id) REFERENCES alerts(id)
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                metadata TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS setup_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )


def load_setup_state() -> SetupState:
    with connection() as db:
        row = db.execute("SELECT payload FROM setup_state WHERE id = 1").fetchone()
        if row:
            return SetupState.model_validate_json(row["payload"])
        state = default_state()
        db.execute(
            "INSERT INTO setup_state (id, payload, updated_at) VALUES (1, ?, ?)",
            (state.model_dump_json(), state.updated_at.isoformat()),
        )
        return state


def save_setup_state(state: SetupState) -> None:
    with connection() as db:
        db.execute(
            "INSERT OR REPLACE INTO setup_state (id, payload, updated_at) VALUES (1, ?, ?)",
            (state.model_dump_json(), state.updated_at.isoformat()),
        )


def save_audit(principal: Principal, action: str, target: str, metadata: dict[str, str] | None = None) -> AuditEvent:
    event = AuditEvent(
        id=f"audit-{uuid.uuid4().hex[:12]}",
        actor=principal.subject,
        action=action,
        target=target,
        metadata=metadata or {},
    )
    with connection() as db:
        db.execute(
            "INSERT INTO audit_events (id, actor, action, target, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (event.id, event.actor, event.action, event.target, json.dumps(event.metadata), event.created_at.isoformat()),
        )
    return event


def persist_alert(alert: Alert) -> None:
    with connection() as db:
        db.execute(
            "INSERT OR REPLACE INTO alerts (id, source, payload, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (alert.id, alert.source.value, json.dumps(alert.model_dump(mode="json")), alert.status.value, utc_now()),
        )


def load_alert(alert_id: str) -> Alert:
    with connection() as db:
        row = db.execute("SELECT payload FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    return Alert.model_validate_json(row["payload"])


def list_alerts(source: str | None, severity: str | None, limit: int, offset: int) -> AlertListResponse:
    clauses: list[str] = []
    values: list[Any] = []
    if source:
        clauses.append("source = ?")
        values.append(source)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connection() as db:
        rows = db.execute(f"SELECT payload FROM alerts {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", (*values, limit, offset)).fetchall()
        total = db.execute(f"SELECT COUNT(*) AS count FROM alerts {where}", values).fetchone()["count"]
    alerts = [Alert.model_validate_json(row["payload"]) for row in rows]
    if severity:
        alerts = [item for item in alerts if item.severity.value == severity]
    return AlertListResponse(items=alerts, total=total)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Sentroxis Copilot API",
    version="0.1.0",
    description="Read-only-first incident-response co-pilot API with evidence-grounded advisory AI.",
    lifespan=lifespan,
)

allowed_origins = os.getenv("SENTROXIS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in allowed_origins if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Sentroxis-Token"],
)


@app.get("/api/health", response_model=StatusResponse)
def health() -> StatusResponse:
    return StatusResponse(service="sentroxis-copilot", status="operational", mode="read-only-demo", timestamp=datetime.now(timezone.utc))


@app.get("/api/setup", response_model=SetupState)
def get_setup_state(principal: Principal = Depends(get_principal)) -> SetupState:
    _ = principal
    return load_setup_state()


@app.post("/api/setup/{server_key}/start", response_model=SetupActionResponse)
def start_server_setup(
    server_key: ServerKey,
    request: SetupStartRequest,
    principal: Principal = Depends(get_principal),
) -> SetupActionResponse:
    require_role(principal, "analyst", "admin")
    state = load_setup_state()
    try:
        next_state, server, message = start_readiness(state, server_key, request.endpoint, request.version)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    save_setup_state(next_state)
    audit = save_audit(principal, "setup.readiness.started", server.key, {"mode": request.mode})
    next_action = (
        "Continue through the Velociraptor wizard and validate TLS, identity, and read-only health."
        if server.key == "velociraptor"
        else "Continue through Wazuh Manager, Indexer, identity, and read-only health checks."
    )
    return SetupActionResponse(server=server, message=message, next_action=next_action, audit_id=audit.id)


@app.get("/api/alerts", response_model=AlertListResponse)
def get_alerts(
    source: str | None = Query(default=None, pattern="^(wazuh|velociraptor|demo)$"),
    severity: str | None = Query(default=None, pattern="^(low|medium|high|critical)$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    principal: Principal = Depends(get_principal),
) -> AlertListResponse:
    _ = principal
    return list_alerts(source, severity, limit, offset)


@app.post("/api/alerts/ingest", response_model=Alert, status_code=201)
def ingest_alert(request: AlertIngestRequest, principal: Principal = Depends(get_principal)) -> Alert:
    require_role(principal, "analyst", "admin")
    if request.source == "wazuh":
        alert = wazuh.normalize_alert(request.payload)
    else:
        raw = request.payload
        alert = Alert(
            id=f"{request.source}-{raw.get('id') or uuid.uuid4().hex[:10]}",
            source=request.source,
            title=str(raw.get("title") or "Normalized security signal")[:240],
            description=str(raw.get("description") or raw.get("content") or "")[:4000],
            severity="medium",
            rule_id=str(raw.get("rule_id") or "unknown"),
            agent_name=str(raw.get("agent_name") or "unknown")[:120],
            raw=raw,
        )
    persist_alert(alert)
    save_audit(principal, "alert.ingested", alert.id, {"source": alert.source.value})
    return alert


@app.post("/api/demo/load", response_model=AlertListResponse)
def load_demo(principal: Principal = Depends(get_principal)) -> AlertListResponse:
    require_role(principal, "analyst", "admin")
    demo = [
        {
            "id": "demo-001",
            "rule": {"id": "100001", "description": "PowerShell encoded command execution", "level": 14},
            "agent": {"name": "ws-fin-07", "ip": "10.20.4.17"},
            "timestamp": "2026-08-24T08:21:00Z",
            "full_log": "powershell.exe -EncodedCommand AAECAwQ=",
        },
        {
            "id": "demo-002",
            "rule": {"id": "100002", "description": "New scheduled task created", "level": 10},
            "agent": {"name": "srv-app-02", "ip": "10.20.8.42"},
            "timestamp": "2026-08-24T08:14:00Z",
            "full_log": "schtasks /create /tn updater /tr powershell.exe",
        },
        {
            "id": "demo-003",
            "rule": {"id": "100003", "description": "Suspicious LSASS access", "level": 13},
            "agent": {"name": "dc-east-01", "ip": "10.20.1.11"},
            "timestamp": "2026-08-24T07:58:00Z",
            "full_log": "Access to lsass.exe memory detected",
        },
        {
            "id": "demo-004",
            "rule": {"id": "100004", "description": "Suspicious file cleanup", "level": 8},
            "agent": {"name": "ws-ops-12", "ip": "10.20.6.9"},
            "timestamp": "2026-08-24T07:40:00Z",
            "full_log": "File deletion from temporary directory",
        },
    ]
    for payload in demo:
        persist_alert(wazuh.normalize_alert(payload).model_copy(update={"source": Source.demo}))
    save_audit(principal, "demo.loaded", "demo-fixture", {"count": str(len(demo))})
    return list_alerts(None, None, 100, 0)


@app.get("/api/alerts/{alert_id}", response_model=Alert)
def get_alert(alert_id: str, principal: Principal = Depends(get_principal)) -> Alert:
    _ = principal
    return load_alert(alert_id)


@app.get("/api/alerts/{alert_id}/analysis", response_model=AIAnalysis)
def analyze_alert(alert_id: str, principal: Principal = Depends(get_principal)) -> AIAnalysis:
    alert = load_alert(alert_id)
    result = agent.analyze(alert)
    save_audit(principal, "ai.analysis.requested", alert_id, {"mode": "deterministic-advisory"})
    return result


@app.post("/api/investigations", response_model=Investigation, status_code=201)
def create_investigation(request: InvestigationCreate, principal: Principal = Depends(get_principal)) -> Investigation:
    alert = load_alert(request.alert_id)
    investigation = Investigation(
        id=f"inv-{uuid.uuid4().hex[:12]}",
        alert_id=alert.id,
        hypothesis=request.hypothesis,
        timeline=[TimelineEvent(
            timestamp=alert.timestamp,
            title="Alert observed",
            detail=alert.title,
            source=alert.source,
            confidence=0.9,
            evidence_refs=[f"alert:{alert.id}"],
        )],
    )
    with connection() as db:
        db.execute(
            "INSERT INTO investigations (id, alert_id, payload, created_at) VALUES (?, ?, ?, ?)",
            (investigation.id, investigation.alert_id, investigation.model_dump_json(), utc_now()),
        )
    save_audit(principal, "investigation.created", investigation.id, {"alert_id": alert.id})
    return investigation


@app.post("/api/alerts/{alert_id}/evidence", response_model=Evidence, status_code=201)
def collect_demo_evidence(alert_id: str, principal: Principal = Depends(get_principal)) -> Evidence:
    require_role(principal, "analyst", "admin")
    alert = load_alert(alert_id)
    evidence = velociraptor.normalize_evidence(alert, {
        "artifact": "Windows.System.Services",
        "content": f"Read-only collection placeholder for {alert.agent_name}; no command executed.",
    })
    save_audit(principal, "evidence.collection.proposed", alert_id, {"source": "velociraptor", "approval": "not-required-demo"})
    return evidence


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest, principal: Principal = Depends(get_principal)) -> ChatResponse:
    alert = load_alert(request.alert_id) if request.alert_id else None
    response = agent.chat(request.message, alert)
    save_audit(principal, "ai.chat.requested", request.alert_id or "unscoped", {"citations": str(len(response.citations))})
    return response


@app.post("/api/actions/proposals", response_model=ActionProposal, status_code=202)
def propose_action(proposal: ActionProposal, principal: Principal = Depends(get_principal)) -> ActionProposal:
    require_role(principal, "analyst", "admin")
    if not proposal.requires_approval:
        raise HTTPException(status_code=400, detail="Response actions must require explicit approval")
    load_alert(proposal.alert_id)
    save_audit(principal, "response.action.proposed", proposal.alert_id, {"action": proposal.action, "requires_approval": "true"})
    return proposal


@app.get("/api/audit", response_model=list[AuditEvent])
def get_audit(principal: Principal = Depends(get_principal), limit: int = Query(default=50, ge=1, le=100)) -> list[AuditEvent]:
    require_role(principal, "analyst", "admin")
    with connection() as db:
        rows = db.execute("SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [AuditEvent(
        id=row["id"],
        actor=row["actor"],
        action=row["action"],
        target=row["target"],
        created_at=datetime.fromisoformat(row["created_at"]),
        metadata=json.loads(row["metadata"]),
    ) for row in rows]
