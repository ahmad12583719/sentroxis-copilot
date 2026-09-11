# Wazuh Logs for Sentroxis OpenSearch and Future Model Training

## Short recommendation

For this project, collect **Wazuh alerts as the primary training input**, together with the endpoint metadata and security context needed to interpret those alerts. Do not send every raw operating-system log directly into the training dataset.

Use this architecture:

> **Wazuh agents → Wazuh Manager and Wazuh Indexer → Logstash → restricted raw/quarantine OpenSearch indexes → normalization and redaction → operational security indexes → reviewed training candidates → approved training dataset**

Use **Logstash** as the first transport and buffering layer because the official Wazuh integration documents a Wazuh Indexer-to-OpenSearch Logstash path and a Wazuh server alert-file-to-OpenSearch Logstash path. Use **OpenSearch ingest pipelines** for simple deterministic transformations after transport. Use the Sentroxis backend for authorization, audit, Velociraptor export, and typed search APIs. Use Data Prepper only if the team later decides that its buffering and processing features are a better fit than Logstash for this deployment.

## 1. First understand the different meanings of “raw logs”

There are three different data levels. They must not be mixed.

| Level | Example | Use in this project |
|---|---|---|
| Original endpoint telemetry | Windows Event Log, Linux auditd, syslog, process event, network connection, file change | Useful for deep investigation and future feature engineering, but potentially very large and sensitive. Keep restricted or archive selectively. |
| Wazuh alert document | A JSON alert produced after Wazuh decoding, rule matching, and severity assignment | The primary operational and initial model-training input. It already contains detection context such as rule, level, agent, decoder, and source event fields. |
| Curated training record | Sanitized alert summary plus validated label, features, analyst rationale, provenance, and dataset version | The only data that should be used for model training or fine-tuning. It must be reviewed and approved. |

A Wazuh alert is not the same as completely raw endpoint data. It is a processed detection record. It normally provides the best starting point because it combines the source event with Wazuh’s decoder and rule context.

## 2. Wazuh data that should be collected

### 2.1 Required first-phase data: Wazuh alerts

Collect the Wazuh alert stream from `wazuh-alerts-*` or the Wazuh alert JSON output. These records should be written to a dedicated OpenSearch family such as `security-wazuh-alerts-*`.

Keep the following fields wherever they are present:

| Field group | Examples | Why it matters for training |
|---|---|---|
| Event identity | Alert ID, event ID, hash, `@timestamp`, event time | Deduplication, ordering, replay, and time-window features. |
| Detection context | Rule ID, rule description, rule level, groups, decoder name, MITRE technique/tactic | Detection labels, weak supervision, explainability, and evaluation. |
| Agent context | Agent ID, agent name, operating system, version, IP, manager name | Device-level behavior and environment features. |
| Source context | Source IP, destination IP, source port, destination port, protocol, direction | Network-behavior features and incident correlation. |
| Authentication context | User name, logon type, authentication result, source address | Account-abuse and lateral-movement features. |
| Process context | Process name, executable path, parent process, command-line metadata, hash | Execution and malware-behavior features. |
| File-integrity context | File path, operation, hash, user, permission change | Persistence, tampering, and unauthorized-change features. |
| Vulnerability context | CVE, package, severity, affected agent, status | Vulnerability prioritization and endpoint risk features. |
| Cloud or application context | Cloud service, URL, HTTP status, application action, API operation | Only when those integrations are enabled and the data is authorized. |
| Provenance | Source system, collector, schema version, ingestion time, redaction status | Trust, reproducibility, and auditability. |

Do not assume every alert contains every field. The normalized schema must allow optional fields and must record which source produced each value.

### 2.2 Recommended endpoint context: agent inventory and status

Collect Wazuh agent status and inventory at a lower frequency than alerts. This data helps models distinguish normal behavior from abnormal behavior.

Recommended context includes:

1. Agent online or disconnected status.
2. Operating system and version.
3. Installed packages and versions.
4. Running processes, if enabled and approved.
5. Network interfaces and stable host metadata.
6. Hardware or host role labels where available.
7. Wazuh agent version and policy group.
8. Last-seen time and collection freshness.

This data should be stored separately from alerts or clearly typed as `event_type=agent_inventory` and `event_type=agent_status`. Do not repeatedly duplicate the full inventory inside every alert document.

### 2.3 High-value security telemetry to enable selectively

Enable these Wazuh modules only when they are relevant to the project’s detection and training goals:

| Wazuh capability | Data value | Recommendation |
|---|---|---|
| Windows Event Channel collection | Authentication, process, PowerShell, service, and system events | High priority for the Windows evaluation environment. Collect selected channels rather than every channel. |
| Linux auditd and syslog | Process execution, privilege use, authentication, and system activity | High priority for Linux evaluation environments. Use allowlisted event categories. |
| Syscheck / File Integrity Monitoring | File creation, modification, deletion, and hash changes | High value for persistence and tampering models. Control path scope to avoid excessive volume. |
| Syscollector | Packages, processes, ports, hardware, and operating-system inventory | High value as endpoint context. Snapshot periodically instead of repeating it per alert. |
| Rootcheck | Rootkit and suspicious configuration findings | Useful as a detection feature, but preserve the rule and finding provenance. |
| Vulnerability detection | CVE, package, severity, and affected endpoint | Useful for risk scoring, but do not treat vulnerability presence alone as proof of compromise. |
| Command monitoring | Output from selected commands | Use sparingly. It can expose secrets and attacker-controlled text. Never collect unrestricted command output by default. |
| Firewall and network events | Connections, blocks, and network behavior | High value when volume is controlled and fields are redacted. |
| Syslog and application logs | Web, database, authentication, and service behavior | Collect selected sources with an explicit allowlist. |
| Cloud or third-party integrations | Identity, API, and cloud control-plane activity | Add only when the project has a defined source, authorization, and schema. |

The first pilot should use Wazuh alerts plus a limited set of agent status, inventory, authentication, process, network, and file-integrity context. It should not begin by collecting every available module.

## 3. What should not be collected into ordinary OpenSearch indexes

The following data should be excluded, redacted, or placed in a restricted evidence/archive store:

1. Passwords, API keys, access tokens, cookies, session identifiers, and private keys.
2. Complete browser history or browser profile contents unless there is an approved forensic case.
3. Full memory dumps or unrestricted binary files.
4. Complete file contents when a hash, metadata, or safe preview is sufficient.
5. Unbounded command output, shell history, or environment variables.
6. Personal data that is not required for the detection or training objective.
7. Raw attacker-controlled text passed directly into an AI prompt.
8. High-cardinality nested vendor payloads that can cause mapping explosions.
9. Duplicate copies of the same inventory snapshot in every event.
10. Data from devices or cases for which the requesting analyst is not authorized.

The system may retain a restricted original record for forensic reproducibility, but that record must not be visible to ordinary analysts or directly available to training jobs.

## 4. Recommended OpenSearch index families

Use separate index families instead of putting every version of a record into one index.

| Index family | Contents | Training access |
|---|---|---|
| `security-wazuh-alerts-*` | Wazuh alert documents with important Wazuh fields preserved | Not directly used for training; read by authorized analysts and preprocessing jobs. |
| `security-events-*` | Normalized cross-source event envelope | Used for search, correlation, and feature extraction. |
| `security-wazuh-context-*` | Agent status and periodic inventory snapshots | Used as time-aware context features. |
| `security-audit-*` | Sentroxis actions and pipeline audit events | Used for governance and reproducibility, not as model behavior data. |
| `security-dead-letter-*` | Documents rejected by transport, validation, or sanitization | Never used for training until manually corrected and reprocessed. |
| `security-training-candidates-*` | Sanitized records awaiting labeling and review | Training reviewers can read and update review status. |
| `security-training-approved-*` | Immutable, versioned approved examples | Training export jobs read only this family. |

A restricted raw archive may be added if the project genuinely needs original Wazuh payloads for later feature engineering. It should have a separate role, retention policy, encryption policy, and access audit. It should not be the default source for RAG or model training.

## 5. How the Wazuh data should be sent to OpenSearch

### Step 1: Wazuh produces the source records

Wazuh agents send telemetry to the Wazuh Manager. The Manager decodes events and applies rules. The resulting alerts are stored by the Wazuh Indexer and/or written to the alert JSON output.

At this stage, Wazuh remains responsible for detection logic. Do not change Wazuh rules or decoders merely to support the new analytics store.

### Step 2: Select the first export method

For the current Sentroxis project, select one of these methods:

| Method | Flow | Advantages | Limitations |
|---|---|---|---|
| **Wazuh Indexer to Logstash to Analytics OpenSearch** | Wazuh Indexer → Logstash OpenSearch input → filters → Analytics OpenSearch output | Preserves indexed Wazuh alerts, aligns with the official Wazuh integration pattern, and is suitable for a controlled pilot. | Requires compatible plugins, certificates, credentials, and careful checkpoint or time-window handling. |
| Wazuh server alert file to Logstash to Analytics OpenSearch | Wazuh Manager alert JSON → Logstash file input → filters → Analytics OpenSearch output | Reduces dependence on Wazuh Indexer queries and can be easier when alert files are available. | Requires reliable file reading, rotation handling, offset recovery, and careful duplicate prevention. |
| Wazuh Indexer to custom Sentroxis worker | Sentroxis worker queries Wazuh Indexer and writes directly to OpenSearch | Maximum application control and a single Python technology stack. | More custom reliability work; the worker must implement buffering, retries, checkpoints, and backpressure. |

**Recommendation:** Use **Wazuh Indexer → Logstash → Analytics OpenSearch** for the first Wazuh pilot. Use the alert-file path if the installed Wazuh topology makes Indexer export impractical. Do not begin with a custom worker unless the official Logstash path cannot satisfy the environment.

### Step 3: Protect the transport

The transport service must use:

1. TLS and certificate verification to the Wazuh Indexer.
2. TLS and certificate verification to the analytics OpenSearch cluster.
3. A dedicated Wazuh read-only or export identity.
4. A dedicated OpenSearch ingest identity.
5. A protected Logstash keystore or equivalent secret manager.
6. No passwords in pipeline files, Git, URLs, browser storage, or logs.
7. A bounded query window and a durable checkpoint or equivalent replay strategy.
8. Retry with backoff and a dead-letter route for records that cannot be processed.

The official Wazuh guide documents Logstash plugins for reading from the Wazuh Indexer and writing to OpenSearch. It also recommends explicit mappings/templates, TLS certificates, and secure Logstash keystore credentials.

### Step 4: Write first to a restricted quarantine or raw-compatible index

For a new pipeline, do not immediately discard fields before proving the export works. Write a restricted copy to a short-retention quarantine family such as:

```text
security-wazuh-quarantine-YYYY.MM.dd
```

This copy should be accessible only to the ingestion administrator and preprocessing job. It must still be protected against secrets and excessive document size; “raw” does not mean “unfiltered and unrestricted.”

Once the pipeline is stable, retain only the fields needed for reproducibility and feature engineering, or move original payloads to a separately protected archive.

### Step 5: Normalize and sanitize

Use Logstash filters or a preprocessing service for complex operations:

1. Parse and normalize timestamps.
2. Set `source=wazuh`.
3. Set a controlled `event_type`, such as `alert`, `agent_status`, or `agent_inventory`.
4. Copy Wazuh rule, decoder, agent, network, process, and file-integrity fields into stable names.
5. Add `schema_version`.
6. Add `ingested_at`.
7. Generate or preserve a stable `event_id`.
8. Add `source_trust=telemetry`.
9. Add `redaction_status` and the redaction policy version.
10. Remove or mask secrets, tokens, private keys, and unnecessary personal data.
11. Limit message, command, path, and preview lengths.
12. Drop or quarantine malformed timestamps and oversized documents.
13. Prevent arbitrary nested fields from creating mapping explosions.
14. Calculate a deterministic deduplication key.
15. Route records by type to the correct index family.

### Step 6: Use an OpenSearch ingest pipeline for simple final processing

After Logstash, use an OpenSearch ingest pipeline for deterministic, low-cost final processing such as:

1. Date parsing.
2. Field renaming.
3. Type conversion.
4. Lowercasing controlled keyword fields.
5. Setting defaults.
6. Removing unwanted fields.
7. Routing based on controlled event type.
8. Fingerprinting or hashing selected stable fields.
9. Handling pipeline failures.

Do not put large, complex, stateful, or security-sensitive business logic only inside an OpenSearch ingest pipeline. OpenSearch documentation distinguishes ingest pipelines, which run inside the cluster and suit simple preprocessing, from Data Prepper, which is better suited to larger and more complex processing.

### Step 7: Index the operational copies

Write normalized records to:

```text
security-wazuh-alerts-YYYY.MM.dd
security-events-YYYY.MM.dd
```

The first index preserves useful Wazuh-specific fields. The second uses the shared Sentroxis envelope so Wazuh, Velociraptor, and audit events can be searched together.

Use index templates before sending live data. Define explicit mappings for timestamps, identifiers, severity, IP addresses, controlled labels, bounded text, and arrays. Avoid solving mapping problems by endlessly increasing the total-field limit.

## 6. The recommended preprocessing and training path

### Step 1: Operational storage

Store the normalized alert and context records in operational indexes. These records support dashboards, investigations, timelines, correlation, and freshness monitoring.

### Step 2: Feature extraction

A separate preprocessing job should create model features from bounded time windows. Examples include:

1. Alert count per device over five minutes, thirty minutes, and twenty-four hours.
2. Count of critical and high-severity rules.
3. Number of distinct source IPs and destination IPs.
4. Number of failed logins followed by a successful login.
5. New process or parent-child process relationships.
6. New executable or file-integrity changes.
7. Agent offline duration.
8. Vulnerability severity and exposure age.
9. Number of affected devices in the same case.
10. Time since the previous similar alert.
11. Validated MITRE ATT&CK technique labels.
12. Analyst-confirmed incident or benign status.

Do not train a model on raw documents simply because they are available. Feature extraction should be reproducible, versioned, and able to point back to source event IDs.

### Step 3: Create training candidates

Write sanitized candidate records to:

```text
security-training-candidates-YYYY.MM.dd
```

A candidate should contain:

- `example_id`;
- normalized event or feature summary;
- source event IDs;
- source type;
- time window;
- device and case scope;
- validated or proposed label;
- MITRE technique, if confirmed;
- analyst rationale;
- label confidence;
- redaction status;
- dataset version;
- creator and review status.

### Step 4: Human review

A SOC analyst or designated reviewer must approve, reject, or correct candidates. Review should check:

1. Whether the label is supported by evidence.
2. Whether the record contains secrets or unnecessary personal data.
3. Whether attacker-controlled text could poison the dataset.
4. Whether duplicate or near-duplicate examples exist.
5. Whether train, validation, and test splits would leak the same incident across sets.
6. Whether the source and provenance are reproducible.

### Step 5: Publish approved data

Only approved, immutable, versioned records should be written to:

```text
security-training-approved-v001
```

The training exporter receives read-only access to this alias. It must not read raw Wazuh indexes, quarantine indexes, unrestricted evidence, or dead-letter documents.

## 7. Recommended pipeline components for this repository

The repository currently contains Wazuh integration and a FastAPI backend but does not yet contain the new ingestion pipeline. Add the components in this order:

```text
sentroxis-copilot/
├── ingestion/
│   ├── logstash/
│   │   ├── pipelines.yml
│   │   ├── wazuh-to-opensearch.conf
│   │   ├── templates/
│   │   └── README.md
│   ├── opensearch/
│   │   ├── index-templates/
│   │   ├── ingest-pipelines/
│   │   ├── roles/
│   │   └── lifecycle/
│   └── fixtures/
│       ├── wazuh-alert.json
│       ├── agent-status.json
│       └── expected-normalized-event.json
├── backend/
│   ├── models/normalized_event.py
│   ├── services/opensearch_service.py
│   ├── services/training_candidates.py
│   └── tests/test_normalization.py
└── docs/
    └── wazuh-opensearch-training-data-guide.md
```

The exact placement can follow the repository’s existing conventions. The important separation is between transport configuration, OpenSearch templates, backend authorization, and training governance.

## 8. Recommended pipeline separation

Use separate logical pipelines rather than one large pipeline.

### Pipeline A: Wazuh alerts

```text
Wazuh Indexer or alert JSON
  → Logstash input
  → checkpoint and retry
  → secret removal and size limits
  → Wazuh field preservation
  → normalized Sentroxis envelope
  → OpenSearch ingest pipeline
  → security-wazuh-alerts-* and security-events-*
```

### Pipeline B: Wazuh context

```text
Wazuh agent/status/inventory source
  → bounded periodic collection
  → snapshot normalization
  → deduplication by agent and collection time
  → security-wazuh-context-*
```

### Pipeline C: Sentroxis audit

```text
Sentroxis FastAPI audit event
  → backend validation
  → secret exclusion
  → audit identity or controlled application writer
  → security-audit-*
```

### Pipeline D: Training candidates

```text
Operational OpenSearch records
  → offline or controlled preprocessing job
  → feature extraction and redaction
  → candidate validation
  → security-training-candidates-*
  → analyst review
  → immutable security-training-approved-* alias
```

### Pipeline E: Velociraptor results

```text
Approved hunt metadata and results
  → Sentroxis server-side adapter
  → bounded pagination and retries
  → evidence hash/reference generation
  → shared normalization and sanitization
  → security-velociraptor-results-* and security-events-*
```

## 9. Logstash versus Data Prepper: final recommendation

| Choice | Recommended use | Decision |
|---|---|---|
| Logstash | First Wazuh export from Wazuh Indexer or alert files | **Use first.** It is directly documented by Wazuh for this integration and supports the required input/output plugins and secure keystore. |
| OpenSearch ingest pipeline | Simple final transformations inside OpenSearch | **Use alongside Logstash.** Keep it deterministic and small. |
| Data Prepper | Future complex, high-volume, multi-source ingestion or when a unified OpenSearch-native pipeline is preferred | **Keep as a later alternative.** It is not necessary for the first Wazuh pilot if Logstash meets the requirements. |
| Custom FastAPI worker | Sentroxis audit events, Velociraptor exports, and application-specific workflows | **Use selectively.** Do not make it the primary Wazuh transport until reliability requirements are proven. |

## 10. First implementation steps

1. Confirm whether the target analytics OpenSearch is separate from the Wazuh Indexer.
2. Record Wazuh version, deployment topology, alert source, event rate, storage, and retention requirements.
3. Select the first Wazuh source: Indexer export or alert-file export.
4. Create a dedicated OpenSearch ingest identity and a protected credential store.
5. Install compatible Logstash OpenSearch input and output plugins.
6. Configure TLS certificate verification on both sides.
7. Create a restricted quarantine index with a short retention policy.
8. Create explicit templates for Wazuh alerts, normalized events, context, audit, dead-letter, and training candidates.
9. Add a small Wazuh Logstash pipeline with bounded time windows, retries, duplicate handling, and dead-letter routing.
10. Add a simple OpenSearch ingest pipeline for timestamp, field, type, and routing operations.
11. Test with synthetic Wazuh alerts before connecting live telemetry.
12. Verify that ingestion failures do not silently disappear.
13. Add backend search APIs with server-side authorization and pagination.
14. Add preprocessing fixtures and deterministic feature extraction.
15. Create training candidates only from sanitized normalized data.
16. Add human review and approval before creating any training-approved alias.
17. Keep the training exporter read-only and deny it access to raw, quarantine, evidence, and dead-letter indexes.

## 11. What should be implemented now and what should wait

| Implement now | Wait until later |
|---|---|
| Wazuh alert export | Direct model training from raw alerts |
| Explicit mappings and templates | Vector embeddings for every raw event |
| TLS and least-privilege identities | Autonomous action based solely on model output |
| Normalized event envelope | Continuous collection of every possible endpoint event |
| Redaction and size limits | Unrestricted command output and file contents |
| Retry, idempotency, and dead-letter handling | Training-approved data before analyst review |
| Backend authorization and audit | RAG over raw telemetry |
| Synthetic end-to-end tests | Replacing the Wazuh Indexer |

## Final answer in one sentence

For Sentroxis, collect **Wazuh alert JSON plus selected endpoint context**, forward it first through **Logstash from the Wazuh Indexer or alert files**, apply **transport-level buffering and redaction**, use a small **OpenSearch ingest pipeline** for deterministic final normalization, store operational and restricted records separately, and create future training data only through a **reviewed preprocessing and approval pipeline**.

## References

[1]: https://documentation.wazuh.com/current/integrations-guide/opensearch/index.html "Wazuh OpenSearch integration guide"
[2]: https://docs.opensearch.org/latest/data-prepper/ "OpenSearch Data Prepper documentation"
[3]: https://docs.opensearch.org/latest/ingest-pipelines/ "OpenSearch ingest pipelines documentation"
[4]: ../docs/opensearch-telemetry-execution-plan.md "Sentroxis-Copilot OpenSearch telemetry execution plan"
[5]: ../README.md "Sentroxis Copilot repository README"
[6]: ../../Sentroxis_SRS_Final.pdf "Sentroxis Agentic SOC RAG Engine software requirements specification"

*Prepared by Manus AI for Sentroxis pre-development planning.*
