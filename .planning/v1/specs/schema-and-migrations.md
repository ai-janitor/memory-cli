# Spec #3 — Schema & Migrations

## Purpose

This spec defines the complete SQLite database schema for memory-cli: every table, virtual table, index, trigger, and pragma required. It also defines schema version tracking and the automatic migration protocol that runs on every startup before any other DB operation. All data-touching specs (#4 through #13) depend on this schema being in place. The schema is the single source of truth for all persistent data shapes.

The schema is store-agnostic: it applies identically whether the active store is global (`~/.memory/memory.db`) or project-scoped (`.memory/memory.db` discovered via ancestor walk). The store path comes from Spec #2 (Config); this spec only governs what is inside the DB file once it is open.

---

## Requirements Traceability

- `REQUIREMENTS.md §2 Storage` — graph-based storage: neurons (nodes) and edges (relationships); single-file backup; design must not preclude sharding
- `REQUIREMENTS.md §2.1 Neurons` — neurons have: content, timestamp, project, tags, source, attributes
- `REQUIREMENTS.md §2.2 Edges` — edges carry a reason and a weight (default 1.0)
- `REQUIREMENTS.md §2.3 Capture Context` — conversations link neurons; co-occurrence tracking
- `REQUIREMENTS.md §5 Tags` — tag registry with integer IDs; tags normalized to lowercase; neuron-tag junction
- `REQUIREMENTS.md §6 Attributes` — attribute key registry with integer IDs; neuron-attribute junction with values
- `REQUIREMENTS.md §8 Embedding` — 768-dim float32 vectors; vectors stored separately from neuron content; stale/blank vector tracking
- `REQUIREMENTS.md §9 Metadata & Integrity` — DB-level metadata: model name, vector dimensions, schema version; automatic migrations on startup
- `REQUIREMENTS.md §10 Edge Cases` — WAL mode for concurrent access; busy timeout for serialized writes; circular edges valid
- `REQUIREMENTS.md §4.1 Light Search` — BM25 via FTS5; vector similarity via sqlite-vec; spreading activation requires edge source/target indexes
- Research `sqlite-vec-and-fts5.md` — FTS5 porter unicode61 tokenizer; vec0 virtual table; two-step vector query pattern; triggers for FTS sync
- Research `spreading-activation-algorithm.md` — edges need source_id and target_id indexes; weight column; both directions queryable
- Research `qmd-reference-architecture.md` — FTS5 trigger sync pattern; WAL + foreign keys; two-step vec query to avoid JOIN hangs

---

## Dependencies

- `#2 Config & Initialization` — provides the resolved `db_path`; provides `embedding.dimensions` used to verify vec0 dimensionality at migration time

All other specs depend on this one. No spec may access the DB before schema initialization has completed for the current invocation.

---

## Behavior

### 3.1 — DB Connection Setup (every invocation, before schema init)

When the DB file is opened, the following connection-level settings are applied in this order before any schema work or command logic:

1. **WAL mode:** Set `PRAGMA journal_mode = WAL`. This enables concurrent reads with serialized writes. If the pragma returns a value other than `wal`, treat as a non-fatal warning (some read-only filesystems may not support WAL; this is logged but not fatal for read-only operations).

2. **Foreign key enforcement:** Set `PRAGMA foreign_keys = ON`. This enforces referential integrity on all foreign key constraints defined in the schema.

3. **Busy timeout:** Set `PRAGMA busy_timeout = 5000`. This sets a 5-second timeout before a locked write returns an error, supporting multiple agents writing concurrently.

These three pragmas are set on every connection open, every invocation, because SQLite pragmas are per-connection and are not persisted.

### 3.2 — Schema Initialization Protocol (every invocation, after connection setup)

After connection setup, before any command runs, the following sequence executes:

1. Read the current schema version from the `meta` table (see §3.8). If the `meta` table does not exist, the schema version is 0 (fresh DB).
2. Compare current schema version against the expected schema version for this binary (see §3.9 for versioning rules).
3. If current == expected: schema is up to date, proceed to command logic.
4. If current < expected: run migrations in order from (current + 1) to expected (see §3.10). After all migrations complete, update the schema version in `meta`.
5. If current > expected: the DB was created by a newer version of the CLI. Exit with code 2:
   `DB schema version <N> is newer than this CLI supports (max: <M>). Upgrade memory-cli.`
6. If the migration fails for any reason: exit with code 2:
   `Schema migration failed at version <N>: <error message>. DB may be in inconsistent state. Restore from backup.`

All migration steps for a given startup run inside a single SQLite transaction. If any step fails, the transaction is rolled back and the DB is left at its pre-migration version.

### 3.3 — Neurons Table

The `neurons` table is the primary storage for all neuron records.

**Columns:**

- `id` — integer primary key, auto-incremented. This is the stable identifier used everywhere in the system (edges, junctions, FTS rowid). Never reused after deletion.
- `content` — text, not null. The fact, concept, or statement stored in this neuron. No maximum length enforced at the DB layer (SQLite stores text as variable length). Empty string is disallowed: a check constraint requires `length(content) > 0`.
- `created_at` — integer, not null. Unix epoch in milliseconds (UTC). Set at insert time; never updated by normal operations. Used for timeline traversal and temporal decay in search.
- `updated_at` — integer, not null. Unix epoch in milliseconds (UTC). Set at insert time; updated when `content` or any attribute on the neuron changes.
- `project` — text, not null. The project name captured from the working directory or git context at write time. Stored as a plain string (not a foreign key to a registry). Empty string is disallowed: check constraint requires `length(project) > 0`.
- `source` — text, nullable. Free-form string indicating the origin of the neuron (e.g., "manual", "ingestion", a session file path). Null means origin is unrecorded.
- `embedding_updated_at` — integer, nullable. Unix epoch in milliseconds (UTC) of when the stored vector was generated. Null means the neuron has never been embedded (blank vector). When `content` is updated and `embedding_updated_at` is before `updated_at`, the vector is considered stale.
- `status` — text, not null, default `'active'`. Valid values: `'active'`, `'archived'`. A check constraint enforces only these two values. There is no `'superseded'` status at the DB layer — that is an attribute-level concern (see §3.7).

**Indexes:**

- Primary key on `id` (implicit).
- Index on `project` — for filtering neurons by project.
- Index on `created_at` — for timeline traversal (walk chronologically).
- Index on `status` — for filtering active vs. archived neurons.
- Index on `embedding_updated_at` — for batch re-embed queries that find blank or stale vectors (IS NULL, or less than `updated_at`).

**No unique constraint on content.** Duplicate content is allowed — conflicting memories both live (see §10 requirements).

### 3.4 — Edges Table

The `edges` table stores relationships between neurons.

**Columns:**

- `id` — integer primary key, auto-incremented.
- `source_id` — integer, not null. Foreign key referencing `neurons(id)`. The neuron the relationship originates from.
- `target_id` — integer, not null. Foreign key referencing `neurons(id)`. The neuron the relationship points to.
- `reason` — text, not null. A human-readable explanation of why this relationship exists. Empty string is disallowed: check constraint requires `length(reason) > 0`.
- `weight` — real, not null, default `1.0`. Modulates spreading activation strength along this edge. A check constraint enforces `weight > 0.0`. There is no upper bound on weight enforced at the DB layer.
- `created_at` — integer, not null. Unix epoch in milliseconds (UTC).

**Constraints:**

- Foreign key: `source_id` references `neurons(id)`. Deletion behavior: if the source neuron is deleted, its edges are cascade-deleted.
- Foreign key: `target_id` references `neurons(id)`. Deletion behavior: if the target neuron is deleted, its edges are cascade-deleted.
- Circular references (where `source_id == target_id`) are explicitly allowed — no check constraint prevents them. Self-referential edges are valid.
- No unique constraint on `(source_id, target_id)`. Multiple edges between the same two neurons are allowed (they may have different reasons and weights).

**Indexes:**

- Index on `source_id` — used for spreading activation neighbor lookups and edge listing by neuron.
- Index on `target_id` — used for reverse traversal (finding what points to a neuron) and cascade operations.
- Both indexes are required for the BFS spreading activation algorithm to be performant (see research `spreading-activation-algorithm.md`).

### 3.5 — Tag Registry Table

The `tags` table is a managed enum of all known tag strings, each assigned a stable integer ID.

**Columns:**

- `id` — integer primary key, auto-incremented.
- `name` — text, not null. The tag string as stored (always lowercase). Unique constraint on `name` — no duplicate tag strings.
- `created_at` — integer, not null. Unix epoch in milliseconds (UTC).

**Constraints:**

- Unique constraint on `name`.
- A check constraint requires `length(name) > 0` — empty tag strings are not allowed.
- A check constraint requires `name = lower(name)` — enforces that all stored tags are lowercase at the DB layer (defense in depth; the application layer normalizes before insert).

**Indexes:**

- Primary key on `id` (implicit).
- Unique index on `name` (implicit from unique constraint) — used for name-to-ID resolution at write time.

### 3.6 — Neuron-Tag Junction Table

The `neuron_tags` table is the many-to-many join between neurons and tags.

**Columns:**

- `neuron_id` — integer, not null. Foreign key referencing `neurons(id)`.
- `tag_id` — integer, not null. Foreign key referencing `tags(id)`.

**Constraints:**

- Primary key: composite `(neuron_id, tag_id)` — a neuron cannot have the same tag twice.
- Foreign key: `neuron_id` references `neurons(id)`, cascade delete.
- Foreign key: `tag_id` references `tags(id)`, cascade delete (if a tag is removed from the registry, all neuron-tag associations for that tag are removed).

**Indexes:**

- Primary key composite index (implicit) — supports lookup by neuron_id.
- Index on `tag_id` — supports looking up all neurons with a given tag (used by tag filtering in search).

### 3.7 — Attribute Key Registry Table

The `attr_keys` table is a managed enum of all known attribute key strings, each assigned a stable integer ID. This follows the same pattern as the `tags` table.

**Columns:**

- `id` — integer primary key, auto-incremented.
- `name` — text, not null. The attribute key name as stored. Unique constraint on `name`.
- `created_at` — integer, not null. Unix epoch in milliseconds (UTC).

**Constraints:**

- Unique constraint on `name`.
- Check constraint: `length(name) > 0`.

**Indexes:**

- Primary key on `id` (implicit).
- Unique index on `name` (implicit from unique constraint).

### 3.8 — Neuron-Attribute Junction Table

The `neuron_attrs` table is the many-to-many join between neurons and attribute key-value pairs.

**Columns:**

- `neuron_id` — integer, not null. Foreign key referencing `neurons(id)`.
- `attr_key_id` — integer, not null. Foreign key referencing `attr_keys(id)`.
- `value` — text, not null. The attribute value for this neuron/key pair. Empty string is allowed (a blank value is semantically distinct from absent).

**Constraints:**

- Primary key: composite `(neuron_id, attr_key_id)` — a neuron has at most one value per attribute key.
- Foreign key: `neuron_id` references `neurons(id)`, cascade delete.
- Foreign key: `attr_key_id` references `attr_keys(id)`. Deletion behavior: restricted (cannot delete an attribute key that is in use on any neuron).

**Indexes:**

- Primary key composite index (implicit).
- Index on `attr_key_id` — supports listing all neurons with a given attribute key.

### 3.9 — FTS5 Virtual Table

The `neurons_fts` virtual table provides full-text search over neuron content and tags using FTS5 with the porter unicode61 tokenizer.

**Definition:**

- Virtual table using the `fts5` module.
- Indexed columns: `content`, `tags_blob`.
  - `content` mirrors the `neurons.content` column.
  - `tags_blob` is a space-separated concatenation of all tag names associated with the neuron. It is not stored in the `neurons` table itself; it is assembled for FTS purposes and maintained by triggers.
- Tokenizer: `porter unicode61`. The porter stemmer handles English morphology (e.g., "running" matches "run"). The unicode61 tokenizer handles non-ASCII characters.
- `content` option: the FTS table is a "content" table backed by `neurons`. The FTS `rowid` corresponds to `neurons.id`.

**Sync triggers (INSERT):**

When a row is inserted into `neurons`, an AFTER INSERT trigger inserts a corresponding row into `neurons_fts(rowid, content, tags_blob)`. At insert time, `tags_blob` is empty (tags are associated after neuron creation). A second trigger fires after neuron-tag associations are created to refresh the FTS row with the full tags_blob.

**Sync triggers (UPDATE):**

When `neurons.content` is updated, an AFTER UPDATE trigger deletes the old FTS row (using `neurons_fts(neurons_fts, rowid, content, tags_blob) = ('delete', old.id, old_content, old_tags_blob)`) and inserts a new one with the updated content. Tags blob is recomputed from the current `neuron_tags` state at update time.

When a row is inserted or deleted from `neuron_tags`, AFTER INSERT and AFTER DELETE triggers on `neuron_tags` update the corresponding FTS row to reflect the new tags_blob. The update is performed as a delete + insert on the FTS table for the affected neuron.

**Sync triggers (DELETE):**

When a row is deleted from `neurons`, an AFTER DELETE trigger removes the corresponding FTS row using the FTS5 delete command.

**FTS5 trigger implementation detail:** FTS5 content tables require explicit triggers because SQLite does not auto-sync them. The trigger pattern for FTS5 is: `INSERT INTO neurons_fts(neurons_fts, rowid, content, tags_blob) VALUES('delete', old.id, old.content_value, old_tags_value)` followed by a regular insert. The delete step uses the special `neurons_fts` column as a command target — this is the standard FTS5 external content table pattern.

**BM25 weighting:** The FTS5 table is configured with column weights that give higher importance to `content` than `tags_blob`. The exact weight values (e.g., content=10.0, tags_blob=1.0) are a concern for Spec #8 (Light Search); this spec only establishes that two separately weighted columns exist.

### 3.10 — vec0 Virtual Table

The `neurons_vec` virtual table stores 768-dimensional float32 embedding vectors for neurons, using the sqlite-vec extension.

**Definition:**

- Virtual table using the `vec0` module (requires sqlite-vec extension loaded on connection).
- Columns:
  - `neuron_id` — integer primary key. Corresponds to `neurons.id`.
  - `embedding` — float[768]. The embedding vector for the neuron.
- The dimensionality (768) comes from `config.embedding.dimensions`. At schema creation time (migration to version 1), the vec0 table is created with the dimension value from config. If dimensions in config do not match those in the existing vec0 table (determined by querying the `meta` table, see §3.11), Spec #13 (Metadata & Integrity) handles the conflict; this spec does not re-create the table mid-migration.
- Not every neuron has a vec0 entry. A neuron with no vector in `neurons_vec` is a blank-vector neuron. The presence or absence of a row in `neurons_vec` is the authoritative indicator of whether a neuron has been embedded, cross-referenced with `neurons.embedding_updated_at`.

**Two-step query pattern (design constraint):** Queries that join `neurons_vec` with `neurons` or other tables must NOT use SQL JOINs directly against the vec0 table — this causes indefinite hangs (see research `sqlite-vec-and-fts5.md`). The vec0 table must be queried alone first (KNN query returning `neuron_id, distance`), then the resulting IDs are used to fetch from `neurons`. This is a constraint on all callers of the vec0 table, not a schema property; it is documented here because the schema design (separate vec0 table with `neuron_id` PK) is chosen to enable this pattern.

**No cascade:** There is no foreign key from `neurons_vec.neuron_id` to `neurons.id` at the vec0 level (vec0 virtual tables do not support FK constraints). Callers that delete neurons must also delete the corresponding `neurons_vec` row manually.

### 3.11 — Meta Table

The `meta` table stores DB-level metadata as key-value pairs. It is the first table created (schema version 0 to 1) and is the source of truth for schema version.

**Columns:**

- `key` — text, primary key. The metadata key name.
- `value` — text, not null. The metadata value (all values stored as text, regardless of their logical type).

**Reserved keys (written at schema creation and updated by migrations or Spec #13):**

- `schema_version` — integer stored as text. The current schema version number. This is the value read by the migration protocol (§3.2). Written as `'1'` when the schema is first created.
- `embedding_model` — the model identifier string (e.g., `'nomic-embed-text-v1.5.Q8_0.gguf'`). Written at first embed operation (Spec #5); may be null/absent before first embed.
- `embedding_dimensions` — integer stored as text. The configured embedding dimensions (e.g., `'768'`). Written at schema creation from `config.embedding.dimensions`.
- `created_at` — integer stored as text. Unix epoch in milliseconds when the DB was first initialized.
- `last_migrated_at` — integer stored as text. Unix epoch in milliseconds when the last migration ran. Updated after each migration batch.

**Schema for this table is created in migration version 1.** The migration protocol handles the bootstrap case: if the `meta` table does not exist, schema version is treated as 0 and migration to version 1 creates the `meta` table as its first act.

### 3.12 — Schema Versioning Rules

- The schema version is a monotonically increasing integer starting at 1.
- Version 1 is the baseline schema: `meta`, `neurons`, `edges`, `tags`, `neuron_tags`, `attr_keys`, `neuron_attrs`, `neurons_fts`, `neurons_vec`, and all indexes and triggers described in this spec.
- Future versions add to version 1 via numbered migrations. Each migration is identified by the target version number it produces.
- The expected schema version for the v1 binary is **1**.
- Migrations are applied atomically (see §3.2 for the single-transaction rule).

### 3.13 — Migration Steps: Version 0 to Version 1

The following objects are created in this order as part of the migration from schema version 0 (empty DB) to version 1:

1. Create `meta` table.
2. Insert `schema_version = '1'` into `meta`.
3. Insert `embedding_dimensions` from `config.embedding.dimensions` into `meta`.
4. Insert `created_at` (current time) into `meta`.
5. Create `neurons` table with all columns and check constraints.
6. Create all indexes on `neurons`.
7. Create `tags` table with all columns and check constraints.
8. Create unique index on `tags.name`.
9. Create `neuron_tags` junction table.
10. Create index on `neuron_tags.tag_id`.
11. Create `attr_keys` table with all columns and check constraints.
12. Create unique index on `attr_keys.name`.
13. Create `neuron_attrs` junction table.
14. Create index on `neuron_attrs.attr_key_id`.
15. Create `edges` table with all columns, check constraints, and foreign keys.
16. Create indexes on `edges.source_id` and `edges.target_id`.
17. Create `neurons_fts` virtual table (FTS5).
18. Create AFTER INSERT trigger on `neurons` to sync FTS.
19. Create AFTER UPDATE trigger on `neurons` to sync FTS content.
20. Create AFTER DELETE trigger on `neurons` to remove FTS row.
21. Create AFTER INSERT trigger on `neuron_tags` to refresh FTS tags_blob.
22. Create AFTER DELETE trigger on `neuron_tags` to refresh FTS tags_blob.
23. Create `neurons_vec` virtual table (vec0, 768-dim or config-specified dimensions).
24. Insert `last_migrated_at` (current time) into `meta`.

All 24 steps run inside a single transaction. If any step fails, the transaction is rolled back and the DB remains at version 0 (empty).

### 3.14 — Extension Loading

The sqlite-vec extension must be loaded on every connection before schema initialization runs. The FTS5 module is built into the SQLite library shipped with Python (no separate loading needed). If sqlite-vec fails to load (extension not available, system Python restriction), the CLI exits with code 2:
`sqlite-vec extension could not be loaded. Ensure you are using Homebrew Python or pysqlite3. See installation docs.`

This check runs before the schema version read, because the `neurons_vec` table cannot be introspected without the extension loaded.

---

## Constraints

- The schema must be identical for global stores (`~/.memory/memory.db`) and project-scoped stores (`.memory/memory.db`). There is no per-store schema variation.
- All timestamps are stored as integers (Unix epoch in milliseconds, UTC). No SQLite DATETIME type is used. This avoids timezone ambiguity and SQLite's text-date parsing behavior.
- All foreign keys use integer IDs, never string names. String names live only in registry tables (`tags.name`, `attr_keys.name`).
- The vec0 dimensionality is fixed at the time the schema is created and must not change without a migration. A dimension mismatch between a newly configured model and the existing vec0 table is detected by Spec #13, not by this spec.
- The FTS5 and vec0 virtual tables are schema objects created alongside the base tables. They are not optional or lazily created.
- The `meta` table is created before all other tables in the migration sequence, because it is needed to record the schema version mid-migration (for crash recovery).
- No `ON DELETE SET NULL` or `ON DELETE RESTRICT` patterns except where explicitly specified above. Cascade delete is used for neuron-owned data (tags, attributes, edges) to ensure no orphaned junction rows after neuron deletion.
- The `meta` table has no foreign keys and no cascade behavior. It is independent of all other tables.
- Schema migrations run in a single transaction. Partial migrations are not allowed.
- The CLI must not execute any data-manipulation commands (INSERT, UPDATE, DELETE on data tables) until schema initialization has successfully completed.

---

## Edge Cases

### EC-1: Fresh DB (schema version 0)
The `meta` table does not exist. The migration protocol detects this (table absence), treats version as 0, and runs the version-1 migration in full. Normal startup after migration.

### EC-2: DB exists but is empty (0 bytes or malformed)
SQLite will either open an empty file as a fresh DB (which is effectively version 0 — same as EC-1) or fail to parse a non-SQLite file. For a malformed file, SQLite returns a parse error. The CLI exits with code 2: `Failed to open DB at <path>: <SQLite error>`.

### EC-3: DB schema version newer than CLI
Detected in step 5 of §3.2. CLI exits without modifying the DB. The data is preserved.

### EC-4: Migration fails mid-sequence
The entire migration transaction is rolled back. The DB remains at the pre-migration version. The CLI exits with code 2 and a message identifying the failing migration step. No partial schema is left in the DB.

### EC-5: sqlite-vec not available
Detected before schema init runs (§3.14). CLI exits with code 2 with instructions. The DB file is not opened for write. The error is actionable (install instructions included in the message).

### EC-6: WAL mode cannot be set (read-only filesystem)
WAL pragma returns a value other than `'wal'`. The CLI emits a non-fatal warning (stderr, not stdout, not exit code 2). Read-only commands (search, get) may proceed. Write commands will fail at the SQLite level when they attempt to write, producing normal SQLite busy/readonly errors.

### EC-7: Multiple agents opening the DB simultaneously
WAL mode + `busy_timeout = 5000` handles this. Concurrent readers do not block. Concurrent writers queue up to 5 seconds before returning a timeout error. If a write times out, the CLI exits with code 2: `DB write timed out after 5 seconds. Another process may be holding a write lock.`

### EC-8: Neuron deleted while FTS trigger fires
SQLite triggers are synchronous and run within the same transaction as the triggering statement. The AFTER DELETE trigger on `neurons` fires before the transaction is committed, guaranteeing FTS stays in sync. Foreign keys cascade after the trigger; the trigger fires first.

### EC-9: FTS tags_blob out of sync due to direct neuron_tags manipulation
If a caller bypasses the application layer and directly modifies `neuron_tags`, the FTS tags_blob may become stale. This is an acceptable constraint: the CLI is the only intended interface to the DB (per §2 requirements: "CLI is the only interface"). The trigger approach is defense for normal operations; direct DB manipulation is out of scope.

### EC-10: vec0 table exists but with different dimensions than config
This is a config/DB drift scenario. Detection and resolution are the responsibility of Spec #13 (Metadata & Integrity), not this spec. This spec only creates the vec0 table with the dimensions from config at schema creation time (migration version 1 to version 1). After that, dimensions are fixed until an explicit migration changes them.

### EC-11: `neuron_tags` row inserted for a neuron that was just inserted (within same transaction)
The AFTER INSERT trigger on `neurons` creates an FTS row with an empty tags_blob. The AFTER INSERT trigger on `neuron_tags` then updates the FTS row for the affected neuron to include the new tag. Both fire within the same transaction. Order is guaranteed: the neuron insert trigger runs first, then the neuron_tags insert trigger runs. No conflict.

### EC-12: Neuron with no tags
Valid. The FTS row for a tagless neuron has an empty `tags_blob`. Searches over `content` still work. Tag filtering simply never matches this neuron for tag-based queries.

### EC-13: Two edges with the same `source_id` and `target_id` but different reasons
Allowed. No unique constraint on `(source_id, target_id)` in the edges table. Both edges coexist. Spreading activation may traverse both edges (both contribute `edge.weight` to activation calculations).

---

## Findings

### Finding F-1: FTS tags_blob is denormalized and trigger-maintained — fragility risk
The `tags_blob` column in `neurons_fts` is a space-separated concatenation of tag names, not a normalized structure. It is maintained by four triggers (INSERT/DELETE on `neurons`, INSERT/DELETE on `neuron_tags`). This is the correct approach (matches QMD reference pattern), but any future tag update operation (renaming a tag) would also need a trigger or a re-sync step to update all affected FTS rows. Tag renaming is not in v1 scope, but this is flagged for future reference.

### Finding F-2: vec0 does not support foreign keys — orphan vector risk
The sqlite-vec `vec0` virtual table does not support SQLite foreign key constraints. Deletions from `neurons` do not automatically cascade to `neurons_vec`. Every neuron-deletion code path (in Spec #6) must explicitly delete the corresponding `neurons_vec` row. This is a design constraint that all callers must honor; it is not enforceable at the schema level. Flagged here so Spec #6 is aware.

### Finding F-3: `tags_blob` computation in update triggers requires a subquery
When a tag is added or removed from a neuron (AFTER INSERT or AFTER DELETE on `neuron_tags`), the FTS row must be updated with the full current tags_blob, not just the delta. This means the trigger must compute the current concatenated tag list via a subquery against `neuron_tags JOIN tags WHERE neuron_id = new.neuron_id`. This is a subquery inside a trigger — legal in SQLite, but implementers should be aware. The exact SQL for this is an implementation detail for the scaffolding step.

### Finding F-4: Schema version is stored in `meta`, which is created in the same migration it tracks
There is a bootstrap ordering issue: to create version 1, we must create `meta` first, then write `schema_version = '1'` into it. The migration protocol (§3.2) handles the bootstrap by treating "meta table does not exist" as version 0. This is correct but worth stating explicitly — the first act of migration version 1 is to create the `meta` table, then immediately record the version. If a crash occurs between `meta` creation and `schema_version` write, the next startup will see `meta` exists but `schema_version` is absent; this should be treated as version 0 (re-run migration). The migration transaction atomicity makes this scenario impossible in practice (both steps are in the same transaction), but it is flagged for implementer awareness.

### Finding F-5: `status` column supports 'active' and 'archived' only — 'superseded' is attribute-level
The requirements mention `status` as an example attribute value (§6). The spec places `status` as a first-class column on `neurons` with only `'active'` and `'archived'` states. This is a deliberate design decision: `'archived'` is operationally important (excludes neurons from search by default), so it warrants a dedicated indexed column. More fine-grained status values (e.g., `'superseded'`) are implemented as attributes. This interpretation is consistent with §6 but is not explicitly stated in the requirements. Flagged for user confirmation if `'superseded'` was intended as a built-in first-class status.

### Finding F-6: Edge weight has no enforced upper bound
The requirements specify a default of 1.0 and that weight "modulates spreading activation strength." A check constraint enforces `weight > 0.0` but not an upper bound. Very high weights (e.g., 100.0) are valid and would dominate activation scores. Whether to enforce a maximum (e.g., 10.0) is left to Spec #7 (Edge Management) at the application validation layer. Flagged here in case a DB-level upper bound is preferred.

### Finding F-7: `project` is stored as a plain string, not a foreign key to a project registry
The requirements do not define a project registry. `project` is captured from `pwd`/git at write time and stored inline on each neuron. This means project names can vary across neurons (e.g., `"my-project"` vs `"My Project"`). No normalization is enforced at the DB layer. If a project registry is added in a future version, it would require a migration. Flagged as a potential consistency issue.
