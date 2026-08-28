from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import httpx

from backend.core.auth import (
    SESSION_COOKIE,
    Principal,
    authenticate,
    clear_session,
    configure_auth_db,
    create_session,
    get_principal,
    principal_payload,
    register_first_user,
    registration_allowed,
    require_role,
    set_session_cookie,
    verify_principal_password,
)
from backend.core.llm_agent import agent
from backend.core.setup_service import default_state, start_readiness
from backend.core.velociraptor_setup import VelociraptorSetupService
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
    VelociraptorPrepareRequest,
    VelociraptorPrepareResponse,
    VelociraptorConfigGenerateRequest,
    VelociraptorConfigGenerateResponse,
    VelociraptorBundleArtifact,
    VelociraptorBundlesResponse,
    VelociraptorBundleResponse,
    VelociraptorCatalog,
    VelociraptorRunRequest,
    VelociraptorRunResponse,
    VelociraptorServerStatusResponse,
    VelociraptorWizardInput,
    VelociraptorWizardOutput,
    VelociraptorWizardStartRequest,
    VelociraptorWizardStartResponse,
    WazuhAgentDeployRequest,
    WazuhAgentDeployResponse,
    Source,
    TimelineEvent,
)
from backend.ingestion.velociraptor_service import VelociraptorService
from backend.ingestion.wazuh_service import WazuhService


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("SENTROXIS_DB_PATH", str(BASE_DIR / "sentroxis.db")))


class AuthCredentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class RegisterRequest(AuthCredentials):
    name: str = Field(min_length=1, max_length=120)


class AuthResponse(BaseModel):
    authenticated: bool
    user: dict[str, str] | None = None
    registration_open: bool
    message: str


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
velociraptor_setup = VelociraptorSetupService(BASE_DIR / "runtime" / "velociraptor")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db() -> None:
    configure_auth_db(str(DB_PATH))
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
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """
        )
        db.execute("DELETE FROM alerts WHERE source = 'demo' OR id LIKE 'demo-%'")


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


@app.get("/api/auth/status", response_model=AuthResponse)
def auth_status(sentroxis_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> AuthResponse:
    try:
        principal = get_principal(sentroxis_session)
    except HTTPException:
        principal = None
    return AuthResponse(
        authenticated=principal is not None,
        user=principal_payload(principal) if principal else None,
        registration_open=registration_allowed(),
        message="Authenticated" if principal else "Sign in to continue",
    )


@app.post("/api/auth/register", response_model=AuthResponse, status_code=201)
def register(request: RegisterRequest, response: Response) -> AuthResponse:
    try:
        principal = register_first_user(request.name, request.email, request.password)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    token = create_session(principal)
    set_session_cookie(response, token)
    save_audit(principal, "auth.registered", principal.subject, {"method": "local_password"})
    return AuthResponse(authenticated=True, user=principal_payload(principal), registration_open=False, message="Account created")


@app.post("/api/auth/login", response_model=AuthResponse)
def login(request: AuthCredentials, response: Response) -> AuthResponse:
    principal = authenticate(request.email, request.password)
    if not principal:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_session(principal)
    set_session_cookie(response, token)
    save_audit(principal, "auth.logged_in", principal.subject, {"method": "local_password"})
    return AuthResponse(authenticated=True, user=principal_payload(principal), registration_open=False, message="Signed in successfully")


@app.post("/api/auth/logout", response_model=AuthResponse)
def logout(response: Response, sentroxis_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> AuthResponse:
    principal = None
    if sentroxis_session:
        try:
            principal = get_principal(sentroxis_session)
        except HTTPException:
            principal = None
    if principal:
        save_audit(principal, "auth.logged_out", principal.subject)
    clear_session(response, sentroxis_session)
    return AuthResponse(authenticated=False, user=None, registration_open=registration_allowed(), message="Signed out")


@app.get("/api/health", response_model=StatusResponse)
def health() -> StatusResponse:
    return StatusResponse(service="sentroxis-copilot", status="operational", mode="authenticated-read-only", timestamp=datetime.now(timezone.utc))


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


@app.get("/api/velociraptor/catalog", response_model=VelociraptorCatalog)
def velociraptor_catalog(principal: Principal = Depends(get_principal)) -> VelociraptorCatalog:
    _ = principal
    return velociraptor_setup.catalog()


@app.post("/api/velociraptor/prepare", response_model=VelociraptorPrepareResponse)
def prepare_velociraptor(request: VelociraptorPrepareRequest, principal: Principal = Depends(get_principal)) -> VelociraptorPrepareResponse:
    require_role(principal, "analyst", "admin")
    try:
        installation = velociraptor_setup.prepare(request.platform, request.confirm_download)
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=502, detail="Official binary download failed") from exc
    audit = save_audit(principal, "velociraptor.binary.prepared", installation.filename, {"verified": "true", "version": installation.version})
    return VelociraptorPrepareResponse(
        installation=installation,
        message="The official Velociraptor binary was downloaded and SHA-256 verified.",
        next_action="Review the command, then explicitly start the interactive config wizard.",
        audit_id=audit.id,
    )


@app.post("/api/velociraptor/config/generate", response_model=VelociraptorConfigGenerateResponse)
def generate_velociraptor_config(
    request: VelociraptorConfigGenerateRequest,
    principal: Principal = Depends(get_principal),
) -> VelociraptorConfigGenerateResponse:
    require_role(principal, "analyst", "admin")
    if not request.confirm_generate:
        raise HTTPException(status_code=400, detail="Explicit configuration confirmation is required")
    if not verify_principal_password(principal, request.password_confirmation):
        raise HTTPException(status_code=401, detail="Password confirmation did not match the signed-in account")
    try:
        installation = velociraptor_setup.load_installation()
        if installation.platform != request.platform:
            raise ValueError("Configuration platform must match the verified installation")
        result = velociraptor_setup.generate_self_signed_config(
            installation,
            server_os=request.server_os,
            datastore_path=request.datastore_path,
            log_path=request.log_path,
            certificate_years=request.certificate_years,
            use_registry_writeback=request.use_registry_writeback,
            frontend_hostname=request.frontend_hostname,
            use_websocket=request.use_websocket,
            gui_port=request.gui_port,
            admin_username=principal.email,
            password_confirmation=request.password_confirmation,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit = save_audit(
        principal,
        "velociraptor.config.generated",
        installation.filename,
        {
            "deployment": "self_signed",
            "server_os": request.server_os,
            "frontend_port": "8010",
            "gui_port": str(request.gui_port),
            "client_config": "generated",
            "admin_identity": principal.email,
        },
    )
    return VelociraptorConfigGenerateResponse(
        config_path=result["config_path"],
        client_config_path=result["client_config_path"],
        api_config_path=result["api_config_path"],
        frontend_url=result["frontend_url"],
        admin_username=result["admin_username"],
        endpoint_bundles=[VelociraptorBundleArtifact(**{key: bundle[key] for key in ("platform", "version", "filename", "download_url", "includes_msi", "msi_mode")}) for bundle in result["endpoint_bundles"]],
        message="Self-signed server, endpoint client, API client, and Linux/Windows endpoint ZIP configurations were generated. Frontend port is fixed at 8010.",
        audit_id=audit.id,
    )


@app.post("/api/velociraptor/wizard/start", response_model=VelociraptorWizardStartResponse)
def start_velociraptor_wizard(request: VelociraptorWizardStartRequest, principal: Principal = Depends(get_principal)) -> VelociraptorWizardStartResponse:
    _ = request
    require_role(principal, "analyst", "admin")
    raise HTTPException(
        status_code=410,
        detail="The free-form terminal wizard is disabled. Use the approved self-signed configuration workflow instead.",
    )


@app.get("/api/velociraptor/wizard/{session_id}", response_model=VelociraptorWizardOutput)
def get_velociraptor_wizard(session_id: str, principal: Principal = Depends(get_principal)) -> VelociraptorWizardOutput:
    _ = principal
    try:
        session = velociraptor_setup.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Wizard session not found") from exc
    return VelociraptorWizardOutput(
        session_id=session.session_id,
        output=session.snapshot(),
        running=session.process.poll() is None,
        exit_code=session.process.poll(),
        config_path=str(session.config_path),
        config_ready=session.config_path.is_file(),
    )


@app.post("/api/velociraptor/wizard/input", response_model=VelociraptorWizardOutput)
def send_velociraptor_wizard_input(request: VelociraptorWizardInput, principal: Principal = Depends(get_principal)) -> VelociraptorWizardOutput:
    require_role(principal, "analyst", "admin")
    try:
        session = velociraptor_setup.send_input(request.session_id, request.input)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Wizard session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return VelociraptorWizardOutput(
        session_id=session.session_id,
        output=session.snapshot(),
        running=session.process.poll() is None,
        exit_code=session.process.poll(),
        config_path=str(session.config_path),
        config_ready=session.config_path.is_file(),
    )


@app.get("/api/velociraptor/endpoints/bundles", response_model=VelociraptorBundlesResponse)
def list_velociraptor_endpoint_bundles(principal: Principal = Depends(get_principal)) -> VelociraptorBundlesResponse:
    _ = principal
    return VelociraptorBundlesResponse(bundles=[VelociraptorBundleArtifact(**bundle) for bundle in velociraptor_setup.list_endpoint_bundles()])


@app.post("/api/velociraptor/endpoints/bundle", response_model=VelociraptorBundleResponse)
def build_velociraptor_endpoint_bundle(request: VelociraptorPrepareRequest, principal: Principal = Depends(get_principal)) -> VelociraptorBundleResponse:
    require_role(principal, "analyst", "admin")
    if not request.confirm_download:
        raise HTTPException(status_code=400, detail="Explicit endpoint bundle confirmation is required")
    if request.platform.value not in {"linux-amd64", "windows-amd64"}:
        raise HTTPException(status_code=422, detail="Endpoint bundles are currently available for Linux amd64 and Windows amd64")
    try:
        bundle = velociraptor_setup.build_endpoint_bundle(request.platform)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit = save_audit(principal, "velociraptor.endpoint_bundle.created", bundle["filename"], {"platform": bundle["platform"], "includes_msi": str(bundle["includes_msi"])})
    return VelociraptorBundleResponse(**{key: bundle[key] for key in ("platform", "version", "filename", "download_url", "includes_msi", "msi_mode")}, message="Endpoint bundle created from verified/generated Velociraptor artifacts.", audit_id=audit.id)


@app.get("/api/velociraptor/endpoints/bundle/download/{platform}")
def download_velociraptor_endpoint_bundle(platform: str, principal: Principal = Depends(get_principal)) -> FileResponse:
    _ = principal
    if platform not in {"linux-amd64", "windows-amd64"}:
        raise HTTPException(status_code=404, detail="Endpoint bundle not found")
    try:
        version = velociraptor_setup.load_installation().version
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Velociraptor has not been prepared") from exc
    bundle_path = velociraptor_setup.runtime_dir / "bundles" / f"sentroxis-velociraptor-{platform}-v{version}.zip"
    if not bundle_path.is_file():
        raise HTTPException(status_code=404, detail="Build the endpoint bundle before downloading it")
    return FileResponse(bundle_path, media_type="application/zip", filename=bundle_path.name, headers={"Cache-Control": "no-store"})


@app.get("/api/velociraptor/api-config/download")
def download_velociraptor_api_config(principal: Principal = Depends(get_principal)) -> FileResponse:
    _ = principal
    try:
        _ = velociraptor_setup.load_installation()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Velociraptor has not been prepared") from exc
    api_config_path = velociraptor_setup.runtime_dir / "api.config.yaml"
    if not api_config_path.is_file():
        raise HTTPException(status_code=404, detail="API configuration has not been generated")
    return FileResponse(
        api_config_path,
        media_type="application/x-yaml",
        filename="velociraptor-api.config.yaml",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/velociraptor/status", response_model=VelociraptorServerStatusResponse)
def get_velociraptor_server_status(principal: Principal = Depends(get_principal)) -> VelociraptorServerStatusResponse:
    _ = principal
    try:
        installation = velociraptor_setup.load_installation()
    except FileNotFoundError:
        return VelociraptorServerStatusResponse(
            configured=False,
            running=False,
            message="Velociraptor is not prepared yet. Download and configure the verified local binary first.",
        )
    details = velociraptor_setup.server_details(installation)
    message = "Velociraptor server is running." if details["running"] else (
        "Configuration is ready; start the local server when approved." if details["configured"]
        else "The verified binary is ready; generate server.config.yaml before starting the server."
    )
    return VelociraptorServerStatusResponse(**details, message=message)


@app.post("/api/velociraptor/run", response_model=VelociraptorRunResponse)
def run_velociraptor_server(request: VelociraptorRunRequest, principal: Principal = Depends(get_principal)) -> VelociraptorRunResponse:
    require_role(principal, "analyst", "admin")
    try:
        installation = velociraptor_setup.load_installation()
        if installation.platform != request.platform:
            raise ValueError("Run platform must match the verified installation")
        pid = velociraptor_setup.run_server(installation, request.confirm_run)
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    details = velociraptor_setup.server_details(installation)
    audit = save_audit(principal, "velociraptor.server.started", str(details["pid"]), {"platform": request.platform.value, "approval": "explicit"})
    return VelociraptorRunResponse(
        running=details["running"],
        pid=details["pid"],
        command_preview=details["command_preview"],
        config_path=details["config_path"],
        gui_url=details["gui_url"],
        gui_port=details["gui_port"],
        log_path=details["log_path"],
        message="Velociraptor server process started from the verified project-local binary and generated configuration.",
        audit_id=audit.id,
    )


@app.post("/api/velociraptor/stop", response_model=VelociraptorRunResponse)
def stop_velociraptor_server(principal: Principal = Depends(get_principal)) -> VelociraptorRunResponse:
    require_role(principal, "analyst", "admin")
    installation = None
    try:
        installation = velociraptor_setup.load_installation()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Velociraptor has not been prepared")
    velociraptor_setup.stop_server()
    details = velociraptor_setup.server_details(installation)
    audit = save_audit(principal, "velociraptor.server.stopped", str(details["pid"] or "unknown"), {"approval": "explicit"})
    return VelociraptorRunResponse(
        running=details["running"],
        pid=details["pid"],
        command_preview=details["command_preview"],
        config_path=details["config_path"],
        gui_url=details["gui_url"],
        gui_port=details["gui_port"],
        log_path=details["log_path"],
        message="Velociraptor server process stopped.",
        audit_id=audit.id,
    )


@app.post("/api/wazuh/agents/deploy", response_model=WazuhAgentDeployResponse)
def build_wazuh_agent_deployment(request: WazuhAgentDeployRequest, principal: Principal = Depends(get_principal)) -> WazuhAgentDeployResponse:
    require_role(principal, "analyst", "admin")
    if not request.confirm_generate:
        raise HTTPException(status_code=400, detail="Explicit deployment-command confirmation is required")
    try:
        result = wazuh.deployment_commands(request.package, request.manager_address.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit = save_audit(principal, "wazuh.agent.deployment_commands.generated", request.package, {"manager_address": request.manager_address})
    return WazuhAgentDeployResponse(package=request.package, manager_address=request.manager_address.strip(), install_command=result["install_command"], start_command=result["start_command"], message="Run the install command on the endpoint, then run the start command. Sentroxis does not execute endpoint commands remotely.", audit_id=audit.id)


@app.get("/api/wazuh/overview")
def get_wazuh_overview(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    _ = principal
    try:
        return wazuh.live_overview()
    except Exception as exc:
        return {"agents": [], "alerts": [], "errors": [f"Wazuh live data request failed: {type(exc).__name__}"], "timestamp": datetime.now(timezone.utc)}


@app.get("/api/alerts", response_model=AlertListResponse)
def get_alerts(
    source: str | None = Query(default=None, pattern="^(wazuh|velociraptor)$"),
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
def collect_evidence(alert_id: str, principal: Principal = Depends(get_principal)) -> Evidence:
    require_role(principal, "analyst", "admin")
    alert = load_alert(alert_id)
    evidence = velociraptor.normalize_evidence(alert, {
        "artifact": "Windows.System.Services",
        "content": f"Read-only collection placeholder for {alert.agent_name}; no command executed.",
    })
    save_audit(principal, "evidence.collection.proposed", alert_id, {"source": "velociraptor", "approval": "not-required-read-only-placeholder"})
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
