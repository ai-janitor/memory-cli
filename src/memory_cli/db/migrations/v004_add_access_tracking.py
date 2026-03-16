# =============================================================================
# v004_add_access_tracking.py — Add access tracking columns to neurons
# =============================================================================
# Purpose:     Add last_accessed_at and access_count columns to the neurons
#              table for LRU-based pruning and memory consolidation.
# Rationale:   Access tracking enables automatic archival of stale neurons
#              (not accessed within a configurable window). These columns
#              power the `memory neuron prune` command.
# Responsibility:
#   - ALTER TABLE neurons ADD COLUMN last_accessed_at INTEGER (nullable, ms UTC)
#   - ALTER TABLE neurons ADD COLUMN access_count INTEGER DEFAULT 0
#   - Add index on last_accessed_at for efficient LRU queries
# Organization:
#   Public function: apply(conn) -> None
# =============================================================================

from __future__ import annotations

import sqlite3


def apply(conn: sqlite3.Connection) -> None:
    """Apply the v3->v4 migration: add access tracking columns to neurons.

    This function executes within the caller's transaction. It must NOT
    call BEGIN, COMMIT, or ROLLBACK.

    Args:
        conn: An open sqlite3.Connection inside an active transaction.

    Raises:
        sqlite3.Error: If any DDL step fails.
    """
    # =========================================================================
    # STEP 1: Add last_accessed_at column (nullable, milliseconds UTC)
    # =========================================================================
    # NULL means "never accessed via neuron_get or search" — these neurons
    # are prime candidates for pruning.
    conn.execute(
        "ALTER TABLE neurons ADD COLUMN last_accessed_at INTEGER"
    )

    # =========================================================================
    # STEP 2: Add access_count column (default 0)
    # =========================================================================
    # Tracks how many times a neuron has been retrieved. Neurons with
    # access_count=0 are prioritized for pruning.
    conn.execute(
        "ALTER TABLE neurons ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0"
    )

    # =========================================================================
    # STEP 3: Add index on last_accessed_at for efficient LRU queries
    # =========================================================================
    conn.execute(
        "CREATE INDEX idx_neurons_last_accessed_at ON neurons (last_accessed_at)"
    )
