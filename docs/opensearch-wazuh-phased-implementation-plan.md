# Sentroxis OpenSearch/Wazuh Phased Implementation Plan

## Purpose

This plan divides the OpenSearch/Wazuh integration into small, testable phases. Work will be performed on the isolated branch `feature/opensearch-wazuh-integration`. The `main` branch must remain unchanged until all required phases pass their acceptance criteria and the branch is intentionally merged.

Each phase has four required parts:

1. **Deliverables:** the files or behavior to be added.
2. **Tests:** the checks that must be run.
3. **Exit criteria:** the evidence required before advancing.
4. **Rollback boundary:** the changes that can be reverted without affecting the existing main branch.

No later phase should be started as an implementation dependency until the previous phase has passed its exit criteria. Documentation, test fixtures, and non-invasive planning can be prepared in parallel when they do not change runtime behavior.

## Branch and operating rules

| Rule | Requirement |
|---|---|
| Development branch | `feature/opensearch-wazuh-integration` |
| Protected baseline | `main` remains the known-good Wazuh/Sentroxis baseline. |
| Commit scope | Prefer one focused commit per logical change or completed phase. |
| Testing | Run automated tests locally before pushing each phase. Run real Wazuh/OpenSearch tests on the target system where Docker, certificates, and persistent data exist. |
| Secrets | Never commit passwords, API keys, certificates with private keys, tokens, or real telemetry containing secrets. |
| Data safety | Use synthetic fixtures first. Do not use `docker compose down -v` unless indexed data is intentionally disposable. |
| Merge policy | Merge only after phase acceptance evidence, target-system validation, and explicit review of the final diff. |

## Target architecture

The first implementation target is:

```text
Wazuh agents
    ↓
Wazuh Manager + Wazuh Indexer
    ↓
controlled Wazuh export
    ↓
Logstash transport and buffer
    ↓
normalization and redaction
    ↓
OpenSearch ingest pipeline
    ↓
Sentroxis Analytics OpenSearch indexes
    ↓
Sentroxis backend query APIs
    ↓
analyst UI and approved preprocessing
```

The first implementation must not replace the Wazuh Indexer, modify Wazuh rules unnecessarily, train a model directly from raw telemetry, or give browser clients OpenSearch administrator credentials.

## Phase overview

| Phase | Name | Main outcome | Must pass before |
|---:|---|---|---|
| 0 | Baseline and scope lock | Confirm topology, versions, data source, retention, and constraints | Any runtime implementation |
| 1 | Contracts and synthetic fixtures | Stable event schema, redaction contract, IDs, and test data | Infrastructure integration |
| 2 | Analytics OpenSearch foundation | TLS, roles, templates, aliases, lifecycle, and health checks | Live ingestion |
| 3 | Wazuh export transport | Wazuh data reaches a restricted destination through Logstash | Normalized operational indexes |
| 4 | Normalize and sanitize | Safe, typed, bounded Sentroxis event envelope | Backend search APIs |
| 5 | Reliability and operational safety | Retry, idempotency, dead-letter handling, outage recovery | Production-like pilot |
| 6 | Sentroxis backend query APIs | Authorized bounded search and timeline endpoints | Frontend integration |
| 7 | Analyst views and observability | UI search, timelines, freshness, and ingestion health | RAG or training work |
| 8 | Training candidate preparation | Feature extraction and reviewed candidate records | Approved training data |
| 9 | Approved datasets and evaluation | Immutable approved dataset and offline evaluation | Any model training |
| 10 | Pilot hardening and merge review | Full evidence package and safe merge to main | Merge |

---

## Phase 0 — Baseline and scope lock

### Objective

Remove architectural ambiguity before adding runtime components.

### Decisions to record

1. Confirm that **Sentroxis Analytics OpenSearch** is separate from the existing **Wazuh Indexer**, even if both use OpenSearch technology.
2. Record the installed Wazuh version and topology.
3. Record the Velociraptor version and server location.
4. Choose the first Wazuh export source:
   - Wazuh Indexer to Logstash; or
   - Wazuh Manager alert JSON to Logstash.
5. Confirm development topology and target two-node topology.
6. Set expected event rate, endpoint count, storage capacity, and retention.
7. Resolve the SRS seven-day rollover requirement against any longer operational-retention proposal.
8. Select the initial event types: Wazuh alerts, selected agent context, Sentroxis audit events, and later Velociraptor results.
9. Decide whether automatic anomaly-to-DFIR triggering is in this integration scope or remains a later controlled feature.

### Deliverables

- A completed deployment baseline document.
- A decision record for the export method.
- A data-retention and field-scope decision.
- A target-system prerequisites checklist.

### Tests and evidence

- Version and topology commands captured without secrets.
- Available disk, memory, Docker, and certificate prerequisites confirmed.
- Sample Wazuh alert shape inspected using sanitized data.
- No production changes made.

### Exit criteria

Phase 0 passes when all decisions are recorded, the target system prerequisites are known, and the team can state exactly which source records will be collected first.

---

## Phase 1 — Contracts and synthetic fixtures

### Objective

Define the data contract before connecting live Wazuh telemetry.

### Deliverables

1. Pydantic models for the normalized event envelope.
2. Controlled enums for source and event type.
3. Schema versioning.
4. Stable event ID and idempotency-key rules.
5. Redaction policy and field allowlist.
6. Maximum lengths and document-size limits.
7. Synthetic Wazuh alert fixtures.
8. Synthetic agent status and inventory fixtures.
9. Synthetic Sentroxis audit fixtures.
10. Expected normalized output fixtures.
11. Tests for valid, malformed, oversized, duplicate, and secret-containing records.

### Minimum normalized fields

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

Fields that do not apply to a source remain absent or null. The schema must not force Wazuh, Velociraptor, and audit records into unsafe fake values.

### Tests

- Model validation tests.
- Timestamp normalization tests.
- Secret-redaction tests.
- Size-limit tests.
- Duplicate-key tests.
- Fixture-to-expected-output tests.
- Static checks for accidental secrets.

### Exit criteria

Phase 1 passes when synthetic records can be validated, normalized, redacted, deduplicated, and rejected deterministically without requiring a live OpenSearch cluster.

---

## Phase 2 — Analytics OpenSearch foundation

### Objective

Create a secure and bounded OpenSearch destination without connecting live ingestion yet.

### Deliverables

1. Development OpenSearch deployment or connection configuration.
2. TLS with certificate verification.
3. Security plugin configuration.
4. Separate service identities:
   - `ingest-wazuh`;
   - `sentroxis-reader`;
   - `sentroxis-auditor`;
   - `training-reviewer`;
   - `training-exporter`;
   - break-glass administrator.
5. Index templates and aliases for:
   - `security-wazuh-alerts-*`;
   - `security-events-*`;
   - `security-wazuh-context-*`;
   - `security-audit-*`;
   - `security-dead-letter-*`;
   - `security-training-candidates-*`;
   - `security-training-approved-*`.
6. Lifecycle and rollover policies based on the Phase 0 decision.
7. OpenSearch ingest pipeline for simple final transformations.
8. Health and readiness checks.
9. Snapshot and restore procedure for the pilot.

### Mapping requirements

Explicitly map timestamps, identifiers, severity, IP addresses, controlled labels, bounded text, arrays, device fields, rule fields, and provenance. Do not rely entirely on dynamic mapping. Do not solve mapping explosions by endlessly increasing the total-field limit.

### Tests

- Authenticated cluster health check.
- TLS certificate verification.
- Role permission tests.
- Template and alias creation tests.
- Index rollover test.
- Ingest pipeline simulation tests.
- Rejection tests for invalid timestamps and oversized documents.
- Snapshot creation and restore test.
- Test proving ingestion identities cannot read analyst data and readers cannot write.

### Exit criteria

Phase 2 passes when a secure empty analytics cluster can accept a synthetic normalized document through its template and ingest pipeline, reject invalid data, enforce roles, and recover from a test snapshot.

---

## Phase 3 — Wazuh export transport

### Objective

Move approved Wazuh records into a restricted OpenSearch destination without changing existing Wazuh detection behavior.

### Recommended method

Use:

```text
Wazuh Indexer → Logstash OpenSearch input → Logstash filters → OpenSearch output
```

Use the Wazuh alert-file path only if the installed topology makes Indexer export impractical. Do not begin with a custom FastAPI Wazuh poller unless the supported Logstash path fails a documented requirement.

### Deliverables

1. Compatible Logstash installation or container configuration.
2. Wazuh OpenSearch input plugin.
3. OpenSearch output plugin.
4. TLS certificate mounts and verification.
5. Logstash keystore or protected secret configuration.
6. Dedicated source and destination credentials.
7. Bounded source query or file-offset behavior.
8. Restricted quarantine index:

```text
security-wazuh-quarantine-YYYY.MM.dd
```

9. Initial Logstash pipeline with no destructive field removal beyond mandatory secret and size controls.
10. Operator runbook for starting, stopping, and inspecting the pipeline.

### Tests

- Synthetic Wazuh alert reaches quarantine.
- Live test alert reaches quarantine on the target system.
- TLS failure is detected rather than silently ignored.
- Invalid credentials fail safely.
- Pipeline restart behavior is recorded.
- Source records are not modified or deleted.
- Wazuh dashboard and existing Wazuh functionality remain usable.

### Exit criteria

Phase 3 passes when approved Wazuh records reliably reach the restricted quarantine destination, credentials are protected, TLS is verified, and the existing Wazuh stack continues to operate unchanged.

---

## Phase 4 — Normalize and sanitize

### Objective

Convert Wazuh records into safe Sentroxis operational documents.

### Deliverables

1. Logstash normalization filters or a controlled preprocessing component.
2. OpenSearch ingest pipeline for simple final transformations.
3. Stable `source=wazuh` and controlled event types.
4. Timestamp normalization.
5. Wazuh rule, decoder, agent, network, process, and file-integrity mappings.
6. Secret masking and unnecessary personal-data removal.
7. Command, message, path, and preview limits.
8. Redaction policy version and `redaction_status`.
9. Provenance and source-trust fields.
10. Deterministic idempotency key.
11. Routing to:

```text
security-wazuh-alerts-*
security-events-*
```

### Tests

- Normalization fixture tests.
- Secret and token redaction tests.
- Field allowlist tests.
- Mapping compatibility tests.
- Source timestamp and ingestion timestamp tests.
- Stable output test for repeated input.
- Attacker-controlled text escaping test.
- Unsupported or malformed record quarantine test.

### Exit criteria

Phase 4 passes when the same input produces the same safe normalized output, secrets are removed, provenance is retained, mappings are stable, and both Wazuh-specific and cross-source views are searchable.

---

## Phase 5 — Reliability and operational safety

### Objective

Ensure events are not silently lost, duplicated, or corrupted during ordinary failures.

### Deliverables

1. Retry with bounded exponential backoff.
2. Dead-letter routing:

```text
security-dead-letter-*
```

3. Duplicate detection and idempotent writes.
4. Backpressure and bounded buffers.
5. Ingestion freshness metrics.
6. Rejected-document metrics.
7. Mapping-error metrics.
8. Pipeline and OpenSearch health logging.
9. Outage recovery and replay procedure.
10. Operator troubleshooting guide.

### Tests

- OpenSearch temporary outage.
- Logstash restart.
- Wazuh source outage.
- Duplicate source delivery.
- Malformed document.
- Oversized document.
- Full or unavailable buffer.
- Short outage followed by catch-up.
- Dead-letter inspection and safe replay.
- No password or token leakage in logs.

### Exit criteria

Phase 5 passes when controlled failures result in retry, dead-letter routing, or explicit operator-visible failure, with no silent loss and no uncontrolled duplication.

---

## Phase 6 — Sentroxis backend query APIs

### Objective

Expose OpenSearch data only through authorized, typed, bounded Sentroxis APIs.

### Deliverables

Add backend endpoints for the minimum required views:

1. Unified security-event search.
2. Alert timeline.
3. Device history.
4. Wazuh alert details.
5. Ingestion health.
6. Dead-letter summary for authorized administrators.
7. Audit records.

Every endpoint must enforce:

- JWT authentication.
- Server-side device, tenant, and case authorization.
- Bounded time range.
- Pagination.
- Maximum result count.
- Query timeout.
- Typed filters.
- Safe text handling.
- Audit event for sensitive searches.
- Clear stale or partial-data indicators.

The browser must never receive OpenSearch administrator credentials or arbitrary query DSL execution.

### Tests

- Valid authenticated search.
- Unauthenticated rejection.
- Expired-token rejection.
- Unauthorized device/case rejection.
- Pagination and maximum-count tests.
- Timeout and cancellation tests.
- Search audit-event test.
- OpenSearch-unavailable graceful-degradation test.

### Exit criteria

Phase 6 passes when analysts can retrieve authorized data through stable backend endpoints and cannot bypass authorization through filters or query parameters.

---

## Phase 7 — Analyst views and observability

### Objective

Make the new data useful and understandable in the Sentroxis workspace.

### Deliverables

1. Unified event search view.
2. Endpoint timeline view.
3. Wazuh alert detail view.
4. Ingestion freshness indicator.
5. Partial-failure indicator.
6. Provenance display.
7. Evidence-reference display where applicable.
8. Authorized ingestion-health and dead-letter views.
9. UI handling for stale or temporarily unavailable OpenSearch data.

### Tests

- Frontend unit and component tests.
- Production frontend build.
- Authenticated end-to-end search.
- Unauthorized UI state.
- Empty, stale, partial, and error states.
- Large result pagination.
- XSS-safe rendering of untrusted event text.

### Exit criteria

Phase 7 passes when an analyst can search and investigate normalized events without direct OpenSearch access and can distinguish current, stale, partial, and failed data.

---

## Phase 8 — Training candidate preparation

### Objective

Create sanitized, reproducible candidate records without treating operational alerts as automatically approved labels.

### Deliverables

1. Feature extraction job.
2. Time-window definitions.
3. Candidate schema.
4. Redaction and malware-content checks.
5. Provenance links to source event IDs.
6. Duplicate and near-duplicate handling.
7. Candidate index:

```text
security-training-candidates-*
```

8. Review status model.
9. Dataset-version field.
10. Train/validation/test split policy that prevents incident leakage.

### Candidate fields

```text
example_id
source_event_ids
feature_summary
source_type
time_window
device_scope
case_scope
proposed_label
mitre_techniques
analyst_rationale
label_confidence
redaction_status
dataset_version
review_status
created_by
reviewed_by
```

### Tests

- Deterministic feature extraction.
- Source-event traceability.
- Secret-removal tests.
- Duplicate detection.
- Incident-level split tests.
- Poisoning and untrusted-text tests.
- Candidate authorization tests.

### Exit criteria

Phase 8 passes when candidates can be reproduced from operational data, contain no prohibited secrets, retain provenance, and remain clearly marked as unapproved.

---

## Phase 9 — Approved datasets and evaluation

### Objective

Create a governed, immutable dataset for offline evaluation or future model training.

### Deliverables

1. Human review workflow.
2. Approval and rejection controls.
3. Immutable versioned approved alias:

```text
security-training-approved-v001
```

4. Read-only training-export identity.
5. Dataset manifest with counts, hashes, labels, and source versions.
6. Train/validation/test exports.
7. Offline evaluation scripts.
8. Dataset rollback and deprecation procedure.

### Required approval checks

- Evidence supports the label.
- Secrets and unnecessary personal data are absent.
- Attacker-controlled instructions are not treated as labels.
- Duplicate incidents do not cross dataset splits.
- Provenance is complete.
- Reviewer identity and timestamp are recorded.
- Dataset version is immutable after publication.

### Tests

- Training exporter cannot read raw or quarantine indexes.
- Approved data cannot be modified by the exporter.
- Dataset manifest reproduces the expected records.
- Split leakage test passes.
- Offline baseline metrics are recorded.
- Dataset version rollback works.

### Exit criteria

Phase 9 passes when a reviewer-approved, immutable dataset can be exported and evaluated without access to raw telemetry or unrestricted evidence.

---

## Phase 10 — Pilot hardening and merge review

### Objective

Prove that the complete feature branch is safe to merge into `main`.

### Required evidence package

1. Phase-by-phase acceptance checklist.
2. Test command output.
3. Target-system integration results.
4. Security test results.
5. Failure and recovery test results.
6. Resource usage and storage estimate.
7. Retention and rollover evidence.
8. Snapshot and restore evidence.
9. Secret scan result.
10. Full diff review against `main`.
11. Updated operator and developer documentation.
12. Known limitations and follow-up issues.

### Final checks

Run the existing repository validation in addition to the new tests:

```bash
bash -n wazuh_installation.sh startup.sh start.sh
cd frontend
npm run lint
npm test -- --run
npm run build
```

Run the new OpenSearch/Wazuh checks from the repository root using the documented test command. Validate real Docker, TLS, Wazuh, and OpenSearch behavior on the target machine because the sandbox cannot reproduce the target’s persistent Wazuh environment.

### Exit criteria

The feature branch is merge-ready only when:

- All required phases pass.
- No required test is skipped without a documented reason.
- No secrets or real sensitive telemetry are committed.
- Existing Wazuh behavior remains intact.
- The target-system pilot succeeds.
- Documentation matches the actual implementation.
- The final diff has been reviewed.
- The team explicitly approves merging the branch into `main`.

## Recommended first coding milestone

Start with **Phase 1**, not with live Logstash or OpenSearch deployment. The first coding milestone should create the normalized event contract, redaction rules, synthetic Wazuh fixtures, and validation tests. This gives the later infrastructure work a stable target and prevents live telemetry from defining the schema accidentally.

After Phase 1 passes, implement Phase 2 foundations and test them with synthetic records. Only then connect the Wazuh export transport in Phase 3.

## Phase completion record

Use this table as the project gate. Update it only with evidence from completed tests.

| Phase | Status | Commit | Test evidence | Reviewer/date |
|---:|---|---|---|---|
| 0 | Not started | — | — | — |
| 1 | Not started | — | — | — |
| 2 | Not started | — | — | — |
| 3 | Not started | — | — | — |
| 4 | Not started | — | — | — |
| 5 | Not started | — | — | — |
| 6 | Not started | — | — | — |
| 7 | Not started | — | — | — |
| 8 | Not started | — | — | — |
| 9 | Not started | — | — | — |
| 10 | Not started | — | — | — |

## Related documentation

- [`wazuh-opensearch-training-data-guide.md`](wazuh-opensearch-training-data-guide.md)
- [`opensearch-telemetry-execution-plan.md`](opensearch-telemetry-execution-plan.md)
- [`opensearch-research-notes.md`](opensearch-research-notes.md)
- [`opensearch-telemetry-architecture.drawio`](opensearch-telemetry-architecture.drawio)
- [`wazuh-integration-architecture.md`](wazuh-integration-architecture.md)

## References

[1]: https://documentation.wazuh.com/current/integrations-guide/opensearch/index.html "Wazuh OpenSearch integration guide"
[2]: https://docs.opensearch.org/latest/data-prepper/ "OpenSearch Data Prepper documentation"
[3]: https://docs.opensearch.org/latest/ingest-pipelines/ "OpenSearch ingest pipelines documentation"
