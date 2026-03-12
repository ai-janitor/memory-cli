# Schema & Migrations

Covers: complete SQLite schema — neurons table, edges table (with weight column),
tag registry table, attribute registry table, neuron-tag junction, neuron-attr
junction, FTS5 virtual table with porter unicode61 tokenizer, vec0 virtual table
(768-dim float32), FTS5 sync triggers (INSERT/UPDATE/DELETE), WAL mode, foreign
keys, busy timeout, schema version tracking, automatic migrations on startup.

Requirements traced: §2 Storage, §9 Metadata & Integrity (schema versioning).
Dependencies: #2 Config (db_path). All data-touching specs depend on this.
