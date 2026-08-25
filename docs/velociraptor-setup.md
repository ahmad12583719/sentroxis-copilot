# Four-Script Velociraptor Setup

The repository provides a **four-script local setup workflow** for a verified, self-signed Velociraptor deployment. It downloads only an allowlisted official binary, verifies its published SHA-256 digest, creates or verifies the initial Sentroxis account, and generates matching server and client configurations.

> The workflow uses **Self Signed SSL with Basic authentication**. It does not configure an external OIDC/SSO identity provider, create an operating-system service, alter firewall rules, install privileged packages, or expose a server automatically.

## Scripts

| Order | Script | Purpose |
|---:|---|---|
| 1 | `scripts/00_run_all_setup.py` | Master runner that invokes the other three scripts in the correct order. |
| 2 | `scripts/01_installation_files.py` | Detects the selected platform, downloads the pinned official release, verifies SHA-256, and writes local installation state. |
| 3 | `scripts/02_signup_credentials.py` | Creates or verifies the initial Sentroxis account and saves only the user identity for the next step. |
| 4 | `scripts/03_setup_velociraptor.py` | Verifies the same Sentroxis credentials, creates self-signed server and client configurations, and reports their paths. |

## Recommended command

Run all scripts in sequence from the repository root:

```bash
chmod 700 scripts/00_run_all_setup.py scripts/01_installation_files.py \
  scripts/02_signup_credentials.py scripts/03_setup_velociraptor.py
./scripts/00_run_all_setup.py
```

The master runner asks for the account, server, filesystem, certificate, network, and GUI choices once. It passes the password to Steps 2 and 3 through process standard input only; it does not write the password to a file or place it in a command-line argument. Sentroxis passwords must be **12–128 characters**, matching the application login policy.

If `backend/sentroxis.db` already contains an initial account, Step 2 detects it and shows its email as the default. Press Enter to reuse that account’s email, then enter its existing password. The workflow will not overwrite or silently replace an existing account with a different email.

## Required operator choices

| Setting | Handling |
|---|---|
| Deployment type | Fixed to **Self Signed SSL + Basic authentication**. |
| Frontend client port | Fixed to **8010**. |
| GUI port | Selected by the operator; default is `8889`. |
| Server operating system | Selected by the operator: Linux, Windows, or macOS. |
| Datastore and logs paths | Selected by the operator. |
| Certificate lifetime | Selected by the operator: 1, 2, or 10 years. |
| Windows registry writeback | Selected by the operator. |
| Public frontend DNS name or server IP | Selected by the operator and embedded in the generated client configuration. |
| Experimental WebSocket client communications | Selected by the operator. |
| Initial Velociraptor administrator | Reuses the Step 2 Sentroxis login **email**. |
| Initial Velociraptor password | Reuses the same Step 2 password after a local verification. Plaintext is not stored. |

The workflow generates fresh Velociraptor key material and creates these files under `backend/runtime/velociraptor/` by default:

```text
backend/runtime/velociraptor/
├── velociraptor
├── installation.json
├── server.config.yaml
├── client.config.yaml
└── setup-summary.json
```

After Step 3, the terminal prints the full `client.config.yaml` path. That client configuration contains the operator-selected server IP or DNS name and **port 8010**, not `localhost:8000`. Copy it securely into the endpoint packaging or deployment process; the script does not print its contents.

## Individual execution

The steps can also be run separately. Script 3 will reuse the email from the Step 2 identity handoff and prompt for the same account password again when it is not called by the master runner.

```bash
./scripts/01_installation_files.py
./scripts/02_signup_credentials.py
./scripts/03_setup_velociraptor.py
```

Use `--help` on any script to inspect its non-interactive arguments. For example, `scripts/01_installation_files.py --dry-run` displays the detected platform and official asset without downloading it.

## Security and deployment note

Generated server and client YAML files contain deployment-sensitive material. On POSIX hosts, the scripts apply owner-only permissions. Keep the files and their backups under appropriate access control. The official quickstart describes self-signed TLS with Basic authentication as suitable for short-term, private-network usage rather than broad public exposure. Use official deployment guidance for production TLS, identity, network controls, backups, and service management. [1] [2]

## References

[1]: https://docs.velociraptor.app/docs/deployment/quickstart/ "Velociraptor Quickstart Guide"
[2]: https://docs.velociraptor.app/downloads/ "Velociraptor Downloads and verification"
