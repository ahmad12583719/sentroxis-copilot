# Sentroxis Copilot

Sentroxis Copilot is an incident-response workspace that brings Wazuh security telemetry, endpoint investigation workflows, MITRE ATT&CK context, and an advisory AI co-pilot into one authenticated interface. This repository currently contains the **Wazuh installation and integration work** plus the existing Velociraptor setup area, which is intentionally handed off to a separate contributor.

> **Current project boundary:** Wazuh is implemented and documented through installation and startup. Velociraptor implementation, service startup, API behavior, and remaining Velociraptor documentation belong to the contributor assigned to that component.

## Current user workflow

The intended single-machine workflow is deliberately staged. A user clones the repository, installs Wazuh separately, completes the separate Velociraptor setup owned by the Velociraptor contributor, and then starts Sentroxis.

```bash
git clone https://github.com/ahmad12583719/sentroxis-copilot.git
cd sentroxis-copilot

# Stage 1: install and configure Wazuh.
sudo ./wazuh_installation.sh

# Stage 2: the Velociraptor contributor’s setup process goes here.
# Do not run or modify that process as part of the Wazuh installation.

# Stage 3: start Sentroxis after the required infrastructure is ready.
./startup.sh
```

`wazuh_installation.sh` is the only Wazuh installation entrypoint. `startup.sh` assumes Wazuh is already installed; it starts the project-managed Wazuh services, validates the Sentroxis application, and starts the backend and frontend. The legacy `start.sh` file remains a compatibility wrapper that delegates to `startup.sh`.

## Wazuh installation

The installer downloads the pinned Wazuh Docker deployment, currently Wazuh 4.7.5, into a hidden `.wazuh` directory beside the cloned project. The user does not need to manage that directory manually. It creates the single-node Wazuh stack, generates or preserves TLS certificates, applies strong non-default credentials, initializes the OpenSearch security database, configures the Wazuh Manager API credentials in both Manager and Dashboard configuration, and verifies service readiness.

The installer also creates a project-managed Nginx TLS proxy in front of the Wazuh Dashboard. This proxy allows the native Wazuh dashboard to be displayed in Sentroxis while preserving the normal standalone dashboard URL. The proxy owns host port 443; the dashboard container itself remains internal on port 5601.

The installer requires Linux with Docker Engine and the Compose plugin. It validates the SRS-oriented resource requirements before a real installation, including available storage, memory, x86-64 architecture, and the Wazuh/OpenSearch JVM setting. It does not enroll endpoints, enable active response, modify Velociraptor, or install Velociraptor.

For the complete technical explanation of the installation pipeline, Docker network, Nginx iframe proxy, FastAPI authentication, live Manager/Indexer queries, widget mappings, validation commands, and troubleshooting flow, read [`docs/wazuh-integration-architecture.md`](docs/wazuh-integration-architecture.md).

### Wazuh credentials

The installer prompts for three separate credentials: the Wazuh indexer `admin` password, the Wazuh dashboard password, and the Wazuh Server API password. Each password must be at least 20 characters and contain uppercase and lowercase letters, a number, and a special character. Use different passwords for each service. Never place passwords in Git, URLs, screenshots, issue reports, or pasted terminal output.

If a password has been exposed, rerun the installer and replace it. The installer updates the indexer users file, Compose environment values, and the Dashboard’s Wazuh API configuration together.

### Wazuh locations and ports

| Component | Location or endpoint | Purpose |
|---|---|---|
| Wazuh project data | `<clone>/\.wazuh/` | Project-local Compose deployment, certificates, and configuration |
| Wazuh Dashboard | `https://localhost/` | Native dashboard and the source used by the Sentroxis Wazuh tab |
| Sentroxis frontend | `https://localhost:5173` | Local HTTPS development frontend |
| Sentroxis backend | `http://localhost:8000` | FastAPI application API |
| Wazuh Manager API | `https://127.0.0.1:55000` by default | Local API endpoint used for health verification |
| Wazuh indexer | Docker network and port 9200 | Internal OpenSearch-compatible storage |
| Agent and event ports | 1514, 1515, and 514/UDP | Wazuh telemetry and agent communication |

The local frontend certificate is generated automatically by `startup.sh` under `runtime/sentroxis-dev-tls/`. The first browser visit to `https://localhost:5173` may require accepting a local self-signed certificate warning.

## Starting the application

After Wazuh has been installed and the separate Velociraptor contributor has completed the required setup, start Sentroxis with:

```bash
cd /path/to/sentroxis-copilot
./startup.sh
```

The script recreates the Python virtual environment, installs backend dependencies, installs frontend dependencies, runs backend and frontend validation, builds the frontend, starts the installed Wazuh Compose stack, and launches FastAPI and Vite over local development endpoints. It does not install Wazuh and it does not configure or start Velociraptor.

Open the application at:

```text
https://localhost:5173
```

The first authenticated workspace account is created through the application login screen. The current frontend exposes four primary tabs: **Wazuh**, **Velociraptor**, **Agent management**, and **AI co-pilot**. The Wazuh tab contains the native Wazuh dashboard frame, Wazuh alert summaries, and machine telemetry cards. The Velociraptor tab is reserved for the separate contributor’s implementation. Agent management currently contains the Wazuh enrollment area and does not execute endpoint enrollment automatically.

## Fresh installation reset

For a complete local reset, stop the project and Wazuh services before deleting files. The `down -v` form permanently deletes Wazuh Docker volumes and indexed event data.

```bash
cd "$HOME/Desktop/project"

if [ -f "$HOME/Desktop/project/sentroxis-copilot/.wazuh/single-node/docker-compose.yml" ]; then
  sudo docker compose \
    -f "$HOME/Desktop/project/sentroxis-copilot/.wazuh/single-node/docker-compose.yml" \
    -f "$HOME/Desktop/project/sentroxis-copilot/.wazuh/single-node/docker-compose.sentroxis.yml" \
    down -v || true
fi

sudo rm -rf -- "$HOME/Desktop/project/sentroxis-copilot/.wazuh"
rm -rf -- "$HOME/Desktop/project/sentroxis-copilot"

git clone https://github.com/ahmad12583719/sentroxis-copilot.git
cd sentroxis-copilot
sudo ./wazuh_installation.sh
# Complete the separate Velociraptor setup here.
./startup.sh
```

Do not delete `.wazuh` while containers are running. Do not use `down -v` unless indexed Wazuh data and certificates are intentionally disposable.

## Repository structure

```text
sentroxis-copilot/
├── README.md
├── wazuh_installation.sh
├── startup.sh
├── start.sh
├── backend/
├── frontend/
├── scripts/
│   ├── 00_run_all_setup.py
│   ├── 01_installation_files.py
│   ├── 02_signup_credentials.py
│   └── 03_setup_velociraptor.py
└── docs/
    └── velociraptor-contributor-readme.md
```

The Wazuh installer and Wazuh startup path are independent of the scripts under `scripts/`. The Velociraptor scripts and their runtime files must remain independently testable and independently owned.

## Validation

The repository’s current Wazuh-related changes are checked with:

```bash
bash -n wazuh_installation.sh startup.sh start.sh
cd frontend
npm run lint
npm test -- --run
npm run build
```

The frontend currently passes its tests and production build. Lint reports existing warnings but no errors. Wazuh container readiness must be verified on the target laptop because the sandbox cannot reproduce the user’s Docker host, certificates, and persistent volumes.

## Wazuh security boundaries

Wazuh credentials are never committed. The installer uses separate indexer, dashboard, and Manager API credentials, applies bcrypt hashes to the indexer users file, preserves TLS certificates, and keeps the Manager API private by default. The project-managed dashboard proxy is intended for the local single-machine MVP and permits framing only through its controlled local endpoint; do not expose it publicly without replacing the self-signed certificates, tightening the frame policy, and placing the service behind appropriate network controls.

The co-pilot remains advisory-only. It does not automatically deploy AI-generated Wazuh rules, execute active response, run shell commands, or enroll agents without an explicit future implementation and authorization boundary.

## Contributor handoff

The Velociraptor contributor should read [`docs/velociraptor-contributor-readme.md`](docs/velociraptor-contributor-readme.md) before changing Velociraptor files. That document describes the current Wazuh boundary, the existing Velociraptor scripts, the expected runtime locations, the frontend integration points, and the startup contract that must be respected.

## Restored Velociraptor project notes

The application includes a **Project setup** screen with two separate server installation sections: **Wazuh Server** for detection and alert telemetry, and **Velociraptor Server** for endpoint evidence collection. Selecting either card opens its setup sequence; selecting Velociraptor displays the dedicated web wizard with endpoint, TLS verification, service identity, and read-only readiness steps.

The setup screen records readiness state but does not install software on remote hosts or execute commands. The backend exposes `GET /api/setup` and `POST /api/setup/{server_key}/start`. Endpoints must use HTTPS and may not contain embedded credentials. This keeps the browser workflow safe while leaving room for a later, separately authorized deployment runner.

For a local console deployment, install Wazuh first with `sudo ./wazuh_installation.sh`, then complete the separate Velociraptor wizard using the existing scripts. After both infrastructure components are installed and configured, run `./startup.sh`. At the current handoff point, `startup.sh` starts Wazuh and Sentroxis; the Velociraptor contributor owns adding or finalizing safe Velociraptor service startup. Wazuh installation requires `sudo` and prompts for three strong credentials on the first run. Set `SENTROXIS_SKIP_WAZUH=1` only when Wazuh is intentionally managed outside this checkout.

Velociraptor remains a separate workflow owned by its existing setup scripts and guide. The Wazuh integration does not modify, install, or configure Velociraptor. See the [four-script Velociraptor setup guide](docs/velociraptor-setup.md) and the [Velociraptor contributor handoff](docs/velociraptor-contributor-readme.md) for that operator flow and its deployment boundaries.

| Setup item | Current behavior |
|---|---|
| Wazuh Server | Installed and started from the cloned checkout by `wazuh_installation.sh` and `startup.sh`; manager, indexer, dashboard, credentials, certificates, proxy, and health readiness are handled by the Wazuh workflow |
| Velociraptor Server | Existing HTTPS endpoint, TLS verification, service identity, and bounded collection readiness workflow; implementation and final startup integration remain with the Velociraptor contributor |
| Credentials | Not accepted in URLs; reserved for authenticated setup steps |
| Remote installation | Not executed by the browser wizard; readiness state only |
| Audit | Readiness start events are written to the backend audit store |

### Velociraptor installation workflow

The Project Setup screen includes an approval-gated Velociraptor flow. The backend selects a platform from an allowlisted official release catalog, downloads the matching Velocidex GitHub asset, verifies its published SHA-256 digest, and stores the verified binary under the ignored `backend/runtime/velociraptor/` directory.

After verification, the browser flow and the four-script console workflow use the official binary to generate a self-signed configuration from bounded operator-selected values. The frontend binds at `8010`; the same Sentroxis login email and password become the initial Velociraptor Basic-authentication account without persisting plaintext credentials; and the official client configuration command creates `client.config.yaml` with the supplied server IP or DNS name rather than `localhost`. The final **Run Velociraptor server** action requires separate explicit approval and launches only the fixed command `velociraptor --config server.config.yaml frontend`. A stop control is available for the process started by Sentroxis.

The Velociraptor implementation does not accept arbitrary download URLs, does not execute AI-generated commands, does not create systemd services, and does not install privileged packages automatically. The Wazuh installer does install Docker and the host bcrypt dependency when required, because Wazuh is a required privileged primary-node component. Production deployments should use the official deployment guidance for TLS, SSO, private-network controls, service accounts, backups, and operating-system service management. The quickstart self-signed and Basic authentication mode is suitable only for short-term private testing [1] [2].

After pulling the repository, install the infrastructure components separately, then start the application:

```bash
cd ~/Desktop/project/sentroxis-copilot
sudo ./wazuh_installation.sh
# Complete the separate Velociraptor workflow owned by the Velociraptor contributor.
./startup.sh
```

At the current handoff point, `startup.sh` starts the already-installed Wazuh services and Sentroxis application. It does not rerun the Velociraptor wizard or silently start a Velociraptor process. The Velociraptor contributor should update this paragraph and the startup integration after implementing and testing that component.

### Velociraptor runtime API

| Endpoint | Purpose | Safety boundary |
|---|---|---|
| `GET /api/velociraptor/catalog` | Return the official allowlisted release assets for the detected host | No arbitrary URLs |
| `POST /api/velociraptor/prepare` | Download and SHA-256 verify the selected release asset | Explicit confirmation and fixed asset map |
| `POST /api/velociraptor/config/generate` | Generate approved self-signed server and client configuration files | Fixed frontend port 8010, current-password confirmation, no free-form commands |
| `POST /api/velociraptor/run` | Start `frontend --config` after config creation | Explicit confirmation and generated config required |
| `POST /api/velociraptor/stop` | Stop the process started by the service | Analyst authorization |

### References

[1]: https://docs.velociraptor.app/downloads/ "Velociraptor official downloads"
[2]: https://docs.velociraptor.app/docs/deployment/quickstart/ "Velociraptor official quickstart"
