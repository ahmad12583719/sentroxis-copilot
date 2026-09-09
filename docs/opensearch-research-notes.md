# OpenSearch telemetry research notes

## Current repository findings

- Sentroxis currently contains a FastAPI backend, React/Vite frontend, SQLite local authentication, a Wazuh ingestion adapter, and a Velociraptor ingestion adapter.
- `backend/ingestion/wazuh_service.py` already normalizes Wazuh alerts into the shared `Alert` model and reads live Wazuh Manager/Indexer data through server-side credentials.
- `backend/ingestion/velociraptor_service.py` normalizes approved read-only collection results into `Evidence`, including artifact name, collection timestamp, SHA-256 of the preview, and provenance.
- The Wazuh integration currently uses the Wazuh Manager API and Wazuh Indexer. OpenSearch should be introduced as a downstream analytics/training store rather than replacing the Wazuh Indexer in the first phase.
- Velociraptor collection results are not yet a durable event stream in the application; the design therefore needs an explicit export/adapter path rather than assuming every hunt result is automatically available as a stream.

## Verified external findings

1. Wazuh's official OpenSearch integration guide documents two supported patterns: forwarding from the Wazuh indexer using Logstash, and forwarding Wazuh server alerts using Logstash. It recommends TLS certificates for both sides, secure Logstash keystore credentials, explicit OpenSearch index mappings/templates, and a Wazuh template with a higher total-field limit because Wazuh documents can exceed the default field count.
   Source: https://documentation.wazuh.com/current/integrations-guide/opensearch/index.html

2. OpenSearch ingest pipelines are sequences of processors applied to documents as they are ingested. They are appropriate for deterministic normalization, field cleanup, timestamp parsing, redaction, and routing after the transport layer.
   Source: https://docs.opensearch.org/latest/ingest-pipelines/

3. OpenSearch Data Prepper is a pipeline service with pluggable sources, processors, buffers, and sinks. Its documentation lists HTTP, file, Kafka, OpenSearch, and other sources plus OpenSearch and file sinks, making it a viable transport/normalization layer for Velociraptor exports and application events.
   Source: https://docs.opensearch.org/latest/data-prepper/

4. OpenSearch provides users and roles through its Security plugin. The plan should use separate least-privilege identities for ingestion, dashboards/analysts, and training export rather than a shared administrator account.
   Source: https://docs.opensearch.org/latest/security/access-control/users-roles/

5. OpenSearch documentation includes vector search and RAG capabilities. This supports a later retrieval layer over curated security knowledge and sanitized event summaries, but raw telemetry should not be sent directly into model training without governance, redaction, labeling, and dataset review.
   Source: https://docs.opensearch.org/latest/vector-search/
   Source: https://docs.opensearch.org/latest/tutorials/gen-ai/rag/
