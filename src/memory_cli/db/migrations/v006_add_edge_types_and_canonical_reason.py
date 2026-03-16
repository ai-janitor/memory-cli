# =============================================================================
# v006_add_edge_types_and_canonical_reason.py — Edge type normalization schema
# =============================================================================
# Purpose:     Add edge_types dimension table for canonical relationship types
#              and canonical_reason column on edges for normalized lookups.
# Rationale:   Free-text edge reason fields accumulate synonyms over time
#              (e.g., "has_interviewer", "interviewed_by", "interviewer" all mean
#              the same relationship). A canonical type system allows normalization
#              while preserving the original reason as provenance.
# Responsibility:
#   - CREATE TABLE edge_types (id, name, parent_id, description)
#   - ALTER TABLE edges ADD COLUMN canonical_reason (nullable)
#   - Seed common relationship types
# Organization:
#   Public function: apply(conn) -> None
# =============================================================================

from __future__ import annotations

import sqlite3


def apply(conn: sqlite3.Connection) -> None:
    """Apply the v5->v6 migration: add edge_types table and canonical_reason column.

    This function executes within the caller's transaction. It must NOT
    call BEGIN, COMMIT, or ROLLBACK.

    Args:
        conn: An open sqlite3.Connection inside an active transaction.

    Raises:
        sqlite3.Error: If any DDL fails.
    """
    # =========================================================================
    # STEP 1: Create edge_types dimension table
    # =========================================================================
    # Hierarchical type system: parent_id enables grouping (e.g., "interviewer"
    # as parent of "has_interviewer", "interviewed_by").
    conn.execute("""
        CREATE TABLE edge_types (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            parent_id   INTEGER REFERENCES edge_types(id) ON DELETE SET NULL,
            description TEXT NOT NULL DEFAULT ''
        )
    """)

    # =========================================================================
    # STEP 2: Add canonical_reason column to edges
    # =========================================================================
    # NULL means "not yet normalized". The janitor pass fills this in.
    # Original reason column is preserved as provenance.
    conn.execute(
        "ALTER TABLE edges ADD COLUMN canonical_reason TEXT DEFAULT NULL"
    )

    # =========================================================================
    # STEP 3: Create index for canonical_reason lookups
    # =========================================================================
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_edges_canonical_reason "
        "ON edges (canonical_reason)"
    )

    # =========================================================================
    # STEP 4: Seed common relationship types
    # =========================================================================
    _seed_edge_types = [
        ("related_to", None, "General relationship between neurons"),
        ("derived_from", None, "Target is derived from source"),
        ("contradicts", None, "Neurons contain contradictory information"),
        ("supports", None, "Source provides evidence for target"),
        ("references", None, "Source references target"),
        ("parent_of", None, "Hierarchical parent-child relationship"),
        ("interviewer", None, "Interview relationship"),
        ("colleague", None, "Professional colleague relationship"),
        ("authored_by", None, "Authorship relationship"),
        ("part_of", None, "Part-whole relationship"),
        ("similar_to", None, "Semantic similarity"),
        ("causes", None, "Causal relationship"),
        ("precedes", None, "Temporal ordering"),
        ("mentions", None, "Source mentions target entity"),
    ]
    conn.executemany(
        "INSERT INTO edge_types (name, parent_id, description) VALUES (?, ?, ?)",
        _seed_edge_types,
    )
