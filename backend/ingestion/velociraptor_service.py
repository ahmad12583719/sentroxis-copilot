from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from backend.core.models import Alert, Evidence, Source


class VelociraptorService:
    """Normalize approved, read-only collection results without executing VQL."""

    def normalize_evidence(self, alert: Alert, payload: dict[str, Any]) -> Evidence:
        content = str(payload.get("content") or payload.get("result") or "")[:2000]
        digest = sha256(content.encode("utf-8")).hexdigest() if content else None
        return Evidence(
            id=f"evidence-{alert.id}",
            alert_id=alert.id,
            source=Source.velociraptor,
            collected_at=self._timestamp(payload.get("collected_at")),
            collection_method=str(payload.get("artifact") or "approved-read-only-collection")[:160],
            sha256=digest,
            content_preview=content,
            provenance="normalized-demo-collection",
        )

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return datetime.now(timezone.utc)
