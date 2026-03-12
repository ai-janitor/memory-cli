# =============================================================================
# v001_baseline_all_tables_indexes_triggers.py — Full v0->v1 migration
# =============================================================================
# Purpose:     Create the entire baseline schema from scratch: all 9 tables
#              (neurons, edges, tags, neuron_tags, attr_keys, neuron_attrs,
#              neurons_fts, neurons_vec, meta), all indexes, all FTS triggers,
#              and seed the meta table with initial values.
# Rationale:   Single baseline migration creates a known-good starting state.
#              All 24 ordered DDL steps run inside the caller's transaction —
#              this function must NOT begin/commit its own transaction.
# Responsibility:
#   - Execute 24 ordered DDL steps to build the complete schema
#   - Seed the meta table with schema_version=1, embedding info, timestamps
#   - All operations use the connection passed in (no autocommit)
#   - Raise on any failure (caller handles rollback)
# Organization:
#   Public function: apply(conn) -> None
#   Private constants: SQL strings for each DDL step
#   Steps are numbered and documented inline for traceability
# =============================================================================

from __future__ import annotations

import sqlite3


def apply(conn: sqlite3.Connection) -> None:
    """Apply the v0->v1 baseline migration: create all tables, indexes,
    triggers, and meta entries.

    This function executes within the caller's transaction. It must NOT
    call BEGIN, COMMIT, or ROLLBACK. If any step fails, it raises an
    exception and the caller rolls back the entire migration batch.

    Args:
        conn: An open sqlite3.Connection with sqlite-vec loaded and
              pragmas configured. Must be inside an active transaction.

    Raises:
        sqlite3.Error: If any DDL step fails.
    """
    # =========================================================================
    # STEP 1: Create the meta table
    # =========================================================================
    # CREATE TABLE meta (
    #   key   TEXT PRIMARY KEY,
    #   value TEXT NOT NULL
    # )
    # Rationale: Must exist first so other steps can reference it, and so
    # schema_version can be set at the end.

    # =========================================================================
    # STEP 2: Create the neurons table
    # =========================================================================
    # CREATE TABLE neurons (
    #   id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    #   content             TEXT NOT NULL CHECK(length(content) > 0),
    #   created_at          INTEGER NOT NULL,   -- ms since epoch UTC
    #   updated_at          INTEGER NOT NULL,   -- ms since epoch UTC
    #   project             TEXT NOT NULL CHECK(length(project) > 0),
    #   source              TEXT,               -- nullable, e.g. "conversation:abc123"
    #   embedding_updated_at INTEGER,           -- nullable, null = needs embedding
    #   status              TEXT NOT NULL DEFAULT 'active'
    #                       CHECK(status IN ('active', 'archived'))
    # )

    # =========================================================================
    # STEP 3: Create neurons indexes
    # =========================================================================
    # CREATE INDEX idx_neurons_project ON neurons(project)
    # Rationale: Most queries filter by project first

    # =========================================================================
    # STEP 4: Create neurons created_at index
    # =========================================================================
    # CREATE INDEX idx_neurons_created_at ON neurons(created_at)
    # Rationale: Time-range queries, recent-first ordering

    # =========================================================================
    # STEP 5: Create neurons status index
    # =========================================================================
    # CREATE INDEX idx_neurons_status ON neurons(status)
    # Rationale: Filter active vs archived neurons

    # =========================================================================
    # STEP 6: Create neurons embedding_updated_at index
    # =========================================================================
    # CREATE INDEX idx_neurons_embedding_updated_at ON neurons(embedding_updated_at)
    # Rationale: Find neurons that need embedding (WHERE embedding_updated_at IS NULL)

    # =========================================================================
    # STEP 7: Create the edges table
    # =========================================================================
    # CREATE TABLE edges (
    #   id         INTEGER PRIMARY KEY AUTOINCREMENT,
    #   source_id  INTEGER NOT NULL REFERENCES neurons(id) ON DELETE CASCADE,
    #   target_id  INTEGER NOT NULL REFERENCES neurons(id) ON DELETE CASCADE,
    #   reason     TEXT NOT NULL CHECK(length(reason) > 0),
    #   weight     REAL NOT NULL DEFAULT 1.0 CHECK(weight > 0),
    #   created_at INTEGER NOT NULL  -- ms since epoch UTC
    # )
    # Notes:
    #   - Self-referential edges allowed (source_id == target_id)
    #   - Multiple edges between same neuron pair allowed (no unique constraint)
    #   - CASCADE delete: if a neuron is deleted, all its edges go too

    # =========================================================================
    # STEP 8: Create edges source_id index
    # =========================================================================
    # CREATE INDEX idx_edges_source_id ON edges(source_id)

    # =========================================================================
    # STEP 9: Create edges target_id index
    # =========================================================================
    # CREATE INDEX idx_edges_target_id ON edges(target_id)

    # =========================================================================
    # STEP 10: Create the tags table
    # =========================================================================
    # CREATE TABLE tags (
    #   id         INTEGER PRIMARY KEY AUTOINCREMENT,
    #   name       TEXT NOT NULL UNIQUE CHECK(length(name) > 0)
    #              CHECK(name = lower(name)),   -- enforce lowercase
    #   created_at INTEGER NOT NULL
    # )

    # =========================================================================
    # STEP 11: Create the neuron_tags junction table
    # =========================================================================
    # CREATE TABLE neuron_tags (
    #   neuron_id INTEGER NOT NULL REFERENCES neurons(id) ON DELETE CASCADE,
    #   tag_id    INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    #   PRIMARY KEY (neuron_id, tag_id)
    # )

    # =========================================================================
    # STEP 12: Create neuron_tags tag_id index
    # =========================================================================
    # CREATE INDEX idx_neuron_tags_tag_id ON neuron_tags(tag_id)
    # Rationale: Reverse lookup — find all neurons for a given tag

    # =========================================================================
    # STEP 13: Create the attr_keys table
    # =========================================================================
    # CREATE TABLE attr_keys (
    #   id         INTEGER PRIMARY KEY AUTOINCREMENT,
    #   name       TEXT NOT NULL UNIQUE CHECK(length(name) > 0),
    #   created_at INTEGER NOT NULL
    # )

    # =========================================================================
    # STEP 14: Create the neuron_attrs table
    # =========================================================================
    # CREATE TABLE neuron_attrs (
    #   neuron_id   INTEGER NOT NULL REFERENCES neurons(id) ON DELETE CASCADE,
    #   attr_key_id INTEGER NOT NULL REFERENCES attr_keys(id) ON DELETE RESTRICT,
    #   value       TEXT NOT NULL,
    #   PRIMARY KEY (neuron_id, attr_key_id)
    # )
    # Note: attr_keys uses ON DELETE RESTRICT — cannot delete an attr_key
    # that is still referenced. This prevents orphaned attribute values.

    # =========================================================================
    # STEP 15: Create neuron_attrs attr_key_id index
    # =========================================================================
    # CREATE INDEX idx_neuron_attrs_attr_key_id ON neuron_attrs(attr_key_id)

    # =========================================================================
    # STEP 16: Create the FTS5 virtual table (neurons_fts)
    # =========================================================================
    # CREATE VIRTUAL TABLE neurons_fts USING fts5(
    #   content,
    #   tags_blob,
    #   content='neurons',
    #   content_rowid='id',
    #   tokenize='porter unicode61'
    # )
    # Rationale: Content-backed FTS5 table. The content= directive means FTS5
    # reads content from the neurons table, but we must manually keep it in sync
    # via triggers. tags_blob is a space-separated string of tag names for
    # combined content+tag search.

    # =========================================================================
    # STEP 17: FTS trigger — AFTER INSERT on neurons
    # =========================================================================
    # CREATE TRIGGER trg_neurons_fts_insert AFTER INSERT ON neurons
    # BEGIN
    #   INSERT INTO neurons_fts(rowid, content, tags_blob)
    #   VALUES (new.id, new.content, '');
    # END;
    # Note: New neurons start with empty tags_blob. Tag triggers update it.

    # =========================================================================
    # STEP 18: FTS trigger — AFTER UPDATE on neurons
    # =========================================================================
    # CREATE TRIGGER trg_neurons_fts_update AFTER UPDATE ON neurons
    # BEGIN
    #   INSERT INTO neurons_fts(neurons_fts, rowid, content, tags_blob)
    #   VALUES ('delete', old.id, old.content,
    #     COALESCE((SELECT group_concat(t.name, ' ')
    #               FROM neuron_tags nt JOIN tags t ON nt.tag_id = t.id
    #               WHERE nt.neuron_id = old.id), ''));
    #   INSERT INTO neurons_fts(rowid, content, tags_blob)
    #   VALUES (new.id, new.content,
    #     COALESCE((SELECT group_concat(t.name, ' ')
    #               FROM neuron_tags nt JOIN tags t ON nt.tag_id = t.id
    #               WHERE nt.neuron_id = new.id), ''));
    # END;
    # Note: Must delete old row then insert new. FTS5 content-sync protocol.

    # =========================================================================
    # STEP 19: FTS trigger — AFTER DELETE on neurons
    # =========================================================================
    # CREATE TRIGGER trg_neurons_fts_delete AFTER DELETE ON neurons
    # BEGIN
    #   INSERT INTO neurons_fts(neurons_fts, rowid, content, tags_blob)
    #   VALUES ('delete', old.id, old.content,
    #     COALESCE((SELECT group_concat(t.name, ' ')
    #               FROM neuron_tags nt JOIN tags t ON nt.tag_id = t.id
    #               WHERE nt.neuron_id = old.id), ''));
    # END;

    # =========================================================================
    # STEP 20: FTS trigger — AFTER INSERT on neuron_tags
    # =========================================================================
    # CREATE TRIGGER trg_neuron_tags_fts_insert AFTER INSERT ON neuron_tags
    # BEGIN
    #   -- Delete old FTS row with previous tags_blob
    #   INSERT INTO neurons_fts(neurons_fts, rowid, content, tags_blob)
    #   VALUES ('delete', new.neuron_id,
    #     (SELECT content FROM neurons WHERE id = new.neuron_id),
    #     COALESCE((SELECT group_concat(t.name, ' ')
    #               FROM neuron_tags nt JOIN tags t ON nt.tag_id = t.id
    #               WHERE nt.neuron_id = new.neuron_id
    #               AND nt.tag_id != new.tag_id), ''));
    #   -- Insert new FTS row with updated tags_blob (includes new tag)
    #   INSERT INTO neurons_fts(rowid, content, tags_blob)
    #   VALUES (new.neuron_id,
    #     (SELECT content FROM neurons WHERE id = new.neuron_id),
    #     COALESCE((SELECT group_concat(t.name, ' ')
    #               FROM neuron_tags nt JOIN tags t ON nt.tag_id = t.id
    #               WHERE nt.neuron_id = new.neuron_id), ''));
    # END;

    # =========================================================================
    # STEP 21: FTS trigger — AFTER DELETE on neuron_tags
    # =========================================================================
    # CREATE TRIGGER trg_neuron_tags_fts_delete AFTER DELETE ON neuron_tags
    # BEGIN
    #   -- Delete old FTS row with previous tags_blob (includes removed tag)
    #   INSERT INTO neurons_fts(neurons_fts, rowid, content, tags_blob)
    #   VALUES ('delete', old.neuron_id,
    #     (SELECT content FROM neurons WHERE id = old.neuron_id),
    #     COALESCE((SELECT group_concat(t.name, ' ')
    #               FROM neuron_tags nt JOIN tags t ON nt.tag_id = t.id
    #               WHERE nt.neuron_id = old.neuron_id
    #               AND nt.tag_id = old.tag_id), '')
    #     || CASE WHEN EXISTS(
    #         SELECT 1 FROM neuron_tags nt JOIN tags t ON nt.tag_id = t.id
    #         WHERE nt.neuron_id = old.neuron_id AND nt.tag_id != old.tag_id)
    #       THEN ' ' || COALESCE((SELECT group_concat(t.name, ' ')
    #         FROM neuron_tags nt JOIN tags t ON nt.tag_id = t.id
    #         WHERE nt.neuron_id = old.neuron_id AND nt.tag_id != old.tag_id), '')
    #       ELSE '' END);
    #   -- Insert new FTS row with updated tags_blob (tag removed)
    #   INSERT INTO neurons_fts(rowid, content, tags_blob)
    #   VALUES (old.neuron_id,
    #     (SELECT content FROM neurons WHERE id = old.neuron_id),
    #     COALESCE((SELECT group_concat(t.name, ' ')
    #               FROM neuron_tags nt JOIN tags t ON nt.tag_id = t.id
    #               WHERE nt.neuron_id = old.neuron_id), ''));
    # END;
    # Note: The delete trigger must reconstruct the OLD tags_blob (before the
    # tag was removed) for the FTS delete command to match correctly.

    # =========================================================================
    # STEP 22: Create the vec0 virtual table (neurons_vec)
    # =========================================================================
    # CREATE VIRTUAL TABLE neurons_vec USING vec0(
    #   neuron_id INTEGER PRIMARY KEY,
    #   embedding float[768]
    # )
    # Notes:
    #   - vec0 does NOT support foreign keys — callers must manually delete
    #     vec rows when neurons are deleted
    #   - vec0 does NOT support JOINs — queries use a two-step pattern:
    #     1. Query neurons_vec for nearest neighbor IDs
    #     2. Query neurons table with those IDs
    #   - 768 dimensions matches the default embedding model

    # =========================================================================
    # STEP 23: Seed the meta table with initial values
    # =========================================================================
    # INSERT INTO meta (key, value) VALUES
    #   ('schema_version', '1'),
    #   ('embedding_model', 'default'),
    #   ('embedding_dimensions', '768'),
    #   ('created_at', <current_timestamp_ms>),
    #   ('last_migrated_at', <current_timestamp_ms>)
    # Use Python's time.time_ns() // 1_000_000 for ms-precision UTC timestamp

    # =========================================================================
    # STEP 24: Verification — check all expected tables exist
    # =========================================================================
    # Query sqlite_master for all 9 tables:
    #   neurons, edges, tags, neuron_tags, attr_keys, neuron_attrs,
    #   neurons_fts, neurons_vec, meta
    # If any are missing: raise RuntimeError with list of missing tables
    # This is a sanity check — if we get here, all CREATEs succeeded,
    # but belt-and-suspenders for debugging

    pass
