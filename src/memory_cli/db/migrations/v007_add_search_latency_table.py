# =============================================================================
# v007_add_search_latency_table.py — Create search_latency table for timing
# =============================================================================
# Purpose:     Store per-search timing breakdowns so `memory meta health` can
#              report p50/p95/p99 latency and suggest pruning when degraded.
# Rationale:   Opaque instrumentation — agents don't browse this table directly,
#              they use `memory meta health` to get actionable diagnostics.
# Responsibility:
#   - CREATE TABLE search_latency with stage timings and metadata
#   - Does NOT update schema_version — the migration runner handles that
# Organization:
#   Public function: apply(conn) -> None
# =============================================================================

from __future__ import annotations

import sqlite3


def apply(conn: sqlite3.Connection) -> None:
    """Apply the v6->v7 migration: create search_latency table.

    This function executes within the caller's transaction. It must NOT
    call BEGIN, COMMIT, or ROLLBACK.

    Args:
        conn: An open sqlite3.Connection inside an active transaction.

    Raises:
        sqlite3.Error: If CREATE TABLE fails.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS search_latency (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            total_ms    REAL    NOT NULL,
            retrieval_ms REAL   NOT NULL,
            scoring_ms  REAL    NOT NULL,
            output_ms   REAL    NOT NULL,
            result_count INTEGER NOT NULL,
            recorded_at INTEGER NOT NULL
        )
    """)
    # Index on recorded_at for efficient window queries in health reporting
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_search_latency_recorded_at
        ON search_latency (recorded_at)
    """)
