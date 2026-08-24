from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from .models import SetupServer, SetupState, SetupStatus, WizardStep


def _steps_for(key: str) -> list[WizardStep]:
    if key == "velociraptor":
        return [
            WizardStep(id="vr-endpoint", title="Server endpoint", description="Enter the HTTPS URL of the Velociraptor frontend or API."),
            WizardStep(id="vr-tls", title="TLS verification", description="Confirm the server certificate and trust boundary."),
            WizardStep(id="vr-identity", title="Service identity", description="Connect a least-privilege read-only service account."),
            WizardStep(id="vr-test", title="Readiness check", description="Verify health without launching a hunt or collection."),
        ]
    return [
        WizardStep(id="wazuh-endpoint", title="Manager endpoint", description="Enter the HTTPS URL of the Wazuh Server API."),
        WizardStep(id="wazuh-indexer", title="Indexer endpoint", description="Configure a separate, bounded Indexer search endpoint."),
        WizardStep(id="wazuh-identity", title="Service identity", description="Connect a least-privilege read-only service account."),
        WizardStep(id="wazuh-test", title="Readiness check", description="Verify API reachability without changing agents or rules."),
    ]


def default_state() -> SetupState:
    return SetupState(
        servers=[
            SetupServer(
                key="wazuh",
                name="Wazuh Server",
                tagline="Detection and alert telemetry",
                description="Connect the Wazuh Manager API and Indexer to normalize alerts into the incident queue.",
                steps=_steps_for("wazuh"),
            ),
            SetupServer(
                key="velociraptor",
                name="Velociraptor Server",
                tagline="Endpoint evidence collection",
                description="Configure bounded, read-only artifact collection with evidence provenance and chain of custody.",
                steps=_steps_for("velociraptor"),
            ),
        ],
    )


def start_readiness(state: SetupState, key: str, endpoint: str, version: str | None) -> tuple[SetupState, SetupServer, str]:
    parsed = urlparse(endpoint)
    if parsed.scheme != "https":
        raise ValueError("Server endpoint must use HTTPS")
    if not parsed.netloc:
        raise ValueError("Server endpoint must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("Credentials must not be embedded in the endpoint URL")
    servers = []
    selected: SetupServer | None = None
    now = datetime.now(timezone.utc)
    for server in state.servers:
        if server.key == key:
            selected = server.model_copy(update={
                "status": SetupStatus.ready,
                "endpoint": endpoint.rstrip("/"),
                "version": version,
                "last_checked": now,
            })
            servers.append(selected)
        else:
            servers.append(server)
    if selected is None:
        raise KeyError(key)
    return state.model_copy(update={"servers": servers, "updated_at": now}), selected, f"{selected.name} is ready for a read-only health check."
