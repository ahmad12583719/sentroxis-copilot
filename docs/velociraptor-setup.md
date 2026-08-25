# Velociraptor Setup in Sentroxis Copilot

Sentroxis Copilot provides a **bounded local configuration workflow** for Velociraptor. It downloads only a pinned official Velocidex release for the selected supported platform, verifies the binary against the published SHA-256 digest, and generates both `server.config.yaml` and `client.config.yaml` using that verified binary.

> The browser workflow is deliberately limited to **Self Signed SSL** with Basic authentication. It does not offer Let’s Encrypt or SSO deployment types, arbitrary download URLs, arbitrary shell commands, firewall changes, operating-system package installation, or automatic service creation.

## Operator flow

After signing in to Sentroxis Copilot, open **Project Setup → Velociraptor Server**. First download and verify the selected official binary. The configuration form then collects the operational values that require an operator decision.

| Item | Behavior |
|---|---|
| Deployment type | Fixed to **Self Signed SSL**. |
| DNS integration | Fixed to manual DNS configuration; NoIP and Cloudflare credential flows are not available. |
| Server operating system | Selected by the operator: Linux, Windows, or macOS. |
| Datastore and logs directories | Supplied by the operator. The logs directory defaults to `<datastore>/logs` if omitted. |
| Certificate lifetime | Selected by the operator: 1, 2, or 10 years. |
| Windows registry writeback | Selected by the operator. |
| Master frontend hostname or server IP | Supplied by the operator; the saved HTTPS endpoint is used as a convenient initial suggestion. |
| Experimental WebSocket communications | Selected by the operator. |
| Frontend port | Fixed to **8010**. |
| GUI port | Selected by the operator; it remains independent of the frontend client port. |
| First Velociraptor administrator | Automatically set to the signed-in Sentroxis user’s **email**, which is also the project’s login identity. |
| Administrator password | The signed-in user confirms their current Sentroxis password once. It is verified server-side and is never stored as plaintext. |

The configuration generator creates fresh Velociraptor key material. It generates `server.config.yaml`, then runs the official client-config operation to create `client.config.yaml`. The resulting client configuration uses the supplied server IP/DNS and **port 8010**, rather than `localhost:8000`.

## Files and permissions

The verified binary, server configuration, and client configuration are stored under `backend/runtime/velociraptor/`. On POSIX hosts, Sentroxis applies owner-only permissions to the generated configuration files. Treat both YAML files as sensitive deployment material and keep any backups under appropriate access control. [1]

The final **Run Velociraptor server** action is separate and explicit. Review the generated configuration before starting the server. The application does not create a background operating-system service; production service management is an operator responsibility.

## Local CLI helper

The repository retains `scripts/setup_velociraptor.py` for a local, operator-driven download and interactive preparation procedure. Use the signed-in browser workflow for the bounded project configuration and automatic `client.config.yaml` generation described above. The command-line helper is useful only when a local console workflow is specifically required.

## Deployment note

The official quickstart positions self-signed TLS with Basic authentication as a short-term, private-network configuration rather than a public-internet deployment. Do not expose the resulting GUI or frontend broadly without appropriate network controls. For long-term production operation, follow the official deployment guidance for TLS, authentication, network restrictions, backups, and host service management. [1] [2]

## References

[1]: https://docs.velociraptor.app/docs/deployment/quickstart/ "Velociraptor Quickstart Guide"
[2]: https://docs.velociraptor.app/downloads/ "Velociraptor Downloads and verification"
