# Spec #13 — Metadata & Integrity

## Purpose

This spec covers DB-level metadata tracking, vector dimension enforcement, config/DB drift detection on startup, and the model-change stale-vector marking flow. It also covers the `memory meta` noun and its two verbs (`stats`, `check`). Metadata & Integrity is the watchdog layer that ensures the running config and the live DB are in agreement before any destructive or embedding-dependent operation proceeds. Without it, a user who swaps the embedding model in config would silently corrupt the vector index by mixing vectors from different embedding spaces.

Schema versioning and automatic migrations are out of scope here — those are owned by Spec #3.

---

## Requirements Traceability

Addresses `REQUIREMENTS.md §9 Metadata & Integrity` except schema versioning (§9 bullet 5, owned by #3):

- DB-level metadata tracks: model name, vector dimensions, neuron/vector stats — §9 bullet 1
- Vector dimension enforcement — all vectors must match configured dimensions — §9 bullet 2
- Config/DB drift detection on startup — compare config.json against DB metadata, warn and block inconsistent operations — §9 bullet 3
- Model change: updating model in config marks all vectors stale — §9 bullet 4

Also traces to:
- §7.1 Grammar (noun `meta`, verbs `stats` and `check`) — meta noun implied by §9 CLI references
- §8 Embedding (model name and dimensions are sourced from the embedding config and model loader)

---

## Dependencies

- **#2 Config & Initialization** — the running config object is the source of truth for `embedding.model_path` and `embedding.dimensions`. All drift comparisons are config vs. DB.
- **#3 Schema & Migrations** — the `db_metadata` table (key-value store) must exist before metadata can be read or written. Also, the `neurons` and `vec_neurons` tables must exist to compute stats.
- **#5 Embedding Engine** — model identity (model name, dimensions) is interrogated from the loaded model at init time and written into DB metadata. The embedding engine provides the canonical source for these values at write time.

---

## Behavior

### 13.1 — DB Metadata Table Contract

The `db_metadata` table (defined in Spec #3) is a simple key-value store. This spec owns the following keys:

| Key | Type | Description |
|-----|------|-------------|
| `embedding_model_name` | string | Basename of the GGUF model file, e.g. `nomic-embed-text-v1.5.Q8_0.gguf`. Written when the first vector is stored. |
| `embedding_dimensions` | integer (stored as string) | Vector dimensionality in use when vectors were first written, e.g. `768`. Written when the first vector is stored. |
| `vectors_marked_stale_at` | ISO 8601 UTC timestamp | Set when a model change is detected and all vectors are marked stale. Cleared (deleted) after a successful full re-embed. |
| `last_integrity_check_at` | ISO 8601 UTC timestamp | Updated every time `memory meta check` is run successfully. |

These keys are read and written only by Spec #13 logic. Spec #3 creates the table; this spec populates it.

The `embedding_model_name` is the basename (filename only, no directory path) of the model file. This allows the model to be moved to a different directory without triggering a false drift detection, as long as the filename is the same.

### 13.2 — Startup Integrity Check (automatic, every invocation)

On every CLI invocation that touches the DB (all commands except `memory init`, `memory help`, and top-level `--help`), after config is loaded (#2) and the schema is verified (#3), the startup integrity check runs automatically before any command logic executes.

The startup check is a read-only comparison. It never blocks indefinitely. If the DB metadata table is empty (i.e., no vectors have ever been written), the check passes silently — there is nothing to compare yet.

**Startup check sequence:**

1. **Read DB metadata:** Load `embedding_model_name` and `embedding_dimensions` from `db_metadata`. If both keys are absent, skip to step 5 (no vectors ever written — no drift possible).

2. **Extract config model name:** Derive the model name from `config.embedding.model_path` using basename extraction (filename only, no directory). This is the "config side" of the comparison.

3. **Compare model names:** If the config model name differs from the DB `embedding_model_name`, this is a model drift condition (see §13.3).

4. **Compare dimensions:** If `config.embedding.dimensions` differs from the DB `embedding_dimensions` integer value, this is a dimension drift condition (see §13.4).

5. **Check stale flag:** If `vectors_marked_stale_at` is present in `db_metadata`, warn the user (see §13.5).

6. **Pass:** If none of the above conditions triggered a block, the startup check passes and the command proceeds normally.

The startup check adds negligible latency — it is a single SQL read of a small key-value table.

### 13.3 — Model Drift Detection and Stale-Vector Marking

A model drift condition occurs when the config's embedding model name differs from the model name recorded in `db_metadata` at the time vectors were first written.

**On model drift detection during startup check:**

1. Emit a warning to stderr:
   ```
   WARNING: Embedding model mismatch.
     DB was embedded with: <db_embedding_model_name>
     Config now specifies:  <config_model_name>
   All existing vectors are now marked stale and will not be used in vector search
   until re-embedded. Run 'memory neuron re-embed --all' to re-embed all neurons.
   Run 'memory meta check' for full details.
   ```

2. Mark all existing vectors stale by setting the `vectors_marked_stale_at` key in `db_metadata` to the current UTC timestamp.

3. Update `db_metadata` keys `embedding_model_name` and `embedding_dimensions` to reflect the new config values. The DB metadata now reflects the config — future startups will not re-trigger model drift unless the config changes again.

4. **Block vector-dependent operations for this invocation.** Commands that require valid vectors — specifically vector search and heavy search — receive an error exit (code 2) with message:
   ```
   Error: Vectors are stale due to model change. Run 'memory neuron re-embed --all'
   before using vector search. BM25 search is still available via 'memory neuron search --bm25-only'.
   ```
   Commands that do not use vectors (neuron add, tag management, edge management, BM25-only search, meta commands) are not blocked.

5. The model drift detection and stale-marking is idempotent: if `vectors_marked_stale_at` is already set (stale was previously marked), re-triggering model drift does not overwrite the timestamp with a later one — it leaves the original timestamp. This preserves the "when did stale begin" record.

**What "stale" means for a vector:**

A vector is stale if it was computed with a different model than the one currently configured. Stale vectors are present in the `vec_neurons` table but must not be used in vector similarity search. The `vectors_marked_stale_at` flag in DB metadata is the global stale indicator for this purpose — it signals that the entire vector index is unreliable, not individual rows. Per-row staleness tracking (for partial re-embed scenarios) is owned by Spec #5 and #6.

### 13.4 — Dimension Drift Detection

A dimension drift condition occurs when `config.embedding.dimensions` differs from the integer stored in `db_metadata.embedding_dimensions`.

Dimension drift is a hard block regardless of whether vectors are stale. The configured dimensions no longer match what is stored.

**On dimension drift detection during startup check:**

1. Emit an error to stderr:
   ```
   ERROR: Vector dimension mismatch.
     DB vectors have <db_dimensions> dimensions.
     Config specifies   <config_dimensions> dimensions.
   This is a critical integrity error. Check your config and model.
   If you have changed models, ensure 'embedding.dimensions' in config matches
   the new model's output dimensions.
   ```

2. Exit with code 2. The command does not proceed.

Dimension drift is more severe than model drift: it indicates that even if re-embedding were attempted with the current config, the dimensions would not match what the DB expects from the vector index schema. This requires explicit user intervention (either correcting the config or migrating the schema).

**Exception:** If both model name and dimensions differ simultaneously (a clean model swap where dimensions also changed), both conditions are reported. The dimension drift error is shown first and takes precedence — exit code 2.

### 13.5 — Stale-Vector Warning on Startup

If `vectors_marked_stale_at` is present in `db_metadata` but the model names now match (i.e., a previous stale-marking occurred and the model has not been changed again), emit a reminder on stderr:

```
WARNING: Vectors were marked stale on <vectors_marked_stale_at>.
Vector search will be degraded or unavailable until re-embedding is complete.
Run 'memory neuron re-embed --all' to fix.
```

The command still proceeds. This is a warning, not a block (the model is now consistent, just not all neurons have been re-embedded yet).

Vector-dependent operations that encounter a neuron with a null or stale vector silently fall back to BM25 for that neuron. They do not error per-neuron. The global warning on startup is sufficient.

### 13.6 — First-Vector Write: Seeding DB Metadata

When the very first vector is written to `vec_neurons` (at neuron-add time, owned by Spec #6), the metadata layer must seed the DB metadata. This is not optional — it must happen atomically with the first vector insert.

The values seeded:

- `embedding_model_name`: basename of `config.embedding.model_path`
- `embedding_dimensions`: value of `config.embedding.dimensions` as a string integer

Subsequent vector writes do not update these keys. They are set once and serve as the reference for all future drift detection.

If for any reason these keys are already present (e.g., two agents racing to write the first vector under concurrent access), the existing values are preserved — do not overwrite.

### 13.7 — `memory meta stats` Command

**Synopsis:** `memory meta stats [--format json|text]`

Returns a JSON or text report of the current DB state. This command always executes the startup check first (§13.2) and may emit warnings to stderr before returning stats to stdout.

**Fields returned:**

```
db_path                  string    Absolute path to the DB file.
db_size_bytes            integer   Size of the DB file in bytes.
schema_version           integer   Current schema version (from db_metadata, owned by #3).
embedding_model_name     string    Model name recorded in DB metadata. Null if no vectors written yet.
embedding_dimensions     integer   Dimensions recorded in DB metadata. Null if no vectors written yet.
config_model_name        string    Model name derived from current config (basename of model_path).
config_dimensions        integer   embedding.dimensions from current config.
drift_detected           boolean   True if model name or dimensions mismatch between config and DB.
vectors_stale            boolean   True if vectors_marked_stale_at is set in DB metadata.
vectors_stale_since      string    ISO 8601 timestamp of stale marking. Null if not stale.
neuron_count             integer   Total number of neurons in the neurons table.
vector_count             integer   Number of neurons with a non-null, non-stale vector in vec_neurons.
stale_vector_count       integer   Number of neurons whose vectors are stale (embedded with old model).
never_embedded_count     integer   Number of neurons that have never been embedded (blank vector).
tag_count                integer   Total distinct tags in the tag registry.
edge_count               integer   Total edges in the edges table.
last_integrity_check_at  string    ISO 8601 timestamp of last 'memory meta check' run. Null if never run.
```

`neuron_count` is a `COUNT(*)` from the neurons table.
`vector_count` counts neurons where a vector row exists in `vec_neurons` AND `vectors_stale_since` is not set globally.
`stale_vector_count` is the count of neurons with a vector row where the vector was computed before `vectors_marked_stale_at` (i.e., the neuron's `vector_updated_at` timestamp is earlier than `vectors_marked_stale_at`). If `vectors_marked_stale_at` is not set, `stale_vector_count` is 0.
`never_embedded_count` counts neurons that have no entry in `vec_neurons` at all.

**JSON output example:**
```json
{
  "db_path": "/Users/alice/.memory/memory.db",
  "db_size_bytes": 4194304,
  "schema_version": 1,
  "embedding_model_name": "nomic-embed-text-v1.5.Q8_0.gguf",
  "embedding_dimensions": 768,
  "config_model_name": "nomic-embed-text-v1.5.Q8_0.gguf",
  "config_dimensions": 768,
  "drift_detected": false,
  "vectors_stale": false,
  "vectors_stale_since": null,
  "neuron_count": 1024,
  "vector_count": 1021,
  "stale_vector_count": 0,
  "never_embedded_count": 3,
  "tag_count": 47,
  "edge_count": 312,
  "last_integrity_check_at": "2026-03-10T14:22:00Z"
}
```

Exit code: 0 on success, 2 on any DB read error.

### 13.8 — `memory meta check` Command

**Synopsis:** `memory meta check [--format json|text]`

Performs an exhaustive integrity check of the DB and reports all anomalies. This is a read-only diagnostic command. It does not repair anything. It does not modify the DB.

**Checks performed in order:**

1. **DB file accessible:** The DB file exists and is readable by the current process.
2. **Schema version valid:** The schema version in `db_metadata` matches a known version (Spec #3 responsibility, but check reports it).
3. **Config/DB model name match:** Same comparison as startup check §13.2 step 3.
4. **Config/DB dimension match:** Same comparison as §13.2 step 4.
5. **Stale vector flag:** Whether `vectors_marked_stale_at` is set.
6. **Orphaned vector rows:** Rows in `vec_neurons` that have no corresponding row in the `neurons` table. These are ghost vectors.
7. **Orphaned edge rows:** Rows in `edges` where `source_id` or `target_id` does not exist in `neurons`. These are dangling edges.
8. **Orphaned FTS rows:** Rows in `neurons_fts` that have no corresponding row in `neurons` (and vice versa — neurons missing from FTS). Mismatch indicates trigger failure.
9. **Dimension consistency:** Spot-check a sample of up to 100 vectors from `vec_neurons`: verify that each stored vector blob has the expected byte length for `embedding_dimensions` float32 values (i.e., `embedding_dimensions * 4` bytes). Report any vectors with wrong dimension.

**Output fields:**

```
status              string    "ok" or "issues_found"
checks_passed       integer   Count of checks that passed.
checks_failed       integer   Count of checks that failed or found issues.
issues              array     List of issue objects (see below).
last_checked_at     string    ISO 8601 UTC timestamp of this check run.
```

Each issue object:
```
check               string    Name of the check (e.g., "orphaned_vector_rows")
severity            string    "error" or "warning"
message             string    Human-readable description of the issue.
count               integer   Number of affected rows (where applicable). Null if not row-based.
```

After a successful run of `memory meta check`, update `last_integrity_check_at` in `db_metadata`.

Exit code: 0 if status is "ok", 1 if status is "issues_found", 2 on DB read error.

### 13.9 — Vector Dimension Enforcement on Write

Every time a vector is written to `vec_neurons` — whether at neuron-add time, batch re-embed, or import — the vector's dimension must be verified against `config.embedding.dimensions` before the write is attempted.

If the vector length does not match `config.embedding.dimensions`, the write is rejected with exit code 2:
```
Error: Vector dimension mismatch on write. Expected <config_dimensions>, got <actual_dimensions>.
This should not happen if using the configured model. Check embedding engine.
```

This is a defensive check — the embedding engine (Spec #5) should always return vectors of the configured dimensions. The check here is a last-resort safeguard.

### 13.10 — Clearing the Stale Flag

The `vectors_marked_stale_at` flag in `db_metadata` is cleared (key deleted) when a full re-embed completes successfully. "Full re-embed" means `memory neuron re-embed --all` ran to completion with zero errors. This is owned by Spec #5 (batch re-embed) but is noted here as the clearing condition.

If a partial re-embed runs (`memory neuron re-embed` without `--all`), the stale flag is not cleared even if all currently-stale neurons have been re-embedded. Only `--all` guarantees completeness and clears the flag.

---

## Constraints

- The startup integrity check must complete in under 10ms. It is a key-value lookup on a small table — no full-table scans.
- `memory meta check` is allowed to take longer (it does orphan checks and spot sampling) but must complete within 5 seconds on a DB with up to 100,000 neurons.
- The metadata layer must not load the embedding model. Model identity is derived from config (basename of model_path) and from `db_metadata`. The model is never loaded for metadata purposes.
- All metadata reads and writes use the same SQLite connection as the rest of the command. No separate connection.
- Metadata writes (seeding at first vector write, stale marking) must be atomic with their triggering operation (first insert, model drift detection). Use SQLite transactions.
- The startup integrity check is read-only. It does not acquire a write lock unless a model drift condition is detected (which triggers stale marking).
- `memory meta stats` and `memory meta check` follow the standard output format contract from Spec #1 (JSON default, text with `--format text`, exit codes 0/1/2).

---

## Edge Cases

### EC-1: DB has never had any vectors written
`db_metadata` contains no `embedding_model_name` or `embedding_dimensions` keys. The startup check skips drift detection silently. `memory meta stats` returns null for those fields, 0 for all counts. `memory meta check` reports no dimension or drift issues.

### EC-2: Config `embedding.model_path` is set but the model file does not exist
The startup check derives the model name from the path (basename only) without loading the model file. If the file doesn't exist, the basename is still computable. The startup check proceeds. The embedding engine (Spec #5) will error when the model is actually loaded for an embedding operation — that is outside this spec's scope.

### EC-3: User manually edits config to change only `embedding.dimensions` without changing the model
Dimension drift is detected. Exit code 2. This is treated as a configuration error (the user has set a dimension value that conflicts with what was used to build the existing vector index). The user must either revert `embedding.dimensions` to match the DB, or clear the vector index and re-embed.

### EC-4: User changes the model filename to a different quantization of the same model (e.g., Q4_K_M instead of Q8_0)
Model drift is detected because the basename differs. All vectors are marked stale. The dimensions field in the new config must be checked — if it also changed (different quant at different Matryoshka dimension), dimension drift fires too. This is correct behavior: different quantizations produce different embeddings that cannot be mixed.

### EC-5: `memory meta check` run on a fresh (never-used) DB
All checks pass. orphan checks return 0. Dimension checks have nothing to sample. Status: "ok" with zero issues.

### EC-6: Two concurrent agents both write the first vector simultaneously
Both attempt to seed `db_metadata`. The "preserve existing values, do not overwrite" rule (§13.6) ensures idempotent behavior under SQLite's serialized write model (WAL mode, busy timeout from Spec #3). One agent wins the transaction; the other reads the already-seeded values. Both see consistent metadata.

### EC-7: `vectors_marked_stale_at` is set but re-embed was only partially completed before process was killed
Partial re-embed does not clear the stale flag. On next startup, stale warning is still emitted. The user must re-run `memory neuron re-embed --all` to completion.

### EC-8: User changes model path to point to a different model but keeps the same filename
Model name (basename) comparison passes (same filename). However, if the new model produces different-dimension vectors, dimension drift will be detected. If dimensions are the same but the model is semantically different, no drift is detected. This is a known limitation of filename-based identity — flagged as Finding F-2.

### EC-9: `memory meta check` with orphaned FTS rows but no orphaned neuron rows
Mismatch in FTS trigger behavior (e.g., a trigger failed silently). Reported as a "warning" severity issue, not "error", since data is not lost — it is only missing from the full-text index.

### EC-10: `memory meta stats` called while another agent is actively writing neurons
Stats are read under SQLite's snapshot isolation (WAL mode). The counts reflect a consistent point-in-time snapshot. No locking is required beyond what SQLite provides.

### EC-11: `embedding_dimensions` in DB metadata is corrupt (e.g., stored as a non-integer string)
At load time, if the value cannot be parsed as an integer, treat it as a dimension drift condition with message:
```
WARNING: DB metadata 'embedding_dimensions' value is not a valid integer: '<value>'.
Treating as dimension drift.
```
Exit code 2 (dimension drift).

---

## Findings

### Finding F-1: Stale marking is global, not per-neuron
The spec marks all vectors globally stale via a single `vectors_marked_stale_at` timestamp, rather than updating a `stale` flag on each individual vector row. This design was chosen because model drift affects ALL vectors (they are all in the wrong embedding space relative to the new model). A per-neuron stale flag would imply partial validity which does not exist in a model-swap scenario. However, the per-row `vector_updated_at` timestamp (owned by #5/#6) is still used to count stale vectors in `meta stats` by comparing against the global stale timestamp. These two tracking mechanisms coexist.

### Finding F-2: Model identity via filename basename is fragile
Using the model filename as identity means two things:
1. Renaming the model file (but keeping the same contents) triggers false drift.
2. Replacing a model file with different contents but the same filename does not trigger drift.

A content-based identity (e.g., SHA256 of the model file) would be more robust but requires hashing a 140 MiB file at startup — unacceptable latency. The requirements do not specify the mechanism for model identity. Basename is the pragmatic choice. This is flagged for user awareness.

### Finding F-3: `memory meta check` orphan checks could be slow on large DBs
Orphan checks (`vec_neurons` without `neurons`, `edges` without `neurons` in both directions) require LEFT JOINs or NOT EXISTS queries that may be slow without proper indexes. The Spec #3 schema must include indexes on `vec_neurons.neuron_id`, `edges.source_id`, and `edges.target_id` for these to complete within the 5-second budget at 100K neurons. This is a dependency constraint on Spec #3 that should be verified.

### Finding F-4: Dimension enforcement on write vs. enforcement at the schema level
The vec0 virtual table schema defines the vector dimension (e.g., `embedding float[768]`). SQLite-vec will likely reject vectors of wrong dimensions at the SQL level anyway. The application-level check in §13.9 is redundant but provides a cleaner error message. The behavior when sqlite-vec rejects a wrong-dimension vector is unspecified here — this is flagged as an implementation detail to verify against sqlite-vec's actual behavior.

### Finding F-5: `memory meta check` severity classification
The spec classifies orphaned FTS rows as "warning" and orphaned vector/edge rows and dimension mismatches as "error". The rationale: orphaned FTS rows are a search quality degradation but not data loss; orphaned vectors/edges represent structural inconsistency. This classification is a judgment call not explicitly specified in requirements.

### Finding F-6: No automatic repair in `memory meta check`
The requirements say "warn and block inconsistent operations" but do not specify repair. `memory meta check` is diagnostic only. No automatic repair command is specified in v1. A future `memory meta repair` command could address orphan cleanup, but it is not in scope. Flagged in case the user wants a repair verb.
