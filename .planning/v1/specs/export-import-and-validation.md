# Spec #12 — Export, Import & Validation

## Purpose

This spec covers the two symmetric I/O operations on the memory graph: exporting neurons (with their edges, tags, attributes, and vectors) to a portable JSON file, and importing that file back into a memory database with strict schema enforcement. It also covers the validate-only dry-run mode, which runs all import checks without writing anything to the DB.

Export and import are the only sanctioned method for moving memory data between databases — or for archiving a subset of the graph. Backup (copying the `.db` file) is documented separately and is not a CLI feature.

---

## Requirements Traceability

| Requirement | Source |
|---|---|
| Export neurons by tag filter or all: `memory neuron export --tags X --format json` | §7.5 Export/Import |
| Import with strict schema enforcement: validates structure, tag registry consistency, vector dimensions, edge references | §7.5 Export/Import |
| Validate-only dry run mode (`--validate-only` or `--dry-run`) | §7.5 Export/Import |
| Backup = copy the .db file (documented, not a CLI feature) | §7.5 Export/Import |
| Export/import format is JSON with full neuron data including tags, attributes, edges, and vectors | §7.5 Export/Import |
| Opaque storage — AI agents cannot access storage directly; CLI is the only interface | §2 Storage |
| Design must not preclude multi-DB / sharding in future versions | §2 Storage |
| Tag registry: managed enum of known tags, stored as integer IDs; tags normalized to lowercase on write | §5 Tags |
| Vector dimension enforcement — all vectors must match configured dimensions | §9 Metadata & Integrity |
| Embedding model: nomic-embed-text-v1.5, 768 dimensions | §8 Embedding |
| Default output format: JSON; alternative: plain text; exit codes 0/1/2 | §7.4 Output Format |

---

## Dependencies

- **#6 Neuron CRUD & Storage** — export reads neuron records; import writes neuron records
- **#7 Edge Management** — export reads edge records; import writes edge records; import validates that edge endpoints exist among the imported neurons
- **#4 Tag & Attribute Registries** — export resolves tag/attribute IDs to names; import validates tag names against or extends the target DB registry
- **#5 Embedding Engine** — dimension validation on import requires knowing the configured vector dimensions

---

## Behavior

### 1. Export

#### 1.1 Command Form

```
memory neuron export [--tags TAG1,TAG2] [--tags-any TAG1,TAG2] [--format json] [--output FILE] [--include-vectors]
```

- `--tags` applies AND filtering (neuron must have all listed tags). Normalized to lowercase.
- `--tags-any` applies OR filtering (neuron must have at least one listed tag). Normalized to lowercase.
- `--tags` and `--tags-any` are mutually exclusive in a single invocation.
- With no tag filter: all neurons in the DB are exported.
- `--format json` is the only supported format in v1. If omitted, JSON is used (it is the only format).
- `--output FILE` writes the export to a file path. If omitted, output goes to stdout.
- `--include-vectors` includes raw embedding vectors in the export. If omitted, vectors are excluded by default (see §Finding F-1 and §1.3).

#### 1.2 What Is Exported Per Neuron

Each exported neuron record includes:
- `id` — the neuron's internal integer ID from the source DB
- `content` — the text content of the neuron
- `created_at` — creation timestamp (ISO 8601)
- `updated_at` — last update timestamp (ISO 8601)
- `project` — project name auto-captured at write time
- `source` — source field (may be null)
- `tags` — list of tag name strings (resolved from IDs, normalized lowercase)
- `attributes` — map of attribute key strings to value strings (resolved from IDs)
- `vector` — the embedding vector as a list of floats, or `null` if not yet embedded; only present when `--include-vectors` is specified
- `vector_model` — the model name used to produce the vector, or `null`; only present when `--include-vectors` is specified

#### 1.3 Vector Export Behavior

Vectors are large (768 floats × 4 bytes = ~3 KB each) and can make exports unwieldy. By default they are omitted. When `--include-vectors` is specified:
- Neurons with a computed vector emit the vector as a JSON array of floats.
- Neurons without a computed vector emit `"vector": null`.
- The export envelope includes the model name and dimension count from DB metadata (see §2).

#### 1.4 Edge Export

Edges among the exported neurons are included in the export envelope (not per-neuron). An edge is included if and only if both its source and target neurons are present in the export. Edges to neurons outside the export set are silently omitted.

Each exported edge record includes:
- `source_id` — integer ID of the source neuron (from source DB)
- `target_id` — integer ID of the target neuron (from source DB)
- `reason` — the edge reason string
- `weight` — the edge weight float
- `created_at` — creation timestamp (ISO 8601)

#### 1.5 Export Envelope (Top-Level JSON Structure)

```json
{
  "memory_cli_version": "1",
  "export_format_version": "1",
  "exported_at": "<ISO 8601 timestamp>",
  "source_db_vector_model": "<model name or null>",
  "source_db_vector_dimensions": <integer or null>,
  "vectors_included": <true or false>,
  "neuron_count": <integer>,
  "edge_count": <integer>,
  "neurons": [ ... ],
  "edges": [ ... ]
}
```

- `memory_cli_version` is the version of the memory-cli that produced the export.
- `export_format_version` is a schema version for the export format itself (separate from the DB schema version).
- `source_db_vector_model` and `source_db_vector_dimensions` are read from DB metadata; present even when `vectors_included` is false, to allow the importing DB to detect model mismatches before attempting a re-embed.
- `neuron_count` and `edge_count` are the counts of records in the `neurons` and `edges` arrays respectively, for quick integrity checking.

#### 1.6 Tag and Attribute Resolution

Tags and attributes are exported as their string names (not integer IDs). This ensures portability: the target DB may have different ID assignments for the same tag names.

#### 1.7 Ordering

Neurons in the export are ordered by `created_at` ascending. Edges are ordered by `created_at` ascending. Ordering is deterministic for reproducible diffs.

#### 1.8 Exit Codes for Export

- 0: export completed successfully (even if zero neurons matched the filter)
- 1: tag filter matched no neurons (no output written)
- 2: error (DB unreadable, write permission denied for output file, etc.)

Note: exporting zero neurons due to a valid but empty filter is exit code 0 (the filter was valid, it just matched nothing). See §Finding F-2.

---

### 2. Import

#### 2.1 Command Form

```
memory neuron import <FILE> [--validate-only] [--dry-run] [--on-conflict skip|overwrite|error]
```

- `<FILE>` is the path to a JSON export file produced by `memory neuron export`. Reading from stdin is not supported in v1 (see §Finding F-3).
- `--validate-only` and `--dry-run` are synonyms. Either flag causes all validation checks to run without writing to the DB. The command reports what would succeed, what would fail, and why.
- `--on-conflict` controls behavior when an imported neuron's `id` already exists in the target DB. Default is `error`. Options:
  - `skip` — silently skip neurons that already exist by ID; their edges are also skipped
  - `overwrite` — replace existing neurons with imported data; edges to/from those neurons are updated
  - `error` — abort the entire import if any ID conflict is detected (default)

#### 2.2 Validation Checks (in order)

All checks run before any writes. The full set of errors is collected and reported together, not fail-fast one at a time. Checks:

**Structural validation:**
1. The JSON is parseable and is an object (not array, null, etc.)
2. The `export_format_version` field is present and is a version this CLI can handle.
3. The `neurons` field is present and is an array.
4. The `edges` field is present and is an array.
5. Each neuron record has all required fields: `id`, `content`, `created_at`, `updated_at`, `tags`, `attributes`. Missing fields are a structural error.
6. Each edge record has all required fields: `source_id`, `target_id`, `reason`, `weight`, `created_at`.
7. `content` must be a non-empty string for every neuron.
8. `created_at` and `updated_at` must be valid ISO 8601 timestamps.
9. `tags` must be an array of strings. Each tag name, after normalization to lowercase, must be non-empty.
10. `attributes` must be a JSON object with string keys and string values.
11. `weight` on edges must be a finite float (not NaN, not Infinity).

**Count integrity check:**
12. The actual count of records in `neurons` matches `neuron_count`. The actual count in `edges` matches `edge_count`. Mismatch is a structural error.

**Neuron ID uniqueness within the file:**
13. All `id` values within the `neurons` array are unique. Duplicate IDs within the file are an error.

**Edge referential integrity within the file:**
14. Every `source_id` and `target_id` in the `edges` array corresponds to an `id` in the `neurons` array. Edges that reference neuron IDs not present in the file are a referential integrity error.

**Tag registry validation:**
15. Each tag name (normalized lowercase) is checked against the target DB's tag registry. Unknown tag names are not an error — they will be auto-created on import (consistent with how `memory neuron add` handles new tags). This is not a validation failure.

**Vector dimension validation (only when `vectors_included` is true in the file):**
16. If the file's `source_db_vector_dimensions` differs from the target DB's configured vector dimensions, this is an error. The import cannot proceed because vectors from a different dimension model are incompatible.
17. If the file's `source_db_vector_model` differs from the target DB's configured model, this is a warning (not an error) — but see §Finding F-4 for discussion of whether this should be an error.

**ID conflict check:**
18. If `--on-conflict error` (the default), any neuron `id` that already exists in the target DB is reported as a conflict error, and the entire import is blocked.

#### 2.3 Import Write Sequence (when validation passes)

The import is transactional: all writes succeed or all fail.

Order of writes:
1. Create any new tag names that don't already exist in the target DB tag registry.
2. Create any new attribute keys that don't already exist in the target DB attribute registry.
3. Write neurons in order. For each neuron:
   - Resolve tag names to IDs in the target DB (using newly created IDs from step 1).
   - Resolve attribute keys to IDs in the target DB (from step 2).
   - Insert the neuron record with the original `id` from the export file, preserving the source `id` values.
   - If `vectors_included` is true and the neuron has a non-null vector, write the vector to the vec table.
   - If `vectors_included` is false, or the neuron's vector is null, the neuron is stored without a vector (it will be treated as "never embedded" / blank vector, eligible for batch re-embed later).
   - FTS5 sync occurs via triggers (as defined in #3 Schema).
4. Write edges in order using the original `source_id` / `target_id` values (which now exist in the target DB from step 3).

#### 2.4 Import Output

On successful completion:
```json
{
  "imported_neurons": <count>,
  "imported_edges": <count>,
  "new_tags_created": <count>,
  "new_attrs_created": <count>,
  "skipped_neurons": <count>,
  "skipped_edges": <count>
}
```

On validation failure (including `--validate-only` runs):
```json
{
  "valid": false,
  "errors": [
    { "type": "structural|referential|dimension|conflict", "message": "..." },
    ...
  ],
  "warnings": [
    { "type": "model_mismatch", "message": "..." },
    ...
  ]
}
```

On `--validate-only` with no errors:
```json
{
  "valid": true,
  "would_import_neurons": <count>,
  "would_import_edges": <count>,
  "would_create_tags": <count>,
  "would_create_attrs": <count>,
  "warnings": []
}
```

#### 2.5 Exit Codes for Import

- 0: import completed successfully (or `--validate-only` and all checks passed)
- 1: `--validate-only` and validation found errors (nothing was written)
- 2: error (file not found, JSON unparseable, fatal DB error, validation failure on live import)

---

### 3. Backup (Documentation Only)

The backup strategy for memory-cli is to copy the SQLite `.db` file. This is the canonical, reliable backup method. It is not exposed as a CLI command.

The CLI documentation (help text for `memory meta`) must include a note explaining:
- The DB path (from config, or `~/.memory/memory.db` by default)
- That copying the file while no CLI process is running produces a valid backup
- That WAL mode files may have associated `-wal` and `-shm` sidecar files that should also be copied

---

## Constraints

1. Export and import are purely `memory neuron` sub-commands. There is no separate `memory export` or `memory import` noun.
2. JSON is the only supported export format in v1. No CSV, SQLite dump, or binary formats.
3. Import does not re-embed neurons automatically. Neurons imported without vectors are marked for future re-embedding by the batch re-embed operation (spec #5).
4. Import preserves source neuron `id` values. The target DB must not have ID conflicts unless `--on-conflict skip` or `overwrite` is specified.
5. Partial imports are not supported. Import is all-or-nothing within a transaction.
6. Export does not lock the DB for writing during export. It reads a consistent snapshot via SQLite's transaction isolation. Concurrent writes during export may or may not be included depending on timing.
7. The export file is not signed or checksummed. Tamper detection is out of scope for v1.
8. Tag IDs from the source DB are NOT preserved in the export. Tags are exported and imported by name only. The target DB assigns its own IDs.
9. Attribute key IDs from the source DB are NOT preserved. Same pattern as tags.
10. The `--format` global flag (from #1 CLI Dispatch) applies to the import result output (JSON vs plain text), not to the export file format.

---

## Edge Cases

1. **Export with zero matching neurons:** Valid operation. Produces a well-formed envelope with `"neuron_count": 0`, `"edge_count": 0`, empty arrays. Exit code 0.

2. **Export of a neuron with no edges:** The `edges` array will be empty or contain only edges between other exported neurons. The neuron is fully exported without edges.

3. **Export of a neuron with edges to non-exported neurons:** Those edges are silently dropped from the export. The neuron itself is exported without those edges.

4. **Import of a file with no neurons:** Allowed. Produces a result of zero imports. Not an error.

5. **Import of a file with neurons but no edges:** Allowed. Neurons are imported, edge count is zero.

6. **Import where all neurons conflict under `--on-conflict skip`:** All neurons skipped, all edges skipped. Exit code 0 (the operation completed successfully — it just did nothing).

7. **Import where `vectors_included` is false but target DB has vectors for some conflicting IDs:** Under `--on-conflict overwrite`, the existing vector in the target DB is preserved (since the import file has no vector to overwrite with). The neuron content and metadata are overwritten but the existing vector is retained as-is.

8. **Import where `vectors_included` is true but a specific neuron's vector is null:** That neuron is imported without a vector. It is treated as never-embedded.

9. **Import file produced by a newer version of memory-cli with a higher `export_format_version` than this CLI understands:** This is a hard error. The CLI cannot safely import a format it doesn't know.

10. **Import file produced by an older version with a lower `export_format_version`:** The CLI attempts to import it. If the older format is missing fields that can be defaulted (e.g., a missing `weight` field defaults to 1.0), the import proceeds. If required fields are missing, structural validation fails.

11. **DB write permission error mid-import:** The transaction is rolled back. Nothing is written. Exit code 2.

12. **Very large export files (e.g., 100K neurons):** Export streams records to the output file rather than building the full JSON in memory. Import reads and validates the full file before writing (necessary for referential integrity check). Memory pressure from large imports is acknowledged as a v1 limitation.

13. **Tags in the export file that conflict with existing tags in the target DB by name but were written with different casing in the source:** All tags are normalized to lowercase at export time and at import time, so casing conflicts cannot occur.

14. **Neuron `content` field is an empty string in the import file:** This is a structural validation error (see §2.2, check 7). Empty content is not allowed.

15. **Circular edges in the import file (A→B and B→A):** Valid. Circular references are permitted in the graph (§2.2 Edges in requirements). Referential integrity check passes as long as both A and B are in the neurons array.

---

## Findings

**F-1: Vector export should be opt-in.**
The requirements say "full neuron data including tags, attrs, edges, and vectors." However, exporting 768 floats per neuron by default makes export files very large (a 10K neuron DB with vectors = ~30 MB of floats before JSON overhead). Recommendation: vectors are excluded by default and included via `--include-vectors`. This is a clarification request — the requirements do not explicitly address default behavior for vectors in exports. Implemented as `--include-vectors` being opt-in pending user confirmation.

**F-2: Exit code for zero-neuron export.**
The requirements specify exit codes 0=success/found, 1=not found, 2=error. It is ambiguous whether a tag-filtered export that matches no neurons should return exit code 0 (success — the export ran) or 1 (not found — no matches). This spec treats it as exit code 0 because the operation itself succeeded; the caller can inspect `neuron_count` to know if anything was exported. If the user wants 1=not-found semantics for empty exports, this is a design decision to flag.

**F-3: Stdin import is not supported.**
The requirements do not specify whether import reads from a file path or from stdin. This spec requires a file path argument. Stdin support would be useful for pipeline use but adds complexity (validation of streaming JSON). Deferred to a finding — stdin import is not implemented in v1.

**F-4: Vector model mismatch on import — warning or error?**
If the export file has vectors from model X but the target DB is configured for model Y, the vectors are semantically incompatible (different embedding space). The spec currently treats this as a warning, not an error, because the user might intend to import the neuron data and re-embed later. However, if vectors are included in the import (`vectors_included: true`), writing incompatible vectors to the DB would corrupt the vector search index. Recommendation: if `vectors_included` is true AND model names differ, this should be a hard error. If `vectors_included` is false (vectors not imported), model mismatch is informational only. This needs a decision from the project owner.

**F-5: ID preservation as an import constraint.**
The spec preserves source neuron IDs on import to ensure edge referential integrity within the import file. This means the target DB must accommodate external integer IDs, which may conflict with the auto-increment sequence. If the target DB already has neurons, collisions are possible. The `--on-conflict` flag handles this, but the behavior of the auto-increment sequence after import (e.g., does SQLite's autoincrement know to skip the imported IDs?) is a schema-level concern for spec #3. Flagged here for coordination.

**F-6: Export includes only outbound edges vs. all edges.**
The requirements say "edges" without specifying direction. An edge between neurons A and B is included when both are in the export set — regardless of which is source and which is target. This spec follows that interpretation. If edges are stored bidirectionally in the DB (one row per direction), the export must deduplicate. If edges are stored as directed (one row, source→target), the export includes all edges where both endpoints are in the export set. The schema spec (#3) determines storage; this spec assumes the export query does the right thing regardless. Coordination with #3 needed.

**F-7: `--tags` and `--tags-any` on export — same syntax as neuron list/search.**
Export uses the same tag filtering flags as other neuron operations. The behavior (AND vs OR, lowercase normalization) is consistent with the tag filtering spec in #4. No new flag semantics are introduced.
