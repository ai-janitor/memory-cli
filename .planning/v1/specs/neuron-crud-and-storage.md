# Spec #6 — Neuron CRUD & Storage

## Purpose

This spec covers all create, read, update, and archive operations on neurons — the fundamental unit of storage in memory-cli. A neuron is a stored fact, entity, concept, or state. This spec defines what properties a neuron carries, what happens when one is created (auto-tagging, immediate embedding, optional edge creation), how neurons are retrieved individually or as a filtered list, how content and metadata are updated, and what archiving means. It also covers the write-and-wire pattern — linking a new neuron to a previously retrieved one at write time.

This spec sits at Tier 3 in the dependency graph. It is the first spec that writes user-visible data. All search, traversal, edge management, and export operations build on the primitives defined here.

---

## Requirements Traceability

| Requirement | Source |
|---|---|
| A neuron represents a fact, entity, concept, state, or thing | §2.1 Neurons |
| Properties: content, timestamp, project, tags, source, attributes | §2.1 Neurons |
| Every neuron has at minimum: timestamp and project (auto-captured from pwd/git) | §2.1 Neurons |
| One-liner CLI command to store a fact | §3.1 Manual Quick Capture |
| Auto-tags: timestamp, current project (from pwd/git) | §3.1 Manual Quick Capture |
| User-provided tags are additive (alongside auto-tags) | §3.1 Manual Quick Capture |
| Optional: link to existing neuron with a reason at write time | §3.1 Manual Quick Capture |
| Embeds immediately on write (model loads in-process) | §3.1 Manual Quick Capture |
| When a neuron is retrieved, used in conversation, and new neuron saved — new can link to old | §3.3 Write-and-Wire |
| The edge reason references the conversation that bridged them | §3.3 Write-and-Wire |
| Tags normalized to lowercase on write | §5 Tags |
| Tags included in embedding input (carry semantic meaning) | §5 Tags |
| No empty tags — auto-capture ensures minimum context | §5 Tags |
| Attribute key-value metadata on neurons | §6 Attributes |
| AI-first noun-verb grammar: `memory neuron <verb>` | §7.1 Grammar |
| Default output: JSON | §7.4 Output Format |
| Exit codes: 0=success/found, 1=not found, 2=error | §7.4 Output Format |
| Embedding input: content text + tags concatenated | §8 Embedding |
| Task prefix `search_document:` prepended transparently on write | §8 Embedding |
| Storage format is separate from embedding input format | §8 Embedding |
| Embedding is decoupled — can store without embedding, re-embed later | §8 Embedding |
| Single-file backup (copy the DB) | §2 Storage |
| AI agents cannot access storage directly — CLI is the only interface | §2 Storage |
| Design must not preclude multi-DB / sharding in future versions | §2 Storage |
| Conflicting memories: both live, most recent outranks by default | §10 Edge Cases |
| Concurrent access: SQLite WAL mode, serialized writes with busy timeout | §10 Edge Cases |

---

## Dependencies

- **#3 Schema & Migrations** — neurons table, FTS5 virtual table (`neurons_fts`), vec0 virtual table (`vec_neurons`), FTS sync triggers, all indexes must exist before any neuron operation runs.
- **#4 Tag & Attribute Registries** — tag name-to-ID resolution (auto-create on reference), attribute key-to-ID resolution, lowercase normalization. Every tag operation during neuron write goes through the registry.
- **#5 Embedding Engine** — called on write to produce the 768-dim vector for the neuron. The embedding engine handles the `search_document:` prefix transparently. If unavailable, the neuron is stored without a vector (stale/blank).

The `--link` flag at write time delegates to the edge module (spec #7). This spec defines the interface for that delegation: the caller passes the target neuron ID and a reason string; the edge module creates the edge. This spec does not define edge creation logic.

---

## Behavior

### 1. Neuron Data Model

A neuron has the following properties:

| Field | Type | Notes |
|---|---|---|
| `id` | integer | Auto-assigned by DB on insert. Immutable after creation. |
| `content` | text | The fact, entity, concept, or state being stored. Required. Non-empty. |
| `timestamp` | datetime (UTC) | Auto-captured at write time. Immutable after creation. |
| `project` | text | Auto-captured from current working directory and/or git remote at write time. See §4 (Auto-Tag Capture). |
| `source` | text | Optional. Caller-provided provenance string (e.g., "claude-session", "manual", "ingestion"). Null if not provided. |
| `status` | text | Lifecycle state: `active` (default) or `archived`. |
| `tags` | set of tag IDs | Resolved via tag registry (#4). Always includes auto-tags. User tags are additive. |
| `attributes` | map of attr key ID → value | Resolved via attribute registry (#4). Optional. |
| `embedding` | float[768] or null | Vector stored in vec_neurons table. Null if not yet embedded. |
| `embedding_updated_at` | datetime or null | Timestamp of last successful embed. Used to detect stale vectors when content changes. |

Content is the only required caller-supplied field on `neuron add`. All other fields are optional or auto-populated.

### 2. Command: `memory neuron add`

**Signature:**
```
memory neuron add <content> [--tags TAG,...] [--source SOURCE] [--attr KEY=VALUE ...] [--link NEURON_ID --reason REASON] [--no-embed] [--format json|text]
```

**Step 1 — Validate inputs.**
- `content` must be non-empty. If empty or absent, exit 2 with error.
- `--link` requires `--reason`. If `--link` is given without `--reason`, exit 2 with error.
- `--link NEURON_ID` must reference a neuron that exists and is not archived. If the target does not exist, exit 2 with error.
- Tag names in `--tags` are validated as non-empty strings. Each is resolved through the tag registry (auto-created if new, normalized to lowercase).
- `--attr KEY=VALUE` pairs are parsed; keys resolved through attribute registry (auto-created if new).

**Step 2 — Resolve auto-tags.**
Two auto-tags are always generated at write time:
- A **timestamp tag** encoding the capture date (see §4.1).
- A **project tag** encoding the current project context (see §4.2).
Auto-tags are resolved through the tag registry (normalized, auto-created if new). They are added to the neuron's tag set unconditionally alongside any user-supplied tags.

**Step 3 — Write neuron record.**
Insert the neuron into the neurons table with: content, timestamp (current UTC), project (from auto-capture), source (from flag or null), status=`active`. Insert tag associations. Insert attribute key-value pairs. The FTS5 sync triggers (defined in spec #3) fire automatically on insert — this spec does not invoke them directly.

**Step 4 — Embed immediately.**
Unless `--no-embed` is specified, call the embedding engine (#5) with the embedding input (see §5). On success, store the vector in `vec_neurons` and record `embedding_updated_at`. On failure (model unavailable, timeout), store the neuron without a vector and emit a warning to stderr. The neuron write is not rolled back due to embedding failure — the record is valid and embeddable later via batch re-embed.

**Step 5 — Optional edge creation via `--link`.**
If `--link NEURON_ID --reason REASON` was provided, delegate to the edge module (spec #7) to create an edge from the new neuron to the target neuron with the given reason. Edge creation failure does not roll back the neuron write; it is reported as a separate warning/error.

**Step 6 — Output.**
On success, output the newly created neuron record (JSON by default). Include `id`, `content`, `timestamp`, `project`, `tags`, `source`, `status`, `attributes`. Include `embedding_updated_at` if embedding succeeded, null if skipped. Exit 0.

### 3. Command: `memory neuron get`

**Signature:**
```
memory neuron get <id> [--format json|text]
```

**Behavior:**
- Look up neuron by integer ID in the neurons table.
- If not found, exit 1 with "not found" message.
- If found (regardless of status — active or archived), return the full neuron record: id, content, timestamp, project, tags (resolved to names), source, status, attributes (resolved to key names and values), embedding_updated_at.
- Exit 0 on success.

Archived neurons are retrievable by ID. Archiving is not deletion.

### 4. Command: `memory neuron list`

**Signature:**
```
memory neuron list [--tags TAG,...] [--tags-any TAG,...] [--status active|archived|all] [--project PROJECT] [--limit N] [--offset M] [--format json|text]
```

**Behavior:**
- Return neurons matching all specified filters.
- Default status filter is `active`. `--status all` returns both active and archived.
- `--tags TAG,...` is AND filtering: neuron must have ALL listed tags.
- `--tags-any TAG,...` is OR filtering: neuron must have AT LEAST ONE listed tag.
- `--tags` and `--tags-any` can be combined: neuron must satisfy both sets simultaneously.
- `--project PROJECT` filters to neurons whose project field matches exactly.
- Default ordering: most recent timestamp first.
- `--limit N` defaults to a configurable value (from config.json search defaults). `--offset M` defaults to 0.
- If no neurons match, return an empty list. Exit 0 (not exit 1).
- Each returned neuron in the list includes: id, content, timestamp, project, tags (names), source, status, attributes.
- Exit 0 on success, exit 2 on filter parse error.

### 5. Command: `memory neuron update`

**Signature:**
```
memory neuron update <id> [--content NEW_CONTENT] [--tags-add TAG,...] [--tags-remove TAG,...] [--attr-set KEY=VALUE ...] [--attr-unset KEY ...] [--source SOURCE] [--format json|text]
```

**Behavior:**
- Look up neuron by ID. If not found, exit 1.
- Archived neurons cannot be updated. If status is `archived`, exit 2 with error message "cannot update archived neuron; restore first".
- At least one mutation flag must be provided. If none are given, exit 2 with error.

**Content update:**
- If `--content` is provided with a non-empty string, replace the neuron's content field.
- After content change, the neuron's embedding is immediately re-generated (unless `--no-embed` is passed). If re-embedding succeeds, `embedding_updated_at` is updated. If it fails, the old vector is retained and a warning is emitted. The vector is considered stale (content_updated_at > embedding_updated_at) until re-embedded.
- The FTS5 sync triggers fire automatically on UPDATE — this spec does not invoke them directly.

**Tag mutations:**
- `--tags-add` resolves new tags through registry and adds them to the neuron's tag set. Tags already present are ignored (idempotent).
- `--tags-remove` removes the specified tags from the neuron's tag set. Auto-tags (timestamp, project) cannot be removed via `--tags-remove`. If a caller attempts to remove an auto-tag, it is silently ignored (not an error). Removing a tag not present on the neuron is silently ignored.

**Attribute mutations:**
- `--attr-set KEY=VALUE` adds or replaces the attribute on the neuron.
- `--attr-unset KEY` removes the attribute from the neuron. Unsetting a key not present is silently ignored.

**Source update:**
- `--source SOURCE` replaces the source field.

**Output:** Return the full updated neuron record. Exit 0.

### 6. Command: `memory neuron archive`

**Signature:**
```
memory neuron archive <id> [--format json|text]
```

**Behavior:**
- Look up neuron by ID. If not found, exit 1.
- If already archived, this is a no-op. Return the neuron record. Exit 0.
- Set neuron status to `archived`.
- Archiving does NOT delete the record, remove vectors, remove FTS entries, or remove edges.
- Archived neurons: not returned by default in `neuron list` (unless `--status archived` or `--status all`); retrievable by exact ID via `neuron get`; excluded from search results by default (search behavior defined in spec #8, not here); their edges remain intact.
- Output: return the updated neuron record with status=`archived`. Exit 0.

There is no `neuron delete` command in v1. Archiving is the only lifecycle change beyond creation and update.

There is no `neuron restore` command in this spec. The update command rejects archived neurons. Whether a restore command exists is flagged as a finding (see §Findings).

### 7. Auto-Tag Capture

Auto-tags are generated at write time and injected unconditionally into every neuron's tag set.

#### 7.1 Timestamp Tag

The timestamp auto-tag encodes the creation date. Format: `YYYY-MM-DD` (e.g., `2026-03-11`). This is resolved through the tag registry (normalized to lowercase, auto-created if new). It allows date-based filtering and carries temporal context in the embedding.

#### 7.2 Project Tag

The project auto-tag identifies the context from which the neuron was captured. The resolution order is:

1. If a git repository is detectable from the current working directory (or any parent), use the git remote URL's repository name (e.g., `memory-cli` from `git@github.com:user/memory-cli.git`). Strip the `.git` suffix.
2. If no git remote is found but a `.git` directory exists, use the last path segment of the current working directory.
3. If no git context exists, use the last path segment of the current working directory.
4. If the current working directory cannot be determined, use `unknown`.

The project tag is normalized to lowercase, stripped of any characters that are not alphanumeric, hyphens, or underscores. It is resolved through the tag registry (auto-created if new).

The `project` field on the neuron record (a first-class column, not just a tag) is set to the same resolved value. Both the column and the tag are populated.

### 8. Embedding Input Construction

The embedding input for a neuron is constructed as follows:

```
<content> [<tag1> <tag2> ... <tagN>]
```

- The content text comes first.
- All tag names (resolved strings, not IDs) are appended in a space-separated list inside square brackets.
- Tags are sorted alphabetically for deterministic output.
- The `search_document:` prefix is prepended by the embedding engine (#5), not by this module. This spec does not construct the prefix.
- The storage format (what is saved to the DB) is the raw content only. The embedding input format (content + tags) is only used for generating the vector. This separation is per §8 "Storage format is separate from embedding input format."

### 9. Neuron ID Semantics

- Neuron IDs are assigned by SQLite (auto-increment integer). They are stable — once assigned, an ID never changes and is never reused.
- IDs are the canonical reference for neurons in all CLI commands, edge declarations, and export/import.
- IDs are opaque to the caller — their value carries no semantic meaning beyond uniqueness and ordering by insertion time.

### 10. Concurrent Write Safety

Multiple CLI invocations may run simultaneously (multiple agents writing). The neurons table is protected by SQLite WAL mode and a busy timeout (configured in spec #3). Writes are serialized at the SQLite level. No application-level locking is required for single-neuron writes.

---

## Constraints

- Content must be non-empty. The system must not store a neuron with empty or whitespace-only content.
- Auto-tags are immutable via `--tags-remove`. The timestamp and project tags cannot be removed from a neuron after creation.
- Auto-tags are not re-generated on update — the original capture context is preserved even if content changes.
- Embedding failure is non-fatal for writes. The system must never roll back a successful neuron write due to an embedding failure.
- Archiving is irreversible in v1 via any documented command path (see Findings §F-3).
- The `--link` flag at `neuron add` creates exactly one edge. Multiple simultaneous `--link` flags in a single invocation are not supported in v1.
- All timestamps are stored and returned as UTC ISO 8601.
- The neurons table is the source of truth. FTS5 and vec_neurons are derived indexes. In the event of inconsistency, the neurons table wins (re-sync is handled by batch re-embed and FTS rebuild, defined in specs #5 and #3 respectively).
- Vector dimension must match the configured model's output dimension (768 for nomic-embed-text-v1.5). Dimension mismatch is detected by spec #13 (Metadata & Integrity) before any write operation.
- The project column and project tag must always agree. They are set from the same resolved value at write time and neither is independently mutable after creation.

---

## Edge Cases

### EC-1: `memory neuron add` called with content that duplicates an existing neuron
Both records are created. The system does not deduplicate on content. Two neurons with identical content are valid. Most recent outranks by default in search (§10 Conflicting memories).

### EC-2: `memory neuron add` called outside any directory (e.g., `/`)
The project auto-tag resolution falls through to the last path segment of pwd, which may be empty or `/`. In this case, use `unknown` as the project value.

### EC-3: `memory neuron add` with `--link` pointing to an archived neuron
Exit 2 with error. Edges to archived neurons are not created at write time. (Rationale: archived neurons are out of active graph circulation.)

### EC-4: `memory neuron update` with `--content` set to the same content as current
The update is accepted. The content field is overwritten with the same value. The embedding is re-generated (unless `--no-embed`). `embedding_updated_at` is updated. This is intentional — the caller may want to force a re-embed.

### EC-5: `memory neuron update` with `--tags-add` for a tag already on the neuron
Idempotent. No error. No duplicate tag association created.

### EC-6: `memory neuron list` with both `--tags` and `--tags-any`
Both constraints apply simultaneously. The neuron must satisfy the AND constraint (all tags in `--tags` present) AND the OR constraint (at least one tag in `--tags-any` present).

### EC-7: `memory neuron get` on a neuron with a null embedding
Return the neuron record with `embedding_updated_at: null`. Do not attempt to re-embed on get. Get is always read-only.

### EC-8: `memory neuron archive` on a neuron that is the target of existing edges
The edges are not removed. The archived neuron remains reachable via edge traversal for graph integrity purposes. Search and list commands apply their own status filters — this spec does not govern what happens to those edges in search results (that is spec #8's concern).

### EC-9: `memory neuron add` with a `--source` value that is very long
No maximum length is enforced in v1 beyond what SQLite's TEXT column accommodates. This is noted as a finding.

### EC-10: Git remote URL is a local path (e.g., `file:///some/path`)
Extract the last path segment as the project name, strip `.git` suffix if present, normalize.

### EC-11: `memory neuron list` returns zero results
Return empty JSON array `[]`. Exit 0. This is not a "not found" condition — it is a valid empty result set.

### EC-12: Embedding engine takes longer than the CLI's expected startup window
The neuron is already written to the DB before embedding is attempted. If embedding times out, the neuron exists with a null vector. The write is not rolled back. The caller receives the neuron record with `embedding_updated_at: null` and a stderr warning.

---

## Findings

### F-1: No `neuron restore` command defined
The spec defines `neuron archive` (active → archived) but no reverse operation. `neuron update` explicitly blocks updates on archived neurons. There is no specified way to return an archived neuron to active status. This gap should be resolved before implementation. Options: (a) add `neuron restore <id>` command, (b) allow `neuron update <id> --status active` as an explicit exception, (c) accept archive as permanent in v1. Recommendation: add `neuron restore` for symmetry, but flag for user decision.

### F-2: `--no-embed` flag — surface or internal?
The spec allows `--no-embed` at `neuron add` and `neuron update`. It is unclear whether this flag should be user-visible in help output or treated as an internal/advanced flag. If ingestion pipelines (spec #11) call neuron add in bulk and embed in a separate batch pass, `--no-embed` needs to be a reliable, documented interface. Recommend: document it, flag as advanced.

### F-3: Archiving is described as "irreversible in v1" but no explicit requirement says so
The requirements say nothing about restore. "Archive" as a soft state change (vs. deletion) implies reversibility. The irreversibility claim in this spec is an inference from the absence of a restore command, not a stated requirement. This should be confirmed with the user. If archive is reversible, `neuron restore` must be added to this spec.

### F-4: Tag timestamp format granularity
The timestamp auto-tag is specified as `YYYY-MM-DD`. This means all neurons created on the same day share the same timestamp tag. This is intentional for coarse grouping but means the tag alone cannot distinguish two neurons created 5 minutes apart. The `timestamp` column on the neuron record carries full precision. If finer-grained temporal tagging is needed (e.g., `YYYY-MM-DD-HH`), that is a v2 concern.

### F-5: `--link` supports only one edge at write time
The spec limits `--link` to a single target neuron at `neuron add`. If a caller wants to link a new neuron to multiple existing neurons at write time, they must use `edge add` after the fact (spec #7). This is a deliberate constraint. If multi-link at add time is desired, it requires a flag syntax change (repeatable `--link` flags) and is deferred to v2.

### F-6: Source field has no controlled vocabulary
The `source` field is a free-text string with no registry or normalization. Common values like `"manual"`, `"ingestion"`, `"claude-session"` are mentioned in context but not enforced. This may lead to inconsistent filtering if callers use different strings for the same source type. A source registry (parallel to tag/attr registries) could be added in v2.

### F-7: Project field vs. project tag — redundancy
The project value is stored in two places: as a first-class column on the neuron record and as an auto-tag in the tag registry. The column enables direct equality filtering (`--project`). The tag enables tag-based filtering and is included in the embedding input. This redundancy is intentional and required by the requirements, but implementers should ensure both are always populated from the same value at write time and that neither can drift.

### F-8: `memory neuron update` has no `--status` flag
There is no way to change a neuron's status to `archived` via `neuron update`. Archiving goes only through `neuron archive`. This is consistent with treating archiving as a lifecycle event distinct from content mutation. Implementers should not add a `--status` flag to `update` without explicit user approval, as it would create two paths to archive.
