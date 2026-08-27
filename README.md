# Sentroxis Copilot

Sentroxis Copilot is an incident-response workspace that brings Wazuh security telemetry, endpoint investigation workflows, MITRE ATT&CK context, and an advisory AI co-pilot into one authenticated interface. This repository currently contains the **Wazuh installation and integration work** plus the existing Velociraptor setup area, which is intentionally handed off to a separate contributor.

> **Current project boundary:** Wazuh is implemented and documented through installation and startup. Velociraptor implementation, service startup, API behavior, and remaining Velociraptor documentation belong to the contributor assigned to that component.

## Current user workflow

The intended single-machine workflow is deliberately staged. A user clones the repository, runs the unified installer to create the Sentroxis account and choose Wazuh or Velociraptor, completes any required infrastructure setup, and then starts Sentroxis.

```bash
git clone https://github.com/ahmad12583719/sentroxis-copilot.git
cd sentroxis-copilot

# Create the Sentroxis account and open the installation menu.
chmod 700 install.py Velociraptor/*.py
./install.py

# Select Install Wazuh from the menu when prompted.
# The initial Sentroxis password becomes the Wazuh admin password.
# Internal Wazuh service passwords are generated automatically.

# After the selected infrastructure setup is complete:
./startup.sh
```

`wazuh_installation.sh` remains the direct Wazuh installation entrypoint for operators who intentionally want to run Wazuh separately. root-level `install.py` is the unified entrypoint that creates the initial Sentroxis account and securely hands the password to the Wazuh installer when Wazuh is selected. `startup.sh` assumes Wazuh is already installed; it starts the project-managed Wazuh services, validates the Sentroxis application, and starts the backend and frontend. The legacy `start.sh` file remains a compatibility wrapper that delegates to `startup.sh`.

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
├── Velociraptor/
│   ├── 00_run_all_setup.py
│   ├── 01_installation_files.py
│   ├── 02_signup_credentials.py
│   └── 03_setup_velociraptor.py
└── docs/
    └── velociraptor-contributor-readme.md
```

The Wazuh installer and Wazuh startup path are independent of the scripts under `Velociraptor/`. The Velociraptor scripts and their runtime files must remain independently testable and independently owned.

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

For a local console deployment, run `./install.py`. It creates a fresh Sentroxis web-login account and then presents a menu for Wazuh installation, Velociraptor installation, or exit. Selecting Wazuh invokes the existing `sudo ./wazuh_installation.sh` entry point and returns to the menu; selecting Velociraptor invokes the unified Velociraptor setup using the same account credentials. Wazuh installation remains independently controlled and may still be skipped with `SENTROXIS_SKIP_WAZUH=1` when managed outside this checkout.

See the [unified Velociraptor setup guide](docs/velociraptor-setup.md) and the [Velociraptor contributor handoff](docs/velociraptor-contributor-readme.md) for the operator flow and deployment boundaries.

| Setup item | Current behavior |
|---|---|
| Wazuh Server | Installed and started from the cloned checkout by `wazuh_installation.sh` and `startup.sh`; manager, indexer, dashboard, credentials, certificates, proxy, and health readiness are handled by the Wazuh workflow |
| Velociraptor Server | Installed through root-level `install.py` and the `Velociraptor/` verified setup runner; generated configs use the existing bounded self-signed workflow |
| Credentials | Not accepted in URLs; reserved for authenticated setup steps |
| Remote installation | Not executed by the browser wizard; readiness state only |
| Audit | Readiness start events are written to the backend audit store |

### Velociraptor installation workflow

The Project Setup screen includes an approval-gated Velociraptor flow. The backend selects a platform from an allowlisted official release catalog, downloads the matching Velocidex GitHub asset, verifies its published SHA-256 digest, and stores the verified binary under the ignored `backend/runtime/velociraptor/` directory.

After verification, the unified installer uses the official binary to generate a self-signed configuration from bounded operator-selected values. The frontend binds at `8010`; the same Sentroxis login email and password become the initial Velociraptor Basic-authentication account without persisting plaintext credentials; and the official client configuration command creates `client.config.yaml` with the supplied server IP or DNS name rather than `localhost`. `startup.sh` owns the fixed local server lifecycle and starts `./velociraptor --config server.config.yaml frontend -v`; `Ctrl+C` stops Sentroxis and its child Velociraptor process together. The dashboard contains no separate server start/stop controls.

The Velociraptor implementation does not accept arbitrary download URLs, does not execute AI-generated commands, does not create systemd services, and does not install privileged packages automatically. The Wazuh installer does install Docker and the host bcrypt dependency when required, because Wazuh is a required privileged primary-node component. Production deployments should use the official deployment guidance for TLS, SSO, private-network controls, service accounts, backups, and operating-system service management. The quickstart self-signed and Basic authentication mode is suitable only for short-term private testing [1] [2].

After pulling the repository, start the unified installer and then the application:

```bash
cd ~/Desktop/project/sentroxis-copilot
chmod 700 install.py Velociraptor/*.py
./install.py
./startup.sh
```

The unified installer handles the selected infrastructure flow. `startup.sh` starts already-configured project-local Velociraptor automatically when its binary and server configuration are present.

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
