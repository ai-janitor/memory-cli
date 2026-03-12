# Spec #10 — Traversal Modes: Timeline & Goto

**Status:** done
**Requirements traced:** §4.4 Traversal Modes
**Dependencies:** #6 Neuron CRUD & Storage (timeline ordering, neuron retrieval), #7 Edge Management (goto follows edges)

---

## 1. Purpose

Define the behavior of two navigation commands that walk the graph from a starting neuron:

- `memory neuron timeline` — walk forward or backward chronologically from a neuron by creation timestamp
- `memory neuron goto` — follow edges from a neuron to its directly connected neighbors

These are navigation commands, not search. There is no scoring, no ranking, no BM25, no vector similarity, no spreading activation. The caller explicitly names a starting neuron and navigates from it.

---

## 2. Requirements Traceability

| Requirement | Source |
|---|---|
| Timeline: walk forward/backward chronologically from a neuron | §4.4 |
| Goto: follow edges to connected neurons regardless of creation time | §4.4 |
| Show edge reasons on goto traversal | §4.3 (fan-out output shows reason), §4.4 |
| Navigation commands, not search — no scoring, no ranking | §4.4 (implied by contrast with §4.1, §4.2) |
| CLI verbs under `neuron` noun | §7.1 Grammar |
| JSON default output, plain text alternative | §7.4 Output Format |
| Pagination: `--limit N --offset M` | §4.3 |
| Exit codes 0/1/2 | §7.4 |

---

## 3. Dependencies

- **#6 Neuron CRUD & Storage** — neurons have a `timestamp` field used for timeline ordering; neuron records are hydrated for output; the starting neuron must be resolvable by ID
- **#7 Edge Management** — edges have `source_id`, `target_id`, `reason`, `weight`, and `created_at`; goto queries edges by neuron ID

---

## 4. Behavior

### 4.1 Command Signatures

```
memory neuron timeline <neuron-id> [--direction forward|backward] [--limit N] [--offset M] [--format json|text]
memory neuron goto <neuron-id> [--direction outgoing|incoming|both] [--limit N] [--offset M] [--format json|text]
```

Both commands require exactly one positional argument: a neuron ID.

---

### 4.2 Timeline Command

#### What it does
Returns neurons ordered by creation timestamp, starting from a reference neuron, walking chronologically forward or backward through the full neuron set.

#### Direction
- `--direction forward` (default): returns neurons created AFTER the reference neuron, in ascending timestamp order (oldest first among the results)
- `--direction backward`: returns neurons created BEFORE the reference neuron, in descending timestamp order (most recent first among the results)

The reference neuron itself is NOT included in the result set.

#### Ordering anchor
The timeline is anchored by the reference neuron's `created_at` timestamp. "Forward" means timestamps strictly greater than the reference; "backward" means timestamps strictly less than the reference.

#### Timestamp tie-breaking
When two neurons share the same `created_at` timestamp, secondary sort is by neuron ID ascending. This ensures deterministic output.

#### Output fields per neuron
Each result item includes:
- `id` — neuron ID
- `content` — neuron content
- `created_at` — ISO 8601 timestamp
- `project` — project context at capture time
- `tags` — list of tag names
- `source` — capture source (if present)

The reference neuron's timestamp is NOT re-emitted in the result list. The caller already has it.

#### Scope
Timeline walks the entire neuron set — it is not scoped to a project or tag unless filtered. In v1, no tag or project filtering flags are defined for timeline (see Finding F-1).

#### Pagination
`--limit N` (default: 20) and `--offset M` (default: 0) apply to the ordered result set. Pagination is offset-based, consistent with `memory neuron search`.

---

### 4.3 Goto Command

#### What it does
Returns neurons directly connected to the reference neuron by an edge, along with the reason for each connection.

#### Traversal depth
Goto is single-hop only. It returns the immediate neighbors of the reference neuron — it does not recursively follow edges beyond depth 1. This distinguishes goto from spreading activation search (which fans out to configurable depth).

#### Direction
- `--direction outgoing` (default): follow edges where the reference neuron is the source (`source_id = reference`)
- `--direction incoming`: follow edges where the reference neuron is the target (`target_id = reference`)
- `--direction both`: follow edges in either direction

#### Output fields per result
Each result item includes:
- `neuron` — the connected neuron, with fields: `id`, `content`, `created_at`, `project`, `tags`, `source`
- `edge` — the edge connecting them, with fields:
  - `reason` — the reason string for the connection (REQUIRED, always present)
  - `weight` — the edge weight (float, default 1.0)
  - `edge_created_at` — when the edge was created (ISO 8601)
  - `direction` — `"outgoing"` or `"incoming"` relative to the reference neuron (only meaningful when `--direction both` is used)

The reference neuron itself is NOT included in the result set.

#### Ordering
Results are ordered by `edge_created_at` descending (most recently added edge first). This is the natural order of interest: edges added most recently are the most contextually relevant connections. Secondary sort is by connected neuron ID ascending for tie-breaking.

#### Circular references
If the reference neuron has an edge to itself (self-loop), it appears in the result set as a connected neuron. This is valid per §2.2 ("circular references are valid").

#### Pagination
`--limit N` (default: 20) and `--offset M` (default: 0) apply.

---

### 4.4 Shared Behavior

#### Starting neuron validation
- If the provided `<neuron-id>` does not exist in the database, the command exits with code 1 and emits an error: `{"error": "neuron not found", "id": "<neuron-id>"}` (JSON) or `Error: neuron not found: <neuron-id>` (text).
- Neuron IDs are integer. If a non-integer value is supplied, the command exits with code 2 (invalid input).

#### Empty result
If no neurons satisfy the traversal (e.g., no edges for goto, or the reference neuron is the first/last in the timeline), the command exits with code 0 and returns an empty list: `{"results": [], "total": 0}`.

Exit code 0 on empty is intentional — "not found" (code 1) applies to the starting neuron not existing, not to the traversal yielding no results.

#### Output format
- Default: JSON
- With `--format text`: human-readable plain text
- Configurable default in `config.json` per §7.4

**JSON envelope — timeline:**
```json
{
  "command": "timeline",
  "reference_id": 42,
  "direction": "forward",
  "results": [ /* neuron objects */ ],
  "total": 7,
  "limit": 20,
  "offset": 0
}
```

**JSON envelope — goto:**
```json
{
  "command": "goto",
  "reference_id": 42,
  "direction": "both",
  "results": [
    {
      "neuron": { /* neuron object */ },
      "edge": {
        "reason": "discussed together in planning session",
        "weight": 1.0,
        "edge_created_at": "2026-01-10T14:22:00Z",
        "direction": "outgoing"
      }
    }
  ],
  "total": 3,
  "limit": 20,
  "offset": 0
}
```

`total` reflects the count of all matching results before pagination is applied.

#### Help
- `memory neuron timeline --help` — flags and usage
- `memory neuron goto --help` — flags and usage

---

## 5. Constraints

1. These are navigation commands, not search. No scoring, no ranking, no BM25, no vector similarity, no spreading activation, no `--explain` flag.
2. Goto is single-hop. It does not recurse. Spreading activation (multi-hop) is the domain of `memory neuron search` (spec #8).
3. Timeline ordering is strictly by `created_at` timestamp. There is no weight, relevance, or decay applied.
4. Both commands read-only. They do not create or modify any data.
5. Embedding is NOT loaded for these commands. No in-process model load cost.
6. Pagination defaults (`--limit 20`) must be consistent with search pagination defaults (§4.3).
7. No LLM is involved. These commands have zero LLM cost.

---

## 6. Edge Cases

| Scenario | Expected Behavior |
|---|---|
| Reference neuron has no edges | Goto returns empty list, exit 0 |
| Reference neuron is the most recent in the DB | `timeline --direction forward` returns empty list, exit 0 |
| Reference neuron is the oldest in the DB | `timeline --direction backward` returns empty list, exit 0 |
| Two neurons with identical timestamps | Secondary sort by ID ascending; deterministic order |
| Edge from neuron to itself (self-loop) | Appears in goto results with its reason; valid |
| `--offset` exceeds total result count | Returns empty list, exit 0; `total` still reflects actual count |
| `--limit 0` | Finding F-2: ambiguous (see Findings) |
| `--direction` value is invalid string | Exit code 2, error message |
| Neuron ID is 0 or negative | Finding F-3: ambiguous (see Findings) |
| Very large neuron set (100K+ neurons) | Timeline uses indexed timestamp query; performance must not degrade relative to result count |

---

## 7. Findings

**F-1: No filtering flags defined for timeline in v1**
Requirements §4.4 specifies timeline as walking "forward/backward chronologically from a neuron." No mention of tag or project filtering for timeline. This spec omits tag/project filtering for timeline in v1. If callers want chronological neurons within a project, they must post-filter the output. This is a gap worth flagging for v2.

**F-2: `--limit 0` behavior is unspecified**
The requirements do not define what `--limit 0` means. Options: (a) return 0 results (valid pagination), (b) treat as "no limit" and return all results, (c) return an error. Recommendation: treat `--limit 0` as returning 0 results with `total` populated — consistent with how pagination libraries typically behave. Implementation agent should confirm.

**F-3: Invalid neuron IDs (0, negative)**
Requirements do not specify whether neuron IDs are 1-indexed or 0-indexed, or whether negative values are possible. If the schema uses SQLite autoincrement, IDs are positive integers starting at 1. A value of 0 or negative should be treated as "not found" (exit 1) rather than a validation error (exit 2), unless the schema spec (#3) explicitly disallows such IDs. Implementation agent should align with #3 spec on this.

**F-4: Timeline scope — all neurons vs. project-scoped**
The requirements don't specify whether timeline walks ALL neurons in the DB or only neurons within the same project as the reference neuron. Given that neurons have a `project` field and the user values project isolation (§2.1), timeline scoped to the same project is arguably more useful. However, §4.4 says "walk forward/backward chronologically from a neuron" with no project qualifier. This spec leaves timeline as global (all neurons) and flags it for the implementation agent and product owner to confirm.

**F-5: Goto direction — edge direction semantics vs. bidirectional storage**
The spreading activation research (spec-context, research/spreading-activation-algorithm.md) notes that edges may be stored bidirectionally OR queried with `WHERE source_id = ? OR target_id = ?`. The goto spec defines `--direction outgoing|incoming|both` semantically. If edges are stored bidirectionally (one row per direction), the `incoming`/`outgoing` distinction requires that the direction be encoded in the edge row itself, not derived from which ID matches which column. This is a dependency on the edge schema defined in #7 — the implementation agent must verify that edge rows carry directional information or that query logic correctly distinguishes direction.

**F-6: `total` count with pagination — pre-pagination or post-pagination?**
The spec defines `total` as the count before pagination. This requires a COUNT query plus the paginated SELECT query, adding a second DB round-trip. This is the standard REST API pattern and is assumed correct. Implementation agent should be aware of the two-query pattern.
