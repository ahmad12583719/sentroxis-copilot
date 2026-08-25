# Velociraptor Contributor Handoff

## Purpose of this document

This document is the handoff guide for the contributor responsible for Velociraptor in Sentroxis-Copilot. The Wazuh implementation is already in place and must be treated as an existing dependency. The goal is to add or improve Velociraptor without breaking Wazuh installation, the single-machine user workflow, the authenticated frontend shell, or the project startup contract.

> **Ownership boundary:** Wazuh installation, Wazuh Docker services, Wazuh credentials, Wazuh TLS, the Wazuh dashboard proxy, Wazuh alert normalization, and the Wazuh tab are maintained separately. Velociraptor implementation belongs to the Velociraptor contributor. Do not edit Wazuh files or repurpose the Wazuh installer to install Velociraptor.

## Intended single-machine workflow

The end-user experience is staged. The user clones the repository once, installs Wazuh, completes the Velociraptor setup, and starts Sentroxis.

```text
1. Clone Sentroxis-Copilot.
2. Run sudo ./wazuh_installation.sh.
3. Run the Velociraptor setup/wizard owned by this contributor.
4. Run ./startup.sh.
5. Log in to https://localhost:5173 and use the four-tab workspace.
```

The Wazuh installation must remain a separate first-class step. The Velociraptor contributor may add or refine the Velociraptor step, but `startup.sh` must not silently install packages, download arbitrary binaries, run a wizard, overwrite credentials, or modify a user’s Velociraptor configuration. Installation and startup are different responsibilities.

## What the Wazuh contributor has implemented

The Wazuh installation entrypoint is the repository-root file:

```text
wazuh_installation.sh
```

It downloads the pinned Wazuh Docker deployment, prepares the single-node stack inside the cloned project’s hidden `.wazuh/` directory, generates or preserves TLS certificates, prompts for separate strong indexer/dashboard/API credentials, generates compatible bcrypt hashes, configures the Wazuh Manager API credentials, initializes indexer security, and starts the Wazuh services.

The installer also creates a project-managed Nginx proxy service. The proxy owns host port 443 and forwards HTTPS traffic to the internal Wazuh Dashboard service on port 5601. This is important because the native Wazuh response includes `X-Frame-Options: sameorigin`, while the Sentroxis Wazuh tab embeds the dashboard. The proxy removes the upstream framing header only at this controlled local endpoint and keeps the normal Wazuh URL:

```text
https://localhost/
```

The project startup entrypoint is:

```text
startup.sh
```

It starts the already-installed Wazuh Compose stack, prepares the Sentroxis Python environment, installs frontend dependencies, runs validation, creates a local HTTPS certificate for the Vite frontend, and starts FastAPI and Vite. The frontend is served at:

```text
https://localhost:5173
```

The legacy `start.sh` is only a compatibility wrapper for `startup.sh`.

## Files that belong to the Wazuh boundary

Do not modify these files for Velociraptor work unless the Wazuh maintainer explicitly approves the change:

| File or directory | Wazuh responsibility |
|---|---|
| `wazuh_installation.sh` | Wazuh installation, credentials, certificates, Compose customization, indexer security bootstrap, and readiness checks |
| `startup.sh` | Starting the installed Wazuh stack and Sentroxis application |
| `frontend/src/pages/Wazuh.jsx` | Wazuh dashboard frame, Wazuh alert summaries, and Wazuh machine telemetry |
| `frontend/src/pages/Agents.jsx` | Wazuh agent-management area and machine inventory UI |
| `frontend/vite.config.js` | Frontend development HTTPS and backend API proxy |
| `backend/ingestion/wazuh_service.py` | Wazuh payload normalization and stable alert model conversion |
| `.wazuh/` | Generated, ignored project-local Wazuh deployment state; never commit it |

The Wazuh installer owns generated files under `.wazuh/single-node/`, including the Compose override and the local dashboard proxy configuration. Do not hand-edit generated files as a permanent solution. Change the installer instead.

## Existing Velociraptor area

The existing Velociraptor scripts are under `scripts/`:

```text
scripts/00_run_all_setup.py
scripts/01_installation_files.py
scripts/02_signup_credentials.py
scripts/03_setup_velociraptor.py
```

The current guide for that area is:

```text
docs/velociraptor-setup.md
```

These scripts and their behavior are the Velociraptor contributor’s responsibility. Before changing them, read them in full, run their help or dry-run modes if available, and preserve their existing safety boundaries. Do not assume that Wazuh credentials, Wazuh API passwords, or Wazuh certificates can be reused for Velociraptor.

The current runtime convention described by the existing setup area is:

```text
backend/runtime/velociraptor/
```

Generated artifacts may include the verified Velociraptor binary, installation state, server configuration, client configuration, and a setup summary. Runtime artifacts, private keys, credentials, and generated configuration files must remain ignored and must never be committed.

The existing Velociraptor setup documentation describes a self-signed TLS and Basic-authentication workflow suitable for short-term private testing. If that workflow is changed, document the new certificate, identity, port, authentication, and storage behavior explicitly rather than leaving the next contributor to infer it from code.

## Frontend integration contract

The current frontend has four user-facing tabs:

| Tab | Current responsibility | Velociraptor contributor boundary |
|---|---|---|
| Wazuh | Native Wazuh dashboard, alert summary, machine telemetry, and Wazuh agent workspace | Do not change it for Velociraptor work |
| Velociraptor | Reserved Velociraptor workspace/page | Implement Velociraptor UI and workflows here |
| Agent management | Wazuh agent enrollment area and machine inventory | Add Velociraptor controls only in a clearly separate section; do not change Wazuh enrollment behavior |
| AI co-pilot | Authenticated advisory chatbot | Do not silently add Velociraptor execution or VQL execution here |

The Velociraptor tab may present hunts, evidence, timelines, IOC data, and report actions, but all mutating or collection operations require authenticated backend endpoints and explicit authorization. The browser must not execute arbitrary shell commands, arbitrary VQL, or arbitrary download URLs.

The existing frontend uses React/Vite. Keep the visual language, authenticated shell, navigation, responsive behavior, visible error states, and severity labels consistent with the rest of the application. Add tests for every new user-visible Velociraptor state: not configured, configuring, ready, running, completed, failed, and stopped.

## Backend integration contract

The backend is FastAPI under `backend/main.py`. Wazuh alert normalization is intentionally read-only and isolated in `backend/ingestion/wazuh_service.py`. Velociraptor code should remain isolated in its own service/module rather than being added to the Wazuh normalizer.

A safe Velociraptor integration should provide bounded, authenticated endpoints with explicit response models. A suggested contract is:

| Endpoint category | Expected behavior |
|---|---|
| Readiness | Return whether a verified binary/configuration exists without exposing private configuration contents |
| Configuration | Accept bounded, validated choices; never accept arbitrary commands or arbitrary URLs |
| Hunt creation | Require authentication and authorization, validate target and artifact choices, and create an auditable job |
| Hunt status | Return bounded progress, timestamps, target identity, and failure state |
| Evidence | Return provenance, hashes where appropriate, bounded fields, and no untrusted HTML execution |
| Reports | Generate/download controlled report artifacts with authorization checks and safe filenames |
| Stop/cancel | Affect only jobs created by the application and record the action in the audit trail |

All endpoints should return explicit `401` or `403` responses when authentication or authorization is missing. Errors should be displayed in the UI within the project’s normal error-state pattern. Long-running hunts should not block telemetry ingestion or the FastAPI event loop; use bounded asynchronous job handling and clear retry/timeout behavior.

## Important port and network rules

For the current single-laptop MVP, Wazuh uses its project-managed HTTPS endpoint at `https://localhost/`, its Manager API on the locally restricted port 55000, and internal Docker networking for the indexer and dashboard services. The Sentroxis frontend uses HTTPS port 5173 and the FastAPI service uses port 8000.

The existing Velociraptor setup area uses a frontend port of 8010 in its generated client configuration and may use a separately selected GUI port. Do not silently reuse Wazuh ports, the Sentroxis frontend port, or the FastAPI port. Document any Velociraptor port mapping in the Velociraptor guide and keep it configurable where the existing workflow permits.

Do not expose a Wazuh password, Velociraptor password, private key, client configuration, server configuration, or token in a URL, browser log, Git commit, screenshot, exception trace, or API response. Do not use the Wazuh dashboard password as a Velociraptor password.

## Startup behavior to preserve

At the current handoff point, the following should be true:

```text
sudo ./wazuh_installation.sh   # installs/configures Wazuh only
# Velociraptor contributor workflow  # separate setup/configuration
./startup.sh                    # starts installed Wazuh and Sentroxis
```

`startup.sh` must remain safe to run after both infrastructure components have already been configured. It should not rerun a Velociraptor wizard on every start, overwrite generated client configuration, or make the user repeat setup prompts. If Velociraptor startup is added later, it must detect a valid existing configuration, use a fixed and documented command, avoid duplicate processes, expose readiness, and fail without taking down Wazuh or the Sentroxis frontend.

If the Velociraptor contributor needs to change `startup.sh`, keep the Wazuh block intact and test these independent cases:

1. Wazuh installed and Velociraptor not yet configured.
2. Wazuh installed and Velociraptor configured.
3. Wazuh intentionally skipped through the documented environment override.
4. Wazuh service unavailable while the Sentroxis application still needs a useful error state.
5. A repeated `startup.sh` run after a previous process has stopped.

## Common mistakes to avoid

### Do not place Velociraptor under `.wazuh`

`.wazuh` is owned by the Wazuh installer. Use `backend/runtime/velociraptor/` or another documented Velociraptor-specific runtime directory.

### Do not edit generated Wazuh files manually

The installer restores and regenerates its managed Wazuh files on reruns. A manual change under `.wazuh` will be overwritten and may produce a difficult-to-diagnose Compose or security-bootstrap failure.

### Do not use the Wazuh dashboard iframe as a Velociraptor pattern

The Wazuh iframe works through a dedicated local HTTPS proxy because Wazuh emits restrictive framing headers. Velociraptor’s UI and API should not be copied into the Wazuh proxy or coupled to Wazuh’s credentials. Use an explicit Velociraptor route and document its security behavior.

### Do not print secrets while debugging

Avoid commands such as `grep` that print password-bearing Compose entries. When collecting diagnostics, redact passwords, hashes, cookies, private keys, and full generated YAML. Prefer service status, sanitized logs, HTTP status codes, and file permission output.

### Do not confuse “container is Up” with “service is ready”

A running container can still be initializing or failing authentication. Provide a real readiness check for Velociraptor and show its state in the UI. The same principle was important in the Wazuh implementation because the dashboard can be reachable while its API connection is not ready.

## Recommended contributor validation

Before opening a pull request, run:

```bash
bash -n startup.sh start.sh wazuh_installation.sh
cd frontend
npm run lint
npm test -- --run
npm run build
cd ..
python3 -m compileall scripts backend
```

Run the Velociraptor setup in a disposable private test environment, verify that the Wazuh dashboard still opens at `https://localhost/`, verify that `https://localhost:5173` still loads, and confirm that Wazuh installation is not triggered by an application restart.

Check the Git diff carefully. The following must never appear in a commit:

```text
.wazuh/
backend/runtime/velociraptor/
*.pem
*.key
*.crt
*.yaml with credentials
*.json with credentials
```

## Handoff checklist

Before considering Velociraptor work complete, document the exact setup command, required operator inputs, generated files, ports, authentication method, TLS behavior, service start/stop behavior, readiness checks, failure recovery, and cleanup procedure. Add frontend and backend tests, preserve Wazuh behavior, and update the main README only after the Velociraptor workflow is stable.

The final user-facing README should continue to state that Wazuh is installed first, Velociraptor is configured through its separate contributor-owned workflow, and `startup.sh` starts the already-installed application stack. It should not claim that Velociraptor is complete until its implementation and verification are finished.
