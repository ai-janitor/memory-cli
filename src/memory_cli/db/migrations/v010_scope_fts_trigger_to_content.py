# =============================================================================
# v010_scope_fts_trigger_to_content.py — FTS update only on content changes (R4)
# =============================================================================
# Purpose:     Recreate trg_neurons_fts_update as AFTER UPDATE OF content so
#              access_count / last_accessed_at bumps (and any non-content UPDATE)
#              do NOT rewrite the FTS index (~20x write amplification per search
#              hydration when the old trigger was unconditional).
# Rationale:   R4 true read-only search + NEW-4: search must not force FTS
#              rewrites. Content changes still propagate (golden).
# Responsibility:
#   - DROP TRIGGER IF EXISTS trg_neurons_fts_update
#   - CREATE TRIGGER ... AFTER UPDATE OF content ON neurons (same body)
#   - Does NOT update schema_version — the migration runner handles that
# =============================================================================

from __future__ import annotations

import sqlite3


def apply(conn: sqlite3.Connection) -> None:
    """Apply v009→v010: scope FTS update trigger to content column only.

    Runs inside the caller's transaction. Must NOT BEGIN/COMMIT/ROLLBACK.
    """
    conn.execute("DROP TRIGGER IF EXISTS trg_neurons_fts_update")
    conn.execute(
        """
        CREATE TRIGGER trg_neurons_fts_update AFTER UPDATE OF content ON neurons
        BEGIN
            INSERT INTO neurons_fts(neurons_fts, rowid, content, tags_blob)
            VALUES ('delete', old.id, old.content,
                COALESCE((SELECT group_concat(t.name, ' ')
                          FROM neuron_tags nt JOIN tags t ON nt.tag_id = t.id
                          WHERE nt.neuron_id = old.id), ''));
            INSERT INTO neurons_fts(rowid, content, tags_blob)
            VALUES (new.id, new.content,
                COALESCE((SELECT group_concat(t.name, ' ')
                          FROM neuron_tags nt JOIN tags t ON nt.tag_id = t.id
                          WHERE nt.neuron_id = new.id), ''));
        END
        """
    )
