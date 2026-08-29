# PreFlight Day 4: Blast Radius

Blast radius answers which entities are reachable when a tracked entity changes,
while preserving the causal dependency paths that justify each finding. It is a
bounded NetworkX traversal layer above the semantic graph, not a deployment risk
or failure-probability model.

## Model and traversal

`BlastRadiusRequest` contains the changed target, `max_hops`, and `max_paths`.
The engine uses NetworkX simple paths, so cycles terminate and no node repeats
within one path. Every path is retained up to the configured bounds. Findings are
classified `DIRECT` at one hop and `INDIRECT` beyond one hop.

## Impact heuristic

Prototype edge weights are transparent engineering heuristics:

- `DB_WRITE`: 1.00
- `DB_READ`: 0.90
- `API_CONSUMES`: 0.85
- `HTTP_CALL`: 0.75
- `CONFIG_DEPENDENCY`: 0.70
- `CALL`: 0.60
- `IMPORT`: 0.35

For a path with edge weights $w_i$ and $h$ hops:

$$
impact = \frac{\prod_i w_i}{1 + 0.5(h - 1)}
$$

The score is a deterministic engineering heuristic, not a statistical
probability of production failure. It is not the final PreFlight risk score.

## Ranking and evidence

Findings are ordered by severity descending, hop distance ascending, affected
entity ID, and complete path. Multiple paths are retained. Each path carries the
underlying semantic evidence, including source file, line, syntax, and resolution
rule. Canonical report JSON and SHA-256 exclude timestamps and object identity.

## CLI

From the repository root:

```text
python scripts/blast_radius.py --root fixtures/demo-commerce --target users.phone_number
python scripts/blast_radius.py --root fixtures/demo-commerce --target users.phone_number --json
```

## Performance and limitations

The canonical semantic fixture was measured separately at 37.712 ms median and
62.507 ms P95 over ten analyses. A dedicated Day 4 graph-size benchmark is not
measured yet. Simple-path enumeration can grow exponentially in highly branching
graphs; `max_hops` and `max_paths` are the explicit controls for this prototype.
Ambiguous and unresolved semantic references must be represented by the Day 3
semantic diagnostics layer before they can contribute to blast radius.

The closure work also confirms that canonical semantic output and blast-radius
output remain stable when the same source set is analyzed in different filesystem
orders, preserving a deterministic engineering analysis result across normal,
reversed, and shuffled discovery sequences.
