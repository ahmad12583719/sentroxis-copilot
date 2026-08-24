from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.core.mitre_engine import enrich_alert, severity_from_payload
from backend.core.models import Alert, Source


class WazuhService:
    """Read-only normalizer for Wazuh alert payloads.

    Network calls are intentionally kept out of the demo service. A production
    client should use separate Server API and Indexer credentials, TLS verification,
    short timeouts, bounded pagination, and audit-linked requests.
    """

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

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return datetime.now(timezone.utc)
