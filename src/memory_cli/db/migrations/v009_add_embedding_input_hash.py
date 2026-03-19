# =============================================================================
# v009_add_embedding_input_hash.py — Add embedding_input_hash column to neurons
# =============================================================================
# Purpose:     Store SHA-256 hash of the assembled embedding input (content +
#              tags) so that batch_reembed can skip re-embedding when the actual
#              embedding input hasn't changed (e.g. only source or non-embedded
#              attrs changed).
# Rationale:   Content-addressable vectorization skip. Modeled after QMD's
#              content hash pattern. Avoids redundant LLM embed calls when
#              updated_at changes but embedding-relevant content is identical.
# Responsibility:
#   - ALTER TABLE neurons ADD COLUMN embedding_input_hash TEXT
#   - Does NOT update schema_version — the migration runner handles that
# Organization:
#   Public function: apply(conn) -> None
# =============================================================================

from __future__ import annotations

import sqlite3


def apply(conn: sqlite3.Connection) -> None:
    """Apply the v008->v009 migration: add embedding_input_hash column.

    This function executes within the caller's transaction. It must NOT
    call BEGIN, COMMIT, or ROLLBACK.

    Args:
        conn: An open sqlite3.Connection inside an active transaction.

    Raises:
        sqlite3.Error: If ALTER TABLE fails.
    """
    conn.execute(
        "ALTER TABLE neurons ADD COLUMN embedding_input_hash TEXT"
    )
