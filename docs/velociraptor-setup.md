# Velociraptor Setup Script

The project now includes `scripts/setup_velociraptor.py`. It detects the current operating system and CPU architecture, selects a pinned **official Velocidex release asset**, downloads it from the official GitHub releases location, and verifies the downloaded file against its published SHA-256 value before it can be used. The script supports Linux AMD64, Linux ARM64, macOS AMD64, macOS ARM64, and Windows AMD64.

> The script deliberately does **not** install operating-system packages, create a background service, change firewall rules, or start the Velociraptor server. It prepares a local, verified binary and configuration only; server startup remains an explicit operator action.

## Usage

Run the script from the repository root on the machine that will host the local Velociraptor configuration:

```bash
chmod 700 scripts/setup_velociraptor.py
./scripts/setup_velociraptor.py
```

Use the following command first if you want to inspect the detected platform and selected official download without writing files or opening the wizard:

```bash
./scripts/setup_velociraptor.py --dry-run
```

The script starts Velociraptor's official `config generate -i` workflow. Answer all deployment-specific questions interactively at runtime, such as the deployment type, server DNS name or IP address, and administrator account. When the wizard asks for the output filename, use `server.config.yaml` unless you intentionally supplied a different `--config` path.

| Configuration item | Handling |
|---|---|
| Release and binary | Automatically selected for the detected supported platform and SHA-256 verified. |
| Deployment type, DNS/IP, credentials, certificates, and other wizard prompts | Supplied by the operator at runtime. |
| `Frontend.bind_port` | Automatically finalized as **8010** after the wizard succeeds. |
| Default `Client.server_urls` entries using port `8000` | Synchronized to **8010** so newly generated clients use the same listener. |
| `GUI.bind_port` | Left unchanged; it is a separate administration GUI setting. |
| Server process | Not started by the script. Review the configuration before an explicit start. |

## Port behavior

Velociraptor's frontend service is the client-facing service. The official quickstart documents TCP port `8000` as its default, while the web administration GUI is normally separate on TCP port `8889`. This project changes `Frontend.bind_port` from the generated default to **8010** and synchronizes only default `Client.server_urls` entries still using `:8000` to `:8010`, so newly generated client configurations reach the same listener. It does not change `GUI.bind_port`, expose a bind address, or alter TLS/authentication settings. Review the generated YAML and ensure that client deployment configuration and network controls match the final port before enrolling endpoints. [1]

The same port-finalization behavior is applied to the existing Sentroxis browser-based Velociraptor wizard. That wizard still accepts operator input for all deployment-specific settings and applies the `8010` value only after a successful configuration file is generated.

## Safety and deployment notes

A server configuration contains cryptographic material and access-control settings. Treat it as sensitive and restrict its file permissions and backups. The script applies owner-only permissions on POSIX hosts after it writes the configuration. [1]

The official quickstart describes self-signed TLS with Basic authentication as appropriate for short-term, private testing rather than general internet exposure. For a production deployment, follow the official deployment guidance for TLS, identity management, network restrictions, backup strategy, and service management. [1] [2]

## References

[1]: https://docs.velociraptor.app/docs/deployment/quickstart/ "Velociraptor Quickstart Guide"
[2]: https://docs.velociraptor.app/downloads/ "Velociraptor Downloads and verification"
