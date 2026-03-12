# Spec #7 — Edge Management

## Purpose

Defines the behavior of all edge operations in memory-cli: creating, removing, and listing directed relationships between neurons. Edges are the graph fabric that enables spreading activation search and captures why neurons are related. This spec also defines how the `--link` flag on `memory neuron add` delegates to edge creation, and the write-and-wire flow where neurons created at different times become connected through later discussions.

---

## Requirements Traceability

| Requirement | Section |
|---|---|
| Edges carry a REASON for the connection | §2.2 |
| Edge weight (default 1.0) modulates spreading activation strength | §2.2 |
| Edges created at capture time from co-occurrence | §2.2 |
| Edges created explicitly via `--link` flag or `edge add` command | §2.2 |
| Circular references are valid | §2.2 |
| Graph re-wires over time — old neurons gain new edges through later conversations | §2.2 |
| A conversation or capture session links all neurons created or referenced within it | §2.3 |
| Connections are captured, not inferred — the context of the moment IS the relationship | §2.3 |
| Optional: link to existing neuron with a reason at write time | §3.1 |
| Write-and-wire: new neuron linked to previously retrieved neuron; edge reason references bridging conversation | §3.3 |
| Neurons created at different times become connected through later discussions | §3.3 |
| Spreading activation traverses edges weighted by their weight column | §11 |

---

## Dependencies

- **#3 Schema & Migrations** — edges table must exist with columns: `source_id`, `target_id`, `reason`, `weight`, `created_at`. Indexes on `source_id` and `target_id` must exist (required for spreading activation performance).
- **#6 Neuron CRUD & Storage** — both source and target neurons must exist before an edge is created. Edge removal does not cascade to delete neurons.

---

## Behavior

### 7.1 Edge Data Model

An edge is a directed relationship from one neuron (source) to another (target).

Fields:
- `source_id` — integer, foreign key to neurons table, required
- `target_id` — integer, foreign key to neurons table, required
- `reason` — text, required, non-empty; describes why the relationship exists; supplied by the caller
- `weight` — float, default 1.0; modulates spreading activation strength along this edge; must be > 0.0
- `created_at` — timestamp, auto-set at creation, not user-modifiable

An edge is uniquely identified by the combination of `(source_id, target_id)`. Duplicate edges (same source and target) are not permitted. A second `edge add` for an identical `(source_id, target_id)` pair is an error.

### 7.2 Directionality

Edges are directed: `(source_id=A, target_id=B)` and `(source_id=B, target_id=A)` are two distinct edges. Creating one does not create the other. The spreading activation traversal in #8 queries `source_id` — meaning activation flows outward along edge direction. Bidirectional connectivity requires two separate edges. Whether `edge add` implicitly creates a reverse edge is flagged as a finding (see Findings).

### 7.3 `memory edge add`

Command: `memory edge add --source <id> --target <id> --reason <text> [--weight <float>]`

Behavior:
1. Validate that `--source` refers to an existing neuron. If not found: exit code 1, error message.
2. Validate that `--target` refers to an existing neuron. If not found: exit code 1, error message.
3. Validate that `--reason` is provided and non-empty. If missing or empty: exit code 2, error message.
4. Validate `--weight` if provided: must be a float > 0.0. If invalid: exit code 2.
5. Check for duplicate edge `(source_id, target_id)`. If it already exists: exit code 2, error message indicating the edge already exists (include the existing reason for context).
6. Insert edge record with `created_at` set to current UTC timestamp.
7. Output: the created edge as JSON (or plain text per --format), including all fields.
8. Exit code 0.

Self-loops (source == target) are a valid edge case — allowed, not blocked. Circular graphs are explicitly valid per §2.2.

### 7.4 `memory edge remove`

Command: `memory edge remove --source <id> --target <id>`

Behavior:
1. Validate that `--source` and `--target` are provided.
2. Look up the edge by `(source_id, target_id)`. If not found: exit code 1, informative message.
3. Delete the edge record.
4. Output: confirmation (edge deleted, with source/target IDs).
5. Exit code 0.

Removing an edge does not affect the source or target neurons. Neurons are never deleted by this command.

### 7.5 `memory edge list`

Command: `memory edge list --neuron <id> [--direction <outgoing|incoming|both>] [--limit N] [--offset M]`

Behavior:
1. `--neuron` is required. If missing: exit code 2.
2. Validate that the neuron exists. If not found: exit code 1.
3. `--direction` controls which edges are returned:
   - `outgoing` (default): edges where `source_id == neuron_id`
   - `incoming`: edges where `target_id == neuron_id`
   - `both`: union of outgoing and incoming
4. For each edge in results, include: `source_id`, `target_id`, `reason`, `weight`, `created_at`.
5. Also include the content snippet (first ~100 chars) of the connected neuron for readability — source neuron content for incoming edges, target neuron content for outgoing edges.
6. Results ordered by `created_at` descending (most recent first).
7. Pagination via `--limit` and `--offset`. Default limit is configurable (falls back to system default, e.g. 20). No maximum enforced in spec — implementation may cap at a reasonable value.
8. If no edges match: return empty list (exit code 0, not exit code 1). No edges is not an error.
9. Output: list of edge records with connected neuron snippets.

### 7.6 `--link` Flag on `memory neuron add`

The `--link` flag is a shorthand that creates a neuron and links it to an existing neuron in one atomic operation.

Command: `memory neuron add "<content>" --link <neuron_id> --link-reason "<reason>" [--link-weight <float>]`

Behavior:
1. Perform full neuron creation per spec #6.
2. If neuron creation succeeds, create an edge from the new neuron to the linked neuron: `source_id = new_neuron_id`, `target_id = <neuron_id>`.
3. `--link-reason` is required when `--link` is present. If missing: exit code 2 before any write.
4. If the target neuron (`--link <neuron_id>`) does not exist: fail before writing the new neuron. Exit code 1. No partial state.
5. The `--link-weight` is optional; defaults to 1.0.
6. Atomicity: neuron creation and edge creation are one transaction. If edge creation fails after neuron creation, the neuron write is rolled back.
7. Output: the created neuron record, with the created edge included in the output (nested or as a sibling field).

The direction convention (new neuron as source, linked neuron as target) reflects "this new thing relates to that prior thing." Whether this direction should be reversed or configurable is flagged as a finding.

### 7.7 Write-and-Wire Flow

Write-and-wire is the pattern described in §3.3: a neuron was retrieved in a prior step, the user is now adding a new neuron, and the new neuron should be connected to the previously retrieved one to record that a conversation bridged them.

This is mechanically identical to `--link` on `neuron add`. The "write-and-wire" term describes the caller's intent, not a distinct CLI command. The edge reason in this case should reference the bridging context (e.g., the session, conversation ID, or descriptive text supplied by the caller).

There is no special CLI command for write-and-wire. The caller (an AI agent or human) explicitly supplies `--link <prior_neuron_id> --link-reason "<bridging context>"`. The CLI does not track session state or automatically link neurons across calls.

### 7.8 Capture Context Linking (§2.3)

The requirement states that neurons co-occurring in a session are connected. This is NOT an automatic behavior in v1. The CLI does not implicitly track which neurons were mentioned in the same session and create edges. The caller is responsible for:

1. Knowing which neurons co-occurred.
2. Calling `edge add` or using `--link` to record those connections with an appropriate reason.

This is consistent with §2.3: "connections are captured, not inferred." The CLI provides the mechanism; the agent provides the intent.

Whether v1 should include any session-level auto-linking is flagged as a finding.

### 7.9 Edge Weight Semantics

Weight is a float with default 1.0. Weight > 1.0 strengthens the edge's contribution to spreading activation. Weight between 0.0 and 1.0 (exclusive) weakens it. Weight = 0.0 is not allowed (would make the edge invisible to spreading activation while still existing in the graph; ambiguous).

The weight is supplied at creation time and is fixed. There is no `edge update` command in v1 — to change a weight, the caller must remove and re-add the edge. Whether an `edge update` command is needed is flagged as a finding.

Weight is passed to the spreading activation algorithm in #8 as a multiplier on the activation propagated along that edge: `next_activation = parent_activation * decay * edge_weight`. The exact formula is defined in spec #8, not here. This spec only defines that weight is stored and must be > 0.0.

### 7.10 Output Format

All edge operations produce output in the configured format (JSON by default, plain text with `--format text`).

JSON edge record structure:
```
{
  "source_id": <int>,
  "target_id": <int>,
  "reason": <string>,
  "weight": <float>,
  "created_at": <ISO 8601 timestamp>
}
```

For `edge list`, the response wraps in a list and may include `total` count (pre-pagination) to support pagination UX.

---

## Constraints

- Reason is mandatory and must be non-empty on every edge. The system must not allow edges without reasons. Reason is the entire point of the edge — it captures the context of the moment.
- Weight must be > 0.0. 0.0 is rejected.
- Duplicate edges `(source_id, target_id)` are rejected. A pair may only have one edge at a time.
- Edge operations never delete or modify neurons.
- The `--link` flag creates a transaction: neuron + edge are written together or not at all.
- Edges reference neurons by integer ID. IDs must be validated against the neurons table before write.
- No batch edge creation command exists in v1 (conversation ingestion in #11 handles bulk edge creation internally, not through a CLI subcommand).

---

## Edge Cases

- **Self-loop:** `source_id == target_id`. Valid. No error. The spreading activation visited-set in #8 prevents infinite loops.
- **Circular graph:** A→B→C→A. Valid per §2.2 and §10.4. Spreading activation uses a visited set to handle cycles.
- **Neuron not found on add:** Fail fast, no partial writes.
- **Duplicate edge:** Return error with the existing edge's reason so the caller knows it already exists.
- **Remove non-existent edge:** Exit code 1 (not found), no error logged as a system fault.
- **Weight exactly 0.0:** Rejected (exit code 2). Weight of 0.0001 is allowed — it's > 0.0.
- **Very long reason text:** No maximum length enforced in spec. SQLite TEXT handles arbitrary length. Callers may pass full conversation excerpts as reason.
- **Neuron deleted after edge creation:** If #6 ever adds a soft-delete or archive for neurons, edges referencing archived neurons should still be traversable unless #8 filters them. This interaction is not defined here — flagged as a finding.
- **`--link` with non-existent target:** No neuron write occurs. Fail atomically. Exit code 1.
- **`edge list` with no edges:** Empty list, exit code 0. Not an error state.
- **Concurrent writes:** SQLite WAL mode + busy timeout handles concurrent agents writing edges simultaneously, consistent with §10 concurrent access rules.

---

## Findings

**F-1: Default edge directionality on `--link` is ambiguous.**
The spec defines `--link` as: new neuron = source, linked neuron = target. This means spreading activation propagates FROM new neuron TO old neuron. Whether the reverse direction (old→new, representing "led to this") is more semantically useful is unclear. The caller may want to create both directions. Recommend: confirm direction convention with project owner before implementation.

**F-2: No reverse-edge creation on `edge add`.**
`edge add` creates only the specified directed edge. If callers want bidirectional traversal they must add two edges. The spreading activation algorithm in #8 could alternatively be specified to traverse in both directions regardless of edge direction — but that is a decision for spec #8. Flagged here to ensure #8 addresses traversal directionality explicitly.

**F-3: No `edge update` command.**
Weight and reason are fixed at creation. To change either, the caller must remove and re-add. If agents frequently need to update edge weights (e.g., reinforcing connections over time), this creates churn. An `edge update` command may be warranted in v1 or v1.1. Flagged for project owner decision.

**F-4: Session-level auto-linking not defined.**
§2.3 says co-occurring neurons in a session are connected. This spec treats that as a caller responsibility (explicit `edge add` or `--link`). If the CLI is expected to track a session context and auto-link, that is a distinct feature not covered here or in #6. Flagged for clarification: is session-level auto-linking an agent responsibility or a CLI responsibility?

**F-5: Behavior when a linked neuron is archived or soft-deleted.**
If #6 implements neuron archival, edges pointing to archived neurons will still exist in the edges table. Spreading activation in #8 may or may not want to traverse to archived neurons. This edge case crosses spec boundaries and must be resolved when #6 and #8 are finalized.

**F-6: `edge list` content snippet length.**
The spec suggests ~100 chars. This is arbitrary. Should be consistent with whatever `neuron list` uses for truncation. Defer to #6 for the canonical snippet length.

**F-7: No `--link` for multiple targets in one command.**
`memory neuron add` with `--link` supports linking to one neuron. If a caller wants to link a new neuron to N prior neurons simultaneously, they must make N-1 additional `edge add` calls after the initial `neuron add --link`. This may be a usability gap for write-and-wire flows involving multiple retrieved neurons. Flagged for consideration.
