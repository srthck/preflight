# PreFlight — Determinism Specification

## Contract

> **Given identical normalized input, PreFlight Day 1 graph construction
> and canonical serialization must produce identical output — including
> identical byte sequences — across all invocations, Python processes,
> and operating systems.**

This property is foundational. It enables:
- Reproducible CI results
- Change detection via hash comparison (Day 11 DVH)
- Auditable output for hackathon judges and production users

---

## Deterministic Entity IDs

Entity IDs are assigned by the caller from stable inputs. They must:

- Be derived from **static, structural information** (table names, class names,
  file paths, service names)
- Never include: random values, UUIDs, current timestamps, memory addresses,
  or process IDs
- Never contain whitespace (enforced by Pydantic validator)

### Formation rules

```
Database columns:   "<table>.<column>"           → "users.phone_number"
Services:           "<service-name>.<ClassName>" → "user-service.UserService"
APIs:               "<service-name>.<ClassName>" → "profile-api.ProfileAPI"
Clients:            "<service-name>.<ClassName>" → "android-client.ProfileClient"
```

The service prefix uses lowercase kebab-case (matching directory names).
The class/symbol suffix uses PascalCase (matching source code identifiers).

---

## Deterministic Graph Construction

`GraphBuilder` enforces deterministic node and edge insertion order:

1. **Nodes** are inserted into the NetworkX graph sorted by `entity_id`
   (string sort, ascending).
2. **Edges** are inserted sorted by `(source, target, kind.value)`
   (all stable strings, lexicographic ascending).

This means the graph's internal iteration order does not depend on Python
dict insertion order or any hash randomisation.

---

## Deterministic Traversal

`find_downstream_paths()` and `find_canonical_path()` apply a defined
ordering rule to all results:

The Day 3 semantic layer adds a second determinism boundary: equivalent semantic
inputs must produce the same graph, canonical JSON, and downstream blast-radius
report regardless of source-file discovery order. This is validated with normal,
reverse, and shuffled file ingestion.

1. **Shortest path first** (ascending `hop_count`)
2. **Lexicographic tiebreak** on the `nodes` tuple for equal-length paths

This rule is tested in `tests/unit/test_traversal.py`.

No path ordering is left undefined. If two equal-length paths exist between
the same endpoints, the lexicographically smaller node sequence is always
returned first.

---

## Canonical Serialization

`canonical_json()` produces a stable JSON string by:

1. Sorting **nodes** by `entity_id` (ascending)
2. Sorting **edges** by `(source, target, kind.value)` (ascending)
3. Calling `json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=True)`

### Excluded values

The following are intentionally **excluded** from canonical output because
they are non-deterministic or extension data:

| Field | Reason for exclusion |
|-------|---------------------|
| `Entity.metadata` | Extension data; not part of canonical identity |
| `DependencyEdge.metadata` | Extension data |
| Wall-clock timestamps | Non-deterministic |
| Memory addresses | Non-deterministic |
| Random/UUID identifiers | Non-deterministic |

---

## SHA-256 Verification

`canonical_sha256(graph)` computes:

```python
hashlib.sha256(canonical_json(graph).encode("utf-8")).hexdigest()
```

This produces a 64-character hex string.

**Day 1 usage:** Used in tests to assert byte-level determinism across
two independent builds from the same input.

**Day 11 usage:** This will become the production Determinism Verification
Hash (DVH) — a content-addressable fingerprint of the analysis graph that
can be used to detect silent changes across deployments.

---

## Test Verification

Determinism is tested at two levels:

### Unit (`tests/unit/test_serialization.py`)

```python
graph_a = build_graph_from_same_input()
graph_b = build_graph_from_same_input()
assert canonical_json(graph_a) == canonical_json(graph_b)
assert canonical_sha256(graph_a) == canonical_sha256(graph_b)
```

Also tests that **reversed insertion order** produces identical output.

### Integration (`tests/integration/test_demo_fixture.py`)

```python
graph_a = build_demo_commerce_graph()
graph_b = build_demo_commerce_graph()
assert canonical_sha256(graph_a) == canonical_sha256(graph_b)
```

---

## Things PreFlight Explicitly Does Not Depend On


## Day 4 Blast-Radius Hash

`canonical_report_json()` sorts report keys and preserves deterministic finding
ordering. `blast_radius_sha256()` hashes those bytes without timestamps,
filesystem metadata, random IDs, or object representations. Blast-radius ranking

## Day 7 Rollback Truth Hash

`canonical_rollback_json()` sorts findings, dependencies, evidence, and
provenance and excludes the report's existing `deterministic_hash`.
`rollback_truth_sha256()` is therefore stable for equivalent snapshot and graph
inputs. Canonical rollback output contains no timestamps, random IDs, process
IDs, memory addresses, or machine-specific paths.

## Day 8 Decision Hash

`canonical_decision_json()` sorts normalized findings, risk evidence, compound
risks, and policy output. `decision_sha256()` hashes that canonical payload and
excludes the report's existing hash field. Reordering findings or graph inputs
cannot change the decision hash.

## Day 9 Explanation Fallback

`DeterministicExplanationProvider` consumes only sanitized structured decision
data. Its response has no timestamps, random identifiers, provider output, or
authoritative decision field. Equal `ExplanationInput` values therefore produce
equal serialized fallback responses. Provider output is advisory and is not
part of the deterministic decision hash.

## Day 10 Orchestration Determinism

`run_analysis()` calls every analyzer exactly once, in a fixed order, and
never reads wall-clock time, randomness, or process state. Its
`AnalysisRunResult.decision.deterministic_hash` is therefore just
`decide()`'s existing Day 8 hash — the orchestrator does not compute or
attach any hash of its own. `explain()`'s output is attached to the HTTP
response but is excluded from that hash, unchanged from Day 9.

`tests/integration/test_orchestration_pipeline.py` verifies, over the real
pipeline rather than a hand-built request object:
- ten full orchestration runs of the canonical scenario produce one
  distinct `deterministic_hash`;
- `SemanticAnalyzer` run with the fixture's files in forward, reversed, and
  shuffled order produces the same graph hash;
- two calls into the HTTP handler's `analyze()` function return the same
  `deterministic_hash`;
- mutating the migration fixture changes the hash, and restoring the
  original file byte-for-byte restores the original hash exactly.

## Day 11 Ingestion Determinism

`build_manifest()` walks the extracted project sorted by relative POSIX
path — never filesystem iteration order — hashes each file's content with
SHA-256, and hashes the canonical JSON of the whole sorted manifest into
`manifest_hash`. `run_project_analysis()` resolves the schema/migration/API
contract/semantic-file set via `preflight.ingestion.discovery` using the
same sorted, deterministic rules, then calls the identical
`_execute_pipeline()` the fixture-scenario path uses — so
`decision.deterministic_hash` inherits the exact same Day 8 guarantee.

`tests/integration/test_project_ingestion.py` proves this over real ZIP
bytes, not a hand-built request: ten runs of the same archive produce one
`deterministic_hash`; shuffling the ZIP's internal entry order before
re-zipping produces the same `manifest_hash` and `deterministic_hash`;
relabeling the same archive under three different (including deliberately
misleading) scenario labels produces the same hash every time; adding an
irrelevant new file changes `manifest_hash` (the manifest sees everything)
but not `deterministic_hash` (analysis only reacts to relevant evidence);
and mutating the migration file, then restoring it byte-for-byte, changes
and then exactly restores `deterministic_hash`.
