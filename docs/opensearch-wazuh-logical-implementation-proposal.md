# Sentroxis OpenSearch/Wazuh Logical Implementation Proposal

**Project:** Sentroxis Copilot  
**Purpose:** Instructor and team review before implementation  
**Development branch:** `feature/opensearch-wazuh-integration`  
**Status:** Proposed; no runtime implementation authorized until review is complete  
**Prepared by:** Manus AI  
**Date:** 2026-09-11

## 1. Executive decision

The proposed integration is technically feasible if it is implemented as a staged, downstream analytics capability rather than as a replacement for the existing Wazuh deployment.

The recommended first implementation is:

```text
Wazuh agents
    ↓
Wazuh Manager + existing Wazuh Indexer
    ↓
controlled export
    ↓
Logstash transport and buffer
    ↓
normalization and redaction
    ↓
OpenSearch ingest pipeline
    ↓
Sentroxis Analytics OpenSearch
    ↓
FastAPI authorization and query APIs
    ↓
Sentroxis analyst workspace
```

The first release should store and search Wazuh alerts and selected endpoint context. It should not train a model directly on raw telemetry. Future training data must be generated through a separate preprocessing, labeling, review, and approval workflow.

This design preserves the current Wazuh operational path and creates a reversible integration boundary. If the analytics path fails, the existing Wazuh Manager, Wazuh Indexer, and dashboard remain operational.

## 2. Problem and scope

Sentroxis currently integrates with Wazuh and Velociraptor as an authenticated analyst workspace. The next capability is to create a controlled analytics store that can combine Wazuh alerts, Velociraptor results, and Sentroxis audit events for search, correlation, timelines, and future model-data preparation.

The scope of this proposal is the logical implementation method for Wazuh-to-OpenSearch integration and its future training-data boundary. It covers data selection, transport, processing, storage, security, reliability, validation, and staged delivery.

The proposal does not authorize automatic model training, autonomous incident response, replacement of the Wazuh Indexer, or production deployment without target-system testing.

## 3. Feasibility analysis

| Capability | Feasibility | Assessment |
|---|---:|---|
| Forward Wazuh alerts to a separate OpenSearch cluster | High | Wazuh documents Logstash-based forwarding from the Wazuh Indexer or Wazuh server alerts. |
| Normalize Wazuh data into a Sentroxis schema | High | Logstash filters, a controlled preprocessing service, and OpenSearch ingest pipelines can implement this. |
| Combine Wazuh and Velociraptor data | Medium to high | It requires a common event envelope and a deliberate Velociraptor export adapter. |
| Query OpenSearch through Sentroxis | High | FastAPI can expose bounded, authorized search and timeline APIs. |
| Train anomaly models from extracted features | Medium to high | This is feasible after enough representative and correctly scoped data exists. |
| Fine-tune a language model on raw Wazuh JSON | Low value and high risk | Raw alerts are noisy, sensitive, attacker-influenced, and usually weakly labeled. |
| Run every component and model training simultaneously on project hardware | Not recommended | Wazuh, OpenSearch, Velociraptor, Ollama, Logstash, and training workloads can compete for limited memory and CPU. |

The technically feasible path is therefore incremental: first reliable data movement and search, then preprocessing and feature extraction, and only later reviewed model-data preparation.

## 4. OpenSearch role separation

The project must distinguish two systems that both use OpenSearch technology:

| System | Role |
|---|---|
| **Wazuh Indexer** | Existing Wazuh storage and operational detection path. It remains in place during the first phase. |
| **Sentroxis Analytics OpenSearch** | New downstream store for normalized security events, correlation, authorized search, and curated data preparation. |

The first implementation must not write back into the Wazuh Indexer, modify Wazuh rules unnecessarily, or make the Wazuh Indexer depend on the new analytics cluster.

## 5. Data collection scope

### 5.1 Primary data: Wazuh alerts

The first source is the Wazuh alert stream from `wazuh-alerts-*` or the Wazuh alert JSON output. An alert is a processed detection record produced after Wazuh decodes an event and applies a rule. It is not equivalent to completely raw endpoint telemetry.

Important fields include event identity, event time, Wazuh rule ID, rule level, rule description, decoder name, rule groups, MITRE context when present, agent identity, operating system, IP addresses, authentication details, process details, file-integrity details, vulnerability information, and source provenance.

Wazuh severity is not ground truth. A high-severity alert can be benign, and a low-severity alert can be useful evidence. Training labels must be validated separately.

### 5.2 Selected endpoint context

Collect agent status and inventory periodically rather than duplicating full snapshots in every alert. Useful context includes operating system, installed packages, running processes where approved, network interfaces, open ports, Wazuh agent version, endpoint group, and last-seen time.

### 5.3 Selective Wazuh modules

The first pilot should enable only modules relevant to the evaluation objective:

| Module | Initial value |
|---|---|
| Windows Event Channels | Authentication, PowerShell, process, and system activity. |
| Linux auditd and syslog | Process execution, privilege use, authentication, and system activity. |
| Syscheck/FIM | File creation, modification, deletion, and hash changes. |
| Syscollector | Periodic packages, processes, ports, and host inventory. |
| Vulnerability detection | CVE, package, severity, and exposure context. |
| Firewall and network events | Controlled network-behavior features. |
| Rootcheck | Suspicious configuration and rootkit findings. |

The project should not begin by collecting every available endpoint event. Event rate, document size, storage growth, OpenSearch heap use, and query latency must be measured first.

### 5.4 Data that must be excluded or restricted

Passwords, tokens, cookies, private keys, unrestricted command output, complete memory dumps, unrestricted binary contents, unnecessary personal data, and raw attacker-controlled instructions must not enter ordinary operational or training indexes. A restricted archive may preserve original records when required for reproducibility, but training jobs must not access it by default.

## 6. Integration methods considered

### 6.1 Method A: Wazuh Indexer to Logstash to Analytics OpenSearch

```text
Wazuh Indexer → Logstash → Sentroxis Analytics OpenSearch
```

This is the recommended first method. It follows the official Wazuh integration pattern, preserves the existing Wazuh path, supports TLS and secure credentials, and provides a mature transport/filtering boundary.

Its costs are an additional service, plugin compatibility work, certificate management, and careful handling of checkpoints, retries, and duplicates.

### 6.2 Method B: Wazuh alert files to Logstash to Analytics OpenSearch

```text
Wazuh Manager alert JSON → Logstash → Analytics OpenSearch
```

This is a valid fallback when Indexer export is impractical. It requires reliable file-offset handling, rotation handling, restart recovery, and duplicate prevention. Historical backfill is more difficult than with an indexed source.

### 6.3 Method C: Custom Sentroxis worker

```text
Sentroxis worker → Wazuh API or Indexer → Analytics OpenSearch
```

This provides application-level control but requires custom implementation of buffering, checkpoints, retries, backpressure, idempotency, replay, bulk writes, and monitoring. It is better suited to Sentroxis audit events, Velociraptor exports, and training-candidate generation than to the first Wazuh transport.

### 6.4 Decision

Use **Method A** first. Select Method B only when the installed Wazuh topology prevents reliable Indexer export. Keep Method C for application-specific data flows.

## 7. Logical pipeline design

### 7.1 Transport pipeline

```text
Wazuh source
    ↓
Logstash input
    ↓
bounded query or file-offset handling
    ↓
retry and buffer
    ↓
restricted quarantine index
```

The transport must use TLS with certificate verification, dedicated identities, protected credentials, bounded source reads, retries with backoff, and dead-letter routing.

### 7.2 Normalization pipeline

```text
quarantine record
    ↓
field allowlist
    ↓
timestamp normalization
    ↓
Wazuh field mapping
    ↓
secret removal and size limits
    ↓
provenance and schema version
    ↓
idempotency key
    ↓
OpenSearch ingest pipeline
```

Logstash or a controlled preprocessing component should perform complex operations. The OpenSearch ingest pipeline should perform simple deterministic final transformations such as date parsing, type conversion, field renaming, default values, controlled routing, and failure handling.

### 7.3 Operational indexes

```text
security-wazuh-alerts-*
security-events-*
security-wazuh-context-*
security-audit-*
security-dead-letter-*
```

`security-wazuh-alerts-*` preserves Wazuh-specific details. `security-events-*` provides the common cross-source envelope. Context, audit, and failure records remain separately governed.

### 7.4 Future training pipeline

```text
operational records
    ↓
feature extraction
    ↓
redaction and malware-content checks
    ↓
training candidates
    ↓
analyst review
    ↓
immutable approved dataset
    ↓
offline evaluation or training
```

The approved dataset is not created automatically from alerts. It requires labels, provenance, reviewer identity, dataset versioning, deduplication, train/test separation, and poisoning review.

## 8. Normalized event contract

Every source record should be converted to a stable Sentroxis envelope. The minimum contract is:

```text
event_id
source
event_type
event_time
ingested_at
tenant_id
device_id
device_name
platform
severity
rule_id
artifact_name
hunt_id
case_id
message
labels
raw_ref
schema_version
redaction_status
source_trust
```

Fields that do not apply remain absent or null. The schema must not invent fake values to make unlike sources appear identical.

The contract must also define maximum lengths, accepted timestamp formats, controlled values, idempotency behavior, and the treatment of malformed or untrusted input.

## 9. Storage and lifecycle design

| Index family | Purpose | Access |
|---|---|---|
| `security-wazuh-quarantine-*` | Restricted debugging and short-term replay | Ingestion administrator and preprocessing worker. |
| `security-wazuh-alerts-*` | Wazuh-specific alert investigation | Authorized analyst read; ingestion write. |
| `security-events-*` | Normalized cross-source search and correlation | Authorized analyst read; ingestion write. |
| `security-wazuh-context-*` | Agent status and inventory snapshots | Authorized analyst and preprocessing read. |
| `security-audit-*` | Application and pipeline audit trail | Authorized security administrator read; audit writer append. |
| `security-dead-letter-*` | Rejected documents and failed processing | Authorized operator only. |
| `security-training-candidates-*` | Sanitized records awaiting review | Training reviewer. |
| `security-training-approved-*` | Immutable approved dataset | Training exporter read-only. |

The SRS specifies seven-day rollover and a maximum OpenSearch heap of approximately 2 GB. The final retention policy must be confirmed against available disk, event rate, and training needs. If operational indexes retain only seven days, any longer-term training source must be an approved archive or dataset, not an assumption that deleted operational records remain available.

## 10. Security model

Separate identities are required for ingestion, analyst reads, auditing, training review, and training export. Browsers must never receive OpenSearch administrator credentials or arbitrary OpenSearch query DSL execution.

All backend searches must enforce authentication, device or case authorization, bounded time ranges, pagination, maximum result counts, query timeouts, and audit logging. Event text must be escaped in the UI and treated as evidence rather than executable instructions.

TLS and certificate verification must be enabled between the export service and both OpenSearch systems. Credentials belong in protected environment configuration or a service keystore. They must not be committed to Git, URLs, browser storage, prompts, or ordinary logs.

## 11. Hardware and deployment feasibility

The SRS describes constrained CPU, memory, and storage. Running Wazuh, the Wazuh Indexer, Analytics OpenSearch, Logstash, Velociraptor, FastAPI, React, Ollama, and model training simultaneously may create resource contention.

The recommended deployment separates runtime and training workloads:

| Mode | Workloads |
|---|---|
| Runtime | Wazuh, Wazuh Indexer, Logstash, Analytics OpenSearch, Sentroxis, and Velociraptor. |
| Offline training | Feature extraction, candidate creation, review export, model training, and evaluation. |

The pilot must measure RAM, JVM heap, CPU, disk growth, ingestion rate, rejected documents, and query latency before increasing collection scope.

## 12. Phased implementation and gates

| Phase | Outcome | Gate |
|---:|---|---|
| 0 | Baseline and scope lock | Versions, topology, export source, retention, event scope, and prerequisites recorded. |
| 1 | Contracts and synthetic fixtures | Records validate, normalize, redact, deduplicate, and reject deterministically without live infrastructure. |
| 2 | Analytics OpenSearch foundation | TLS, roles, templates, aliases, lifecycle, ingest pipeline, health checks, and snapshot restore pass. |
| 3 | Wazuh export transport | Synthetic and live test alerts reach quarantine through Logstash without changing Wazuh behavior. |
| 4 | Normalize and sanitize | Safe, typed, bounded records reach operational indexes with provenance and stable mappings. |
| 5 | Reliability and operations | Restart, outage, retry, duplicate, dead-letter, and replay tests pass. |
| 6 | Backend query APIs | Authorized, bounded Sentroxis endpoints provide search, timelines, health, and audit data. |
| 7 | Analyst views | UI supports search, timelines, provenance, freshness, partial failure, and safe rendering. |
| 8 | Training candidates | Reproducible features and sanitized candidate records exist with source traceability. |
| 9 | Approved datasets | Reviewed, immutable, versioned datasets and offline evaluation pass. |
| 10 | Merge review | Full evidence package, target validation, secret scan, documentation, and final diff review pass. |

No phase should be treated as complete based only on code existence. Each gate requires test evidence.

## 13. Validation strategy

### 13.1 Synthetic validation

Synthetic Wazuh alerts, agent-context records, and Sentroxis audit events must pass through the contract and OpenSearch pipeline before live telemetry is connected.

### 13.2 Security validation

Tests must prove that ingestion identities cannot read analyst data, readers cannot write, training exporters cannot read raw or quarantine data, unauthorized device or case queries return no data, expired sessions fail, secrets are redacted, and invalid or oversized documents are rejected.

### 13.3 Reliability validation

Tests must cover OpenSearch restart, Logstash restart, Wazuh source outage, duplicate delivery, malformed documents, buffer pressure, dead-letter replay, index rollover, snapshot restoration, and temporary OpenSearch unavailability.

### 13.4 Existing project validation

The existing project checks remain required:

```bash
bash -n wazuh_installation.sh startup.sh start.sh
cd frontend
npm run lint
npm test -- --run
npm run build
```

Target-system Docker, TLS, Wazuh, and persistent-volume checks must run on the real deployment machine because they cannot be fully reproduced in the development sandbox.

## 14. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Excessive event volume | Begin with an allowlist and measure rate, size, storage, heap, and latency. |
| Weak training labels | Treat Wazuh severity as a feature or weak label; require analyst confirmation. |
| Memory contention | Keep training offline and constrain OpenSearch heap; expand only after measurements. |
| Duplicate events | Use deterministic document identifiers and idempotency keys. |
| Secret or PII leakage | Apply allowlists, redaction, length limits, restricted quarantine, and review. |
| Mapping explosion | Use explicit templates and bounded fields. |
| Wazuh disruption | Keep Analytics OpenSearch downstream and read-only with respect to Wazuh. |
| Untrusted event text | Escape it in the UI and prohibit it from becoming a query, command, VQL statement, or model instruction. |

## 15. Instructor/team decisions requested

Before implementation begins, the team should confirm:

1. The separate Analytics OpenSearch role.
2. The Wazuh Indexer-to-Logstash export method.
3. The development and target deployment topology.
4. Initial event types and Wazuh modules.
5. Retention and rollover policy.
6. Resource limits and training execution location.
7. Whether automatic anomaly-to-DFIR triggering is excluded from the first integration.
8. The acceptance evidence required for each phase.

## 16. Recommendation

Approve the project to begin with Phase 0 and Phase 1 only. Phase 0 records the baseline and resolves design decisions. Phase 1 creates the normalized event contract and synthetic fixtures. These phases are low risk because they do not alter the existing Wazuh runtime or connect live telemetry.

After Phase 1 passes, proceed to the Analytics OpenSearch foundation. Connect live Wazuh data only after secure roles, templates, TLS, and failure handling have been tested.

## References

[1]: https://documentation.wazuh.com/current/integrations-guide/opensearch/index.html "Wazuh OpenSearch integration guide"
[2]: https://docs.opensearch.org/latest/data-prepper/ "OpenSearch Data Prepper documentation"
[3]: https://docs.opensearch.org/latest/ingest-pipelines/ "OpenSearch ingest pipelines documentation"
[4]: ../docs/opensearch-wazuh-phased-implementation-plan.md "Sentroxis OpenSearch/Wazuh phased implementation plan"
[5]: ../docs/wazuh-opensearch-training-data-guide.md "Wazuh logs for Sentroxis OpenSearch and future model training"
[6]: ../README.md "Sentroxis Copilot repository README"

## Document control

| Item | Value |
|---|---|
| Current status | Proposed for instructor/team review |
| Runtime code changes | None authorized by this document |
| Implementation branch | `feature/opensearch-wazuh-integration` |
| Merge condition | All required phase gates and target-system tests pass |
