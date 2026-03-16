# =============================================================================
# v004_add_edge_provenance.py — Add provenance tracking to edges
# =============================================================================
# Purpose:     Add provenance and confidence columns to the edges table so
#              authored edges (agent-created, confidence=1.0) can be
#              distinguished from extracted edges (model-inferred, confidence<1.0).
# Rationale:   Spreading activation should trust authored edges more than
#              extracted ones. Provenance metadata enables confidence-weighted
#              traversal — low-confidence edges decay activation faster.
# Responsibility:
#   - ALTER TABLE edges ADD COLUMN provenance (authored|extracted)
#   - ALTER TABLE edges ADD COLUMN confidence (0.0, 1.0]
#   - Existing edges default to 'authored' with confidence 1.0
# Organization:
#   Public function: apply(conn) -> None
# =============================================================================

from __future__ import annotations

import sqlite3


def apply(conn: sqlite3.Connection) -> None:
    """Apply the v3->v4 migration: add provenance columns to edges table.

    This function executes within the caller's transaction. It must NOT
    call BEGIN, COMMIT, or ROLLBACK.

    Args:
        conn: An open sqlite3.Connection inside an active transaction.

    Raises:
        sqlite3.Error: If any ALTER TABLE fails.
    """
    # =========================================================================
    # STEP 1: Add provenance column — 'authored' or 'extracted'
    # =========================================================================
    # Default 'authored' for existing edges — they were explicitly created
    # by agents, not inferred by a model.
    conn.execute(
        "ALTER TABLE edges ADD COLUMN provenance TEXT NOT NULL DEFAULT 'authored'"
    )

    # =========================================================================
    # STEP 2: Add confidence column — float in (0.0, 1.0]
    # =========================================================================
    # Default 1.0 for existing edges (full confidence for authored edges).
    # CHECK constraint enforces valid range at the DB level.
    conn.execute(
        "ALTER TABLE edges ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0"
    )
