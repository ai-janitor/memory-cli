# =============================================================================
# v004_add_access_tracking.py — Add access tracking columns to neurons table
# =============================================================================
# Purpose:     Add last_accessed_at and access_count columns to track neuron
#              read frequency and recency.
# Rationale:   Access tracking enables decay/boost scoring — frequently and
#              recently accessed neurons are more relevant. This data feeds
#              into search ranking and future garbage collection.
# Responsibility:
#   - ALTER TABLE neurons ADD COLUMN last_accessed_at (INTEGER, nullable)
#   - ALTER TABLE neurons ADD COLUMN access_count (INTEGER DEFAULT 0)
#   - Does NOT update schema_version — the migration runner handles that
# Organization:
#   Public function: apply(conn) -> None
# =============================================================================

from __future__ import annotations

import sqlite3


def apply(conn: sqlite3.Connection) -> None:
    """Apply the v3->v4 migration: add access tracking columns to neurons.

    This function executes within the caller's transaction. It must NOT
    call BEGIN, COMMIT, or ROLLBACK. If any step fails, it raises an
    exception and the caller rolls back the entire migration batch.

    Args:
        conn: An open sqlite3.Connection inside an active transaction.

    Raises:
        sqlite3.Error: If ALTER TABLE fails.
    """
    # =========================================================================
    # STEP 1: Add last_accessed_at — nullable INTEGER (ms since epoch UTC)
    # =========================================================================
    conn.execute(
        "ALTER TABLE neurons ADD COLUMN last_accessed_at INTEGER"
    )

    # =========================================================================
    # STEP 2: Add access_count — INTEGER DEFAULT 0
    # =========================================================================
    conn.execute(
        "ALTER TABLE neurons ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0"
    )
