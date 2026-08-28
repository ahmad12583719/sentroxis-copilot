from __future__ import annotations

import ipaddress
import os
import re
import shlex
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.core.mitre_engine import enrich_alert, severity_from_payload
from backend.core.models import Alert, Source


class WazuhService:
    """Normalize Wazuh data and provide bounded, read-only live queries."""

    def normalize_alert(self, payload: dict[str, Any]) -> Alert:
        rule = payload.get("rule") if isinstance(payload.get("rule"), dict) else {}
        agent = payload.get("agent") if isinstance(payload.get("agent"), dict) else {}
        alert_id = str(payload.get("id") or payload.get("_id") or payload.get("timestamp") or "wazuh-unknown")
        timestamp = self._timestamp(payload.get("timestamp"))
        alert = Alert(
            id=f"wazuh-{alert_id}",
            source=Source.wazuh,
            title=str(rule.get("description") or payload.get("title") or "Wazuh security alert")[:240],
            description=str(payload.get("full_log") or payload.get("description") or "")[:4000],
            severity=severity_from_payload(payload),
            rule_id=str(rule.get("id") or payload.get("rule_id") or "unknown"),
            agent_name=str(agent.get("name") or payload.get("agent_name") or "unknown")[:120],
            agent_ip=str(agent.get("ip"))[:64] if agent.get("ip") else None,
            timestamp=timestamp,
            raw=payload,
        )
        return enrich_alert(alert)

    def enroll_agent(self, *, name: str, ip: str | None, group: str | None, platform: str, manager_address: str | None) -> dict[str, str]:
        """Create one Wazuh agent and return a one-time client-key workflow.

        The API token and service credentials remain server-side. The returned
        client key is intentionally exposed only to the authenticated analyst
        who requested this enrollment so it can be imported on the endpoint.
        """
        manager_url = os.getenv("WAZUH_MANAGER_API_URL", "https://127.0.0.1:55000").rstrip("/")
        api_user = os.getenv("WAZUH_API_USER", "wazuh-wui")
        api_password = os.getenv("WAZUH_API_PASSWORD", "")
        verify: bool | str = os.getenv("WAZUH_CA_BUNDLE") or False
        if not api_password:
            raise RuntimeError("WAZUH_API_PASSWORD is not configured")
        address = (manager_address or os.getenv("WAZUH_AGENT_MANAGER_ADDRESS") or "127.0.0.1").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}", address):
            raise ValueError("Manager address must be a hostname or IP address")
        if ip:
            try:
                ipaddress.ip_address(ip.strip())
            except ValueError as exc:
                raise ValueError("Endpoint IP must be a valid IPv4 or IPv6 address") from exc
        timeout = httpx.Timeout(10.0, connect=3.0)
        with httpx.Client(verify=verify, timeout=timeout) as client:
            token_response = client.post(f"{manager_url}/security/user/authenticate", auth=(api_user, api_password))
            token_response.raise_for_status()
            token_data = token_response.json().get("data")
            token = token_data.get("token") if isinstance(token_data, dict) else token_data
            if not isinstance(token, str) or not token:
                raise RuntimeError("Wazuh API authentication returned no token")
            payload: dict[str, Any] = {"name": name}
            if ip:
                payload["ip"] = ip
            if group:
                payload["groups"] = group
            response = client.post(
                f"{manager_url}/agents",
                params={"pretty": "true"},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json().get("data") or {}
            agent_id = str(data.get("id") or "")
            key = str(data.get("key") or "")
            if not agent_id or not key:
                raise RuntimeError("Wazuh did not return an agent ID and client key")
        quoted_key = shlex.quote(key)
        if platform == "windows":
            install_command = "Install the Wazuh agent MSI for the Manager version on the endpoint, then open PowerShell as Administrator."
            enroll_command = f'& "C:\\Program Files (x86)\\ossec-agent\\manage_agents.exe" -i {key!r}'
            configure_command = f"$p='C:\\Program Files (x86)\\ossec-agent\\ossec.conf'; (Get-Content $p) -replace '<address>.*</address>', '<address>{address}</address>' | Set-Content $p"
            restart_command = "Restart-Service -Name WazuhSvc; Get-Service -Name WazuhSvc"
        else:
            install_command = f"wget -q https://packages.wazuh.com/4.x/apt/pool/main/w/wazuh-agent/wazuh-agent_4.7.5-1_amd64.deb -O /tmp/wazuh-agent_4.7.5-1_amd64.deb && sudo WAZUH_MANAGER={shlex.quote(address)} dpkg -i /tmp/wazuh-agent_4.7.5-1_amd64.deb"
            enroll_command = f"sudo /var/ossec/bin/manage_agents -i {quoted_key}"
            configure_command = f"sudo sed -i 's#<address>.*</address>#<address>{address}</address>#' /var/ossec/etc/ossec.conf"
            restart_command = "sudo systemctl enable wazuh-agent && sudo systemctl restart wazuh-agent && sudo systemctl --no-pager status wazuh-agent"
        return {
            "id": agent_id,
            "name": name,
            "key": key,
            "platform": platform,
            "manager_address": address,
            "install_command": install_command,
            "enroll_command": enroll_command,
            "configure_command": configure_command,
            "restart_command": restart_command,
        }

    @staticmethod
    def deployment_commands(package: str, manager_address: str) -> dict[str, str]:
        """Build endpoint-local install/start commands without running them."""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}", manager_address):
            raise ValueError("Manager address must be a hostname or IP address")
        package_urls = {
            "deb-amd64": "https://packages.wazuh.com/4.x/apt/pool/main/w/wazuh-agent/wazuh-agent_4.7.5-1_amd64.deb",
            "deb-aarch64": "https://packages.wazuh.com/4.x/apt/pool/main/w/wazuh-agent/wazuh-agent_4.7.5-1_arm64.deb",
            "rpm-amd64": "https://packages.wazuh.com/4.x/yum/wazuh-agent-4.7.5-1.x86_64.rpm",
            "rpm-aarch64": "https://packages.wazuh.com/4.x/yum/wazuh-agent-4.7.5-1.aarch64.rpm",
        }
        if package in package_urls:
            filename = package_urls[package].rsplit("/", 1)[-1]
            package_manager = 'dpkg -i' if package.startswith('deb-') else 'rpm -ih'
            install = f"curl -O {package_urls[package]} && sudo WAZUH_MANAGER={shlex.quote(manager_address)} {package_manager} {filename}"
            start = "sudo systemctl daemon-reload && sudo systemctl enable wazuh-agent && sudo systemctl start wazuh-agent && sudo systemctl --no-pager status wazuh-agent"
        elif package == "msi":
            installer = "wazuh-agent-4.7.5-1.msi"
            install = f"Invoke-WebRequest -Uri https://packages.wazuh.com/4.x/windows/{installer} -OutFile {installer}; .\\{installer} /q WAZUH_MANAGER=\"{manager_address}\""
            start = "NET START Wazuh"
        elif package == "macos-intel":
            installer = "wazuh-agent-4.7.5-1.intel64.pkg"
            install = f"curl -O https://packages.wazuh.com/4.x/macos/{installer} && echo \"WAZUH_MANAGER='{manager_address}'\" > /tmp/wazuh_envs && sudo installer -pkg {installer} -target /"
            start = "sudo /Library/Ossec/bin/wazuh-control start"
        else:
            installer = "wazuh-agent-4.7.5-1.arm64.pkg"
            install = f"curl -O https://packages.wazuh.com/4.x/macos/{installer} && echo \"WAZUH_MANAGER='{manager_address}'\" > /tmp/wazuh_envs && sudo installer -pkg {installer} -target /"
            start = "sudo /Library/Ossec/bin/wazuh-control start"
        return {"install_command": install, "start_command": start}

    def live_overview(self) -> dict[str, Any]:
        """Return bounded live Manager agents and Indexer alerts.

        The caller supplies credentials through the process environment. TLS
        verification is enabled when WAZUH_CA_BUNDLE is set; local self-signed
        MVP deployments explicitly default to disabled verification.
        """
        manager_url = os.getenv("WAZUH_MANAGER_API_URL", "https://127.0.0.1:55000").rstrip("/")
        indexer_url = os.getenv("WAZUH_INDEXER_URL", "https://127.0.0.1:9200").rstrip("/")
        api_user = os.getenv("WAZUH_API_USER", "wazuh-wui")
        api_password = os.getenv("WAZUH_API_PASSWORD", "")
        indexer_user = os.getenv("WAZUH_INDEXER_USER", "admin")
        indexer_password = os.getenv("WAZUH_INDEXER_PASSWORD", "")
        verify: bool | str = os.getenv("WAZUH_CA_BUNDLE") or False
        timeout = httpx.Timeout(8.0, connect=3.0)
        errors: list[str] = []
        agents: list[dict[str, Any]] = []
        alerts: list[Alert] = []
        with httpx.Client(verify=verify, timeout=timeout) as client:
            if api_password:
                try:
                    token_response = client.post(
                        f"{manager_url}/security/user/authenticate",
                        auth=(api_user, api_password),
                    )
                    token_response.raise_for_status()
                    token_data = token_response.json().get("data")
                    token = token_data.get("token") if isinstance(token_data, dict) else token_data
                    if isinstance(token, str) and token:
                        response = client.get(
                            f"{manager_url}/agents",
                            params={"limit": 500},
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        response.raise_for_status()
                        raw_agents = response.json().get("data", {}).get("affected_items", [])
                        agents = [
                            {
                                **agent,
                                "id": str(agent.get("id", "")),
                                "name": agent.get("name") or str(agent.get("id", "")),
                                "status": str(agent.get("status", "")).lower(),
                                "lastKeepAlive": agent.get("lastKeepAlive") or agent.get("last_keep_alive"),
                            }
                            for agent in raw_agents
                            if isinstance(agent, dict) and str(agent.get("status", "")).lower() == "active"
                        ]
                    else:
                        errors.append("Wazuh API authentication returned no token")
                except (httpx.HTTPError, ValueError) as exc:
                    errors.append(f"Wazuh Manager API unavailable: {exc}")
            else:
                errors.append("WAZUH_API_PASSWORD is not configured")

            if indexer_password:
                try:
                    query = {"size": 100, "sort": [{"timestamp": {"order": "desc"}}], "query": {"match_all": {}}}
                    response = client.post(
                        f"{indexer_url}/wazuh-alerts-*/_search",
                        auth=(indexer_user, indexer_password),
                        json=query,
                    )
                    response.raise_for_status()
                    for hit in response.json().get("hits", {}).get("hits", []):
                        source = hit.get("_source") if isinstance(hit.get("_source"), dict) else {}
                        source.setdefault("_id", hit.get("_id"))
                        alerts.append(self.normalize_alert(source))
                except (httpx.HTTPError, ValueError) as exc:
                    errors.append(f"Wazuh Indexer unavailable: {exc}")
            else:
                errors.append("WAZUH_INDEXER_PASSWORD is not configured")

        return {"agents": agents, "alerts": alerts, "errors": errors, "timestamp": datetime.now(timezone.utc)}

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return datetime.now(timezone.utc)


wazuh = WazuhService()
