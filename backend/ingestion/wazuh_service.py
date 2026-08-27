from __future__ import annotations

import os
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

    def live_overview(self) -> dict[str, Any]:
        """Return bounded live Manager agents and Indexer alerts.

        The caller supplies credentials through the process environment. TLS
        verification is enabled when WAZUH_CA_BUNDLE is set; local self-signed
        MVP deployments explicitly default to disabled verification.
        """
        manager_url = os.getenv("WAZUH_MANAGER_API_URL", "https://127.0.0.1:55000").rstrip("/")
        indexer_url = os.getenv("WAZUH_INDEXER_URL", "https://127.0.0.1:9200").rstrip("/")
        api_user = os.getenv("WAZUH_API_USER", "wazuh")
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
                            params={"limit": 500, "select": "id,name,ip,status,os,version,lastKeepAlive"},
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        response.raise_for_status()
                        agents = response.json().get("data", {}).get("affected_items", [])
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
