# Velociraptor and Sentroxis installation

The repository now has one unified installer entry point in `Velociraptor/install.py`. It creates a fresh Sentroxis web-login account first, then opens an installation menu. The same account email and password are used to authenticate the Velociraptor configuration step.

> This installer never modifies Wazuh implementation or configuration. The existing `wazuh_installation.sh` is invoked only when the operator selects **Install Wazuh** from the menu.

## Unified workflow

Run from the repository root:

```bash
chmod 700 Velociraptor/*.py
./Velociraptor/install.py
```

### Task 01: fresh Sentroxis sign-up

The installer asks for a display name, email, password, and password confirmation. It intentionally starts fresh: if `backend/sentroxis.db` already exists, the installer asks for confirmation before deleting only the local Sentroxis account/session database. It does not delete Wazuh files, Wazuh data, Velociraptor files, or other project data.

The password must be at least 20 characters and contain uppercase, lowercase, a number, and a special character because it is also used as the Wazuh Indexer/Dashboard `admin` password. It is held in process memory for the workflow. The installer writes an identity handoff containing the account ID and email but never writes the plaintext password.

### Task 02: installation menu

After sign-up, the installer repeatedly displays:

```text
What would you like to install?
1. Install Wazuh
2. Install Velociraptor
3. Exit installer
```

Selecting **Install Wazuh** securely hands the Task 01 password to `wazuh_installation.sh` as the Indexer/Dashboard `admin` password. The unified installer generates separate random passwords for the internal `kibanaserver` and `wazuh-wui` accounts, applies them to the Wazuh configuration, and stores the resulting protected runtime credentials. It then returns to this menu. Selecting **Install Velociraptor** runs `Velociraptor/00_run_all_setup.py`, which calls `01_installation_files.py` and `03_setup_velociraptor.py` using the Task 01 identity and password. Selecting **Exit installer** leaves the account available for normal web login.

## Velociraptor scripts

| File | Purpose |
|---|---|
| `Velociraptor/install.py` | Fresh Sentroxis sign-up and Wazuh/Velociraptor/Exit menu. |
| `Velociraptor/00_run_all_setup.py` | Runs Velociraptor installation and configuration after Task 01; it does not create another account. |
| `Velociraptor/01_installation_files.py` | Downloads the allowlisted official binary and verifies its SHA-256 digest. |
| `Velociraptor/03_setup_velociraptor.py` | Generates self-signed server, endpoint-client, and API-client configurations. |

The retired `02_signup_credentials.py` script has been removed. Velociraptor configuration reuses the account created in Task 01. The password is passed to the configuration runner through standard input only. Wazuh receives the same password only as a protected environment-file handoff; the generated Wazuh service passwords are not passed to Velociraptor.

## Generated files

The default runtime directory is `backend/runtime/velociraptor/`:

```text
velociraptor
installation.json
server.config.yaml
client.config.yaml
api.config.yaml
setup-summary.json
```

Frontend client port is fixed to **8010**. The GUI binds locally on the selected GUI port, normally `8889`. The API configuration is generated using the official `config api_client` command and should be treated as sensitive private-key material.

## Running the project

After configuration, review `server.config.yaml` and start the project:

```bash
./startup.sh
```

`startup.sh` starts the project-local Velociraptor binary with:

```bash
./velociraptor --config server.config.yaml frontend -v
```

The Sentroxis Velociraptor page uses the same-origin development proxy route `/velociraptor-console/` to avoid cross-origin secure-cookie and CSRF failures. Open Sentroxis at `https://127.0.0.1:5173` and select the Velociraptor page. The page displays the full-screen local console without a separate left-side panel. Pressing `Ctrl+C` in the startup terminal stops Sentroxis and its child Velociraptor process together.

## Recovery and safety

If a previous configuration exists, use `./Velociraptor/install.py` after confirming the fresh-state prompt, or run `./Velociraptor/00_run_all_setup.py --force` with a valid Task 01 identity. If an interrupted binary download exists, the installation-file step resumes it only after HTTP range support is confirmed and always performs the final SHA-256 check.

All generated YAML files are owner-readable on POSIX systems. Do not print or commit `server.config.yaml`, `client.config.yaml`, or `api.config.yaml`.

## References

[1]: https://www.velociraptor-docs.org/docs/server_automation/server_api/ "Velociraptor Server API and API client configuration"
[2]: https://docs.velociraptor.app/docs/deployment/quickstart/ "Velociraptor Quickstart Guide"
[3]: https://docs.velociraptor.app/downloads/ "Velociraptor Downloads and verification"
