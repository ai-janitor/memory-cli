# =============================================================================
# v005_add_consolidated_column.py — Add consolidated timestamp to neurons table
# =============================================================================
# Purpose:     Add nullable consolidated column to track when a neuron was last
#              processed by the consolidation lifecycle step.
# Rationale:   Consolidation is the lifecycle trigger — neurons enter as raw
#              additions and get consolidated (reviewed, linked, enriched) over
#              time. The timestamp lets us query unconsolidated neurons FIFO and
#              detect stale neurons (updated_at > consolidated).
# Responsibility:
#   - ALTER TABLE neurons ADD COLUMN consolidated (INTEGER, nullable, ms UTC)
#   - Does NOT update schema_version — the migration runner handles that
# Organization:
#   Public function: apply(conn) -> None
# =============================================================================

from __future__ import annotations

import sqlite3


def apply(conn: sqlite3.Connection) -> None:
    """Apply the v4->v5 migration: add consolidated column to neurons.

    This function executes within the caller's transaction. It must NOT
    call BEGIN, COMMIT, or ROLLBACK. If any step fails, it raises an
    exception and the caller rolls back the entire migration batch.

    Args:
        conn: An open sqlite3.Connection inside an active transaction.

    Raises:
        sqlite3.Error: If ALTER TABLE fails.
    """
    # =========================================================================
    # STEP 1: Add consolidated — nullable INTEGER (ms since epoch UTC)
    # NULL means the neuron has never been consolidated.
    # =========================================================================
    conn.execute(
        "ALTER TABLE neurons ADD COLUMN consolidated INTEGER"
    )
