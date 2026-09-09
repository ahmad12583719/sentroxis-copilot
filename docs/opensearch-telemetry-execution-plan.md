# Sentroxis-Copilot OpenSearch Telemetry Architecture and Execution Plan

## 1. Executive recommendation

The proposed OpenSearch integration should be implemented as a **downstream security analytics and curated learning store**. Wazuh remains the detection and alerting system, Velociraptor remains the endpoint collection and response system, and Sentroxis remains the authenticated analyst workspace. OpenSearch becomes the central search, correlation, retention, visualization, and approved dataset layer for telemetry from both systems.

Do not replace the Wazuh Indexer in the first implementation phase. The safest path is:

> Wazuh agents → Wazuh Manager/Indexer → controlled export → OpenSearch
>
> Velociraptor clients → Velociraptor server/hunts → controlled result adapter → OpenSearch
>
> Sentroxis backend → normalized search/read APIs → analyst UI and approved AI retrieval

This separation preserves Wazuh’s existing operational behavior and avoids coupling the first release to vendor-specific index internals. Wazuh’s official integration guide supports Logstash-based forwarding from either the Wazuh Indexer or Wazuh server and recommends TLS, secure credential storage, and explicit mappings/templates.[1]

OpenSearch should **not** be treated as an automatic model-training sink. Raw endpoint telemetry may contain credentials, personal data, private keys, filenames, command lines, browser data, or attacker-controlled text. The initial target should be analyst search and retrieval-augmented investigation. A separate, reviewed `security-training-*` dataset may later be generated from sanitized, labeled, and approved records.

## 2. What the system does logically

Every source event passes through six logical stages:

| Stage | Purpose | Main controls |
|---|---|---|
| Collect | Receive Wazuh alerts, Wazuh agent/status metadata, Velociraptor hunt results, and approved evidence metadata. | Read-only source accounts, bounded queries, endpoint scope controls. |
| Buffer | Absorb bursts and allow retry without losing events. | Durable queue or Data Prepper buffer, event IDs, dead-letter handling. |
| Normalize | Convert vendor-specific payloads into a stable Sentroxis security-event envelope. | Typed schema, timestamp normalization, source tagging, field limits. |
| Sanitize | Remove or mask secrets and unnecessary personal data. | Allowlist fields, redaction rules, content-size limits, malware-safe parsing. |
| Index | Store operational telemetry and curated records in separate OpenSearch index families. | Index templates, lifecycle policies, aliases, least-privilege roles. |
| Use | Support dashboards, investigations, correlation, reports, and approved retrieval. | Backend authorization, server-side filters, audit logs, data freshness labels. |

The normalized envelope should include `event_id`, `source`, `event_type`, `event_time`, `ingested_at`, `tenant_id`, `device_id`, `device_name`, `platform`, `severity`, `rule_id`, `artifact_name`, `hunt_id`, `case_id`, `message`, `labels`, `raw_ref`, `schema_version`, and `redaction_status`. Keep the raw vendor payload in a restricted archive or encrypted object store; do not expose it to ordinary analysts or the model by default.

## 3. Physical architecture

The first deployment can run on one Linux host for development, but the components should remain separable:

| Component | Development placement | Production placement | Responsibility |
|---|---|---|---|
| Wazuh Manager/Indexer | Existing Wazuh deployment or optional local stack | Dedicated Wazuh nodes | Agent telemetry, rules, alerts, Wazuh-native retention. |
| Velociraptor server | Project-local server on port 8010 | Dedicated Velociraptor server with protected datastore | Endpoint hunts, client events, evidence collection. |
| Sentroxis backend | FastAPI process on port 8000 | Separate application service | Authenticated APIs, normalization adapters, OpenSearch reads, audit. |
| Data Prepper or Logstash | Local service for pilot | Dedicated ingestion tier | Buffering, routing, enrichment, retry, dead-letter processing. |
| OpenSearch | Single node for pilot | TLS-enabled cluster with replicas | Search, analytics, dashboards, curated retrieval index. |
| OpenSearch Dashboards | Optional pilot component | Restricted analyst-only interface | Low-level operational analytics; Sentroxis remains the primary UI. |
| Training export worker | Offline or isolated process | Separate controlled environment | Dataset review, redaction, labeling, export, evaluation. |

Use one-way outbound data flow from Wazuh and Velociraptor toward the ingestion tier. The ingestion tier may write to OpenSearch but must not receive arbitrary commands from telemetry. Sentroxis reads OpenSearch through a backend service account; browsers never receive OpenSearch administrator credentials.

## 4. Source pipelines

### 4.1 Wazuh pipeline

The recommended first Wazuh path is:

1. Wazuh agents send telemetry to the Wazuh Manager.
2. The Manager applies decoders and rules and writes alerts to the Wazuh Indexer or alert JSON output.
3. A dedicated Logstash or Data Prepper pipeline reads only the approved Wazuh alert indexes or alert file.
4. The pipeline adds `source=wazuh`, maps Wazuh fields into the normalized envelope, and applies a deterministic redaction policy.
5. The pipeline writes to `security-wazuh-alerts-YYYY.MM.dd` using the Wazuh-compatible template where Wazuh-native fields must be preserved.
6. A second normalized view is written to `security-events-YYYY.MM.dd` for cross-source search.
7. Sentroxis queries the normalized view through a least-privilege OpenSearch role.

For a first release, do not write back to the Wazuh Indexer and do not modify Wazuh rules, decoders, or agent configuration. The official Wazuh guide documents both indexer-based and server-alert-file-based Logstash patterns, so the deployment can select the path that matches the installed Wazuh topology.[1]

### 4.2 Velociraptor pipeline

Velociraptor needs a deliberate export adapter because a completed hunt is not automatically a generic OpenSearch event stream in the current Sentroxis code.

1. An analyst launches an approved collection through Sentroxis or the Velociraptor console.
2. Sentroxis records `hunt_id`, artifact names, device scope, analyst, case, launch time, and authorization decision.
3. A server-side adapter polls or receives the completed result through the authenticated Velociraptor API. It must use bounded pagination, a timeout, and a retry budget.
4. Each result row is mapped to the normalized envelope. The adapter records `source=velociraptor`, `event_type=artifact_result`, `artifact_name`, `client_id`, `hunt_id`, and `collection_method`.
5. Evidence files are stored separately. OpenSearch receives metadata, hashes, small safe previews, and evidence references—not unrestricted binary contents.
6. The normalized result is sent through the same sanitization and indexing pipeline as Wazuh data.
7. OpenSearch stores operational results in `security-velociraptor-results-YYYY.MM.dd` and cross-source summaries in `security-events-YYYY.MM.dd`.

For high-volume client monitoring, use an event-specific stream and sampling policy rather than indexing every raw event forever. For one-time forensic hunts, retain complete result metadata and a reference to the immutable evidence package.

### 4.3 Sentroxis audit and workflow pipeline

Sentroxis itself should emit audit events for login, endpoint package downloads, hunt preview, hunt launch, cancellation, evidence download, configuration changes, and OpenSearch searches. These records should go to `security-audit-YYYY.MM.dd` and should never include passwords, API keys, private key material, raw `api.config.yaml`, or session tokens.

## 5. OpenSearch index strategy

Use aliases and templates so application code does not hard-code daily index names.

| Index family | Contents | Retention suggestion | Access |
|---|---|---:|---|
| `security-events-*` | Normalized cross-source events used by Sentroxis search and correlation. | 90 days hot, then archive. | Analyst read, ingestion write. |
| `security-wazuh-alerts-*` | Wazuh alerts with source fields preserved. | Match Wazuh policy. | Analyst read, ingestion write. |
| `security-velociraptor-results-*` | Artifact rows and collection metadata. | 90 days hot; evidence separately retained. | Analyst read, ingestion write. |
| `security-evidence-meta-*` | Evidence hashes, references, collection provenance, and small approved previews. | Case/legal policy. | Analyst read; evidence service write. |
| `security-audit-*` | Sentroxis and ingestion audit records. | 1 year or policy. | Security-admin read, audit writer. |
| `security-training-candidates-*` | Sanitized, labeled candidate records awaiting review. | Until review. | Training-reviewer read/write. |
| `security-training-approved-*` | Approved examples for evaluation or model fine-tuning. | Versioned, immutable. | Training pipeline read-only. |

Create explicit templates for timestamps, keyword identifiers, IP addresses, numeric severity, bounded text, and arrays. Set a deliberate total-field limit. Wazuh’s guide notes that Wazuh documents can exceed OpenSearch’s default field limit and provides a template with a higher limit.[1] Do not solve mapping explosions by endlessly increasing the limit; first remove unbounded raw fields and map high-cardinality vendor payloads as restricted JSON or flattened content.

## 6. Security and privacy model

Create separate identities:

| Identity | Permissions |
|---|---|
| `ingest-wazuh` | Write only to Wazuh and normalized event aliases; no search outside health checks. |
| `ingest-velociraptor` | Write only to Velociraptor result and normalized event aliases. |
| `sentroxis-reader` | Read approved aliases with server-side time/device/case filters. |
| `sentroxis-auditor` | Append audit records; read audit data only for authorized administrators. |
| `training-reviewer` | Read candidate data, write labels and approval status; no raw evidence access by default. |
| `training-exporter` | Read only approved, versioned training aliases. |
| `opensearch-admin` | Break-glass administration, MFA, separate from application credentials. |

Use TLS with certificate verification between every service. Store credentials in environment-level secret management or a service keystore, never in Git, ordinary logs, browser storage, URLs, or prompts. OpenSearch ingest pipelines can perform deterministic processing, while Data Prepper provides configurable sources, processors, buffers, and sinks.[2] [3]

Treat event text as untrusted. Escape it in the UI, cap document and preview sizes, redact secrets before indexing, and never allow an event field to become an executable query, shell command, VQL statement, or model instruction. Add a `redaction_status` and `source_trust` field so downstream consumers know that telemetry is evidence, not trusted instructions.

## 7. Agent-training and AI boundary

The phrase “agents training” should be separated into three use cases:

| Use case | Recommended OpenSearch role | Policy |
|---|---|---|
| Analyst search | Full-text, filters, aggregations, timelines. | Use normalized operational indexes. |
| AI retrieval/RAG | Retrieve relevant, sanitized alert/evidence summaries. | Preserve source, timestamp, case, and authorization filters in every retrieval. OpenSearch supports vector and RAG patterns, but retrieval must remain permission-aware.[4] [5] |
| Model training/fine-tuning | Curated labeled examples. | Never train directly on raw Wazuh/Velociraptor indexes. Require redaction, deduplication, malware-content handling, analyst labels, approval, dataset versioning, and evaluation. |

A safe training record contains a stable example ID, sanitized event summary, source type, attack-technique label if validated, analyst rationale, evidence references, label confidence, dataset version, and reviewer identity. It must not contain passwords, tokens, private keys, unrestricted command output, raw file contents, or unreviewed attacker instructions.

The first AI milestone should be **retrieval-augmented analyst assistance**, not autonomous model training. The model may summarize or propose a hypothesis, but the Sentroxis policy layer and authorized analyst remain responsible for collection or response actions.

## 8. Step-by-step execution plan

### Phase 0 — Decide scope and baseline

Document the Wazuh version, Wazuh Indexer topology, Velociraptor version, expected events per second, retention, endpoint count, network boundaries, and whether OpenSearch is local or remote. Define the first supported event types: Wazuh alerts, Velociraptor artifact results, hunt metadata, and Sentroxis audit events.

### Phase 1 — Deploy a safe OpenSearch pilot

Run a single-node OpenSearch and optional Dashboards instance in an isolated development environment. Enable TLS and the Security plugin. Create the service roles above, health checks, a snapshot location, and test credentials. Do not expose OpenSearch directly to the public Internet.

### Phase 2 — Define schemas and templates

Create JSON schema/Pydantic models for the normalized envelope. Create index templates and aliases for the seven index families. Add lifecycle policies, a dead-letter index, field limits, and test fixtures containing benign synthetic Wazuh and Velociraptor data.

### Phase 3 — Implement Wazuh forwarding

Choose either Wazuh Indexer-to-OpenSearch or Wazuh server alert-file forwarding. Install and configure Logstash or Data Prepper on a dedicated ingestion host. Store credentials in its keystore. Validate TLS, templates, backfill behavior, duplicate handling, retry, dead-letter routing, and alert freshness. Keep existing Wazuh pages and Wazuh business logic unchanged.

### Phase 4 — Implement Velociraptor export

Add a dedicated backend worker or controlled CLI job that retrieves completed hunt results through the Velociraptor API, normalizes rows, redacts sensitive values, computes evidence references, and writes through the ingestion pipeline. Add idempotency using a key such as `source + hunt_id + client_id + artifact + result_hash`.

### Phase 5 — Add Sentroxis search APIs

Expose only typed, bounded backend endpoints for search, timeline, device history, hunt results, evidence metadata, and audit records. Apply tenant/device/case authorization server-side. Add pagination, time bounds, maximum result counts, query timeouts, stale-request cancellation, and data-freshness indicators.

### Phase 6 — Add analyst dashboards

Build dashboards for unified events, Wazuh alerts, Velociraptor evidence, endpoint timelines, ingestion health, dead-letter events, and audit activity. Keep OpenSearch credentials server-side; the React client calls Sentroxis APIs. Display source, freshness, provenance, and partial-failure states.

### Phase 7 — Add curated AI retrieval

Create a sanitized retrieval index from approved summaries. Start with lexical filtering and then add embeddings/vector fields if evaluation shows value. Enforce the same case, tenant, and device authorization filters during retrieval. Record the retrieved document IDs and prompt context for auditability.

### Phase 8 — Establish training governance

Create a review queue for candidate training examples. Require analyst labels, reviewer approval, redaction checks, duplicate detection, dataset versioning, train/test separation, poisoning review, and offline evaluation. Publish only immutable approved dataset aliases to training jobs.

### Phase 9 — Operate and scale

Monitor ingestion lag, OpenSearch cluster health, rejected documents, mapping errors, dead-letter volume, index growth, query latency, Velociraptor export failures, and Wazuh forwarding freshness. Add snapshots, restore tests, rollover policies, shard sizing, and capacity alerts before production scale-up.

## 9. Validation and acceptance criteria

The integration is ready for pilot when a synthetic Wazuh alert, a synthetic Velociraptor result, and a Sentroxis audit event each travel through the pipeline, appear in the correct index, can be queried through the backend, and retain source/timestamp/provenance fields.

Security tests must prove that an ingestion identity cannot read analyst data, a reader cannot write, a training exporter cannot access raw evidence, untrusted event text is escaped and redacted, unauthorized devices/cases return no data, expired sessions fail, invalid timestamps and oversized documents are rejected, duplicate events are idempotent, and ingestion failures go to a dead-letter path.

Operational tests must prove that OpenSearch restart does not lose buffered events, Wazuh forwarding catches up after a short outage, Velociraptor export retries without duplicating results, index rollover works, snapshots restore, and Sentroxis remains usable when OpenSearch is temporarily unavailable.

## 10. Recommended first implementation slice

The lowest-risk first slice is **Wazuh alerts + Velociraptor hunt metadata/results + Sentroxis audit events into normalized OpenSearch indexes**, with no direct model training. Once search and retention are stable, add sanitized RAG retrieval. Only after the organization has labels and review controls should `security-training-approved-*` be created.

## References

[1]: https://documentation.wazuh.com/current/integrations-guide/opensearch/index.html "Wazuh OpenSearch integration guide"
[2]: https://docs.opensearch.org/latest/ingest-pipelines/ "OpenSearch ingest pipelines"
[3]: https://docs.opensearch.org/latest/data-prepper/ "OpenSearch Data Prepper"
[4]: https://docs.opensearch.org/latest/vector-search/ "OpenSearch vector search"
[5]: https://docs.opensearch.org/latest/tutorials/gen-ai/rag/ "OpenSearch retrieval-augmented generation documentation"
[6]: https://docs.opensearch.org/latest/security/access-control/users-roles/ "OpenSearch users and roles"
