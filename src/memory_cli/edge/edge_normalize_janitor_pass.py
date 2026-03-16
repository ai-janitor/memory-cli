# =============================================================================
# Module: edge_normalize_janitor_pass.py
# Purpose: Normalize free-text edge reason fields to canonical types.
#   Scans all edges, clusters synonym reasons under canonical edge_types,
#   and writes the canonical_reason column. Original reason is preserved
#   as provenance — never modified.
# Rationale: Over time, agents create edges with variant reason strings
#   (e.g., "has_interviewer", "interviewed_by", "interviewer") that all
#   mean the same relationship. Normalization enables consistent querying
#   and graph traversal by canonical type.
# Responsibility:
#   - Maintain synonym map: variant -> canonical name
#   - Scan edges with NULL canonical_reason
#   - Resolve each reason to its canonical form
#   - Update canonical_reason column (batch)
#   - Register new edge_types discovered during normalization
# Organization:
#   1. Imports and constants
#   2. SYNONYM_MAP — built-in synonym clusters
#   3. EdgeNormalizeError — custom exception
#   4. edge_normalize() — main janitor entry point
#   5. _resolve_canonical() — synonym lookup with fallback
#   6. _ensure_edge_type_exists() — register type in edge_types table
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional


# -----------------------------------------------------------------------------
# Built-in synonym clusters: variant -> canonical name
# -----------------------------------------------------------------------------
# Keys are lowercase, stripped. Values are the canonical edge_type name.
# The canonical name itself also appears as a key (identity mapping).
SYNONYM_MAP: Dict[str, str] = {
    # --- interviewer cluster ---
    "interviewer": "interviewer",
    "has_interviewer": "interviewer",
    "interviewed_by": "interviewer",
    "interviews": "interviewer",
    "interview": "interviewer",
    # --- related_to cluster ---
    "related_to": "related_to",
    "related": "related_to",
    "relates_to": "related_to",
    "relation": "related_to",
    # --- derived_from cluster ---
    "derived_from": "derived_from",
    "derives_from": "derived_from",
    "derived": "derived_from",
    "source_of": "derived_from",
    # --- contradicts cluster ---
    "contradicts": "contradicts",
    "contradicted_by": "contradicts",
    "contradiction": "contradicts",
    "conflicts_with": "contradicts",
    # --- supports cluster ---
    "supports": "supports",
    "supported_by": "supports",
    "evidence_for": "supports",
    "backs": "supports",
    # --- references cluster ---
    "references": "references",
    "referenced_by": "references",
    "refers_to": "references",
    "ref": "references",
    # --- parent_of cluster ---
    "parent_of": "parent_of",
    "child_of": "parent_of",
    "has_parent": "parent_of",
    "has_child": "parent_of",
    # --- colleague cluster ---
    "colleague": "colleague",
    "coworker": "colleague",
    "works_with": "colleague",
    "collaborator": "colleague",
    # --- authored_by cluster ---
    "authored_by": "authored_by",
    "written_by": "authored_by",
    "author": "authored_by",
    "created_by": "authored_by",
    # --- part_of cluster ---
    "part_of": "part_of",
    "belongs_to": "part_of",
    "member_of": "part_of",
    "component_of": "part_of",
    # --- similar_to cluster ---
    "similar_to": "similar_to",
    "similar": "similar_to",
    "like": "similar_to",
    "resembles": "similar_to",
    # --- causes cluster ---
    "causes": "causes",
    "caused_by": "causes",
    "leads_to": "causes",
    "results_in": "causes",
    # --- precedes cluster ---
    "precedes": "precedes",
    "followed_by": "precedes",
    "before": "precedes",
    "after": "precedes",
    # --- mentions cluster ---
    "mentions": "mentions",
    "mentioned_by": "mentions",
    "mentioned_in": "mentions",
    "cites": "mentions",
}


class EdgeNormalizeError(Exception):
    """Raised when edge normalization fails.

    Attributes:
        exit_code: CLI exit code — 1 for not-found, 2 for validation error.
        message: Human-readable description of the failure.
    """

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def edge_normalize(
    conn: sqlite3.Connection,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run the janitor pass: normalize edge reasons to canonical types.

    Scans all edges where canonical_reason IS NULL, resolves each reason
    to its canonical form via SYNONYM_MAP, and updates the canonical_reason
    column. Unknown reasons are kept as-is (identity normalization — the
    original reason becomes the canonical form).

    New canonical types discovered during normalization are registered in
    the edge_types table if they don't already exist.

    Args:
        conn: SQLite connection with edges and edge_types tables.
        dry_run: If True, compute normalizations but don't write to DB.

    Returns:
        Dict with normalization results:
        - total_scanned: number of edges examined
        - normalized: number of edges that got a canonical_reason
        - new_types_registered: number of new edge_types created
        - mappings: list of {edge_id, original_reason, canonical_reason}
        - dry_run: whether this was a dry run

    Raises:
        EdgeNormalizeError: If the edge_types table or canonical_reason
            column doesn't exist (schema not migrated).
    """
    # --- Step 1: Verify schema has canonical_reason column ---
    _verify_schema(conn)

    # --- Step 2: Fetch all edges with NULL canonical_reason ---
    rows = conn.execute(
        "SELECT id, reason FROM edges WHERE canonical_reason IS NULL"
    ).fetchall()

    # --- Step 3: Resolve each reason to canonical form ---
    mappings: List[Dict[str, Any]] = []
    new_types: set[str] = set()

    for row in rows:
        edge_id = row["id"]
        original_reason = row["reason"]
        canonical = _resolve_canonical(original_reason)

        mappings.append({
            "edge_id": edge_id,
            "original_reason": original_reason,
            "canonical_reason": canonical,
        })

        # Track new types that need to be registered
        new_types.add(canonical)

    # --- Step 4: Register new edge_types and update edges ---
    new_types_registered = 0
    if not dry_run and mappings:
        # Register any new canonical types
        for type_name in new_types:
            if _ensure_edge_type_exists(conn, type_name):
                new_types_registered += 1

        # Batch update canonical_reason on edges
        conn.executemany(
            "UPDATE edges SET canonical_reason = ? WHERE id = ?",
            [(m["canonical_reason"], m["edge_id"]) for m in mappings],
        )

    return {
        "total_scanned": len(rows),
        "normalized": len(mappings),
        "new_types_registered": new_types_registered,
        "mappings": mappings,
        "dry_run": dry_run,
    }


def _resolve_canonical(reason: str) -> str:
    """Resolve a free-text reason to its canonical form.

    Logic:
    1. Lowercase and strip whitespace
    2. Replace spaces and hyphens with underscores
    3. Look up in SYNONYM_MAP
    4. If found: return the canonical name
    5. If not found: return the normalized key as-is (identity mapping)

    Args:
        reason: Original edge reason string.

    Returns:
        Canonical reason string.
    """
    key = reason.strip().lower().replace(" ", "_").replace("-", "_")
    return SYNONYM_MAP.get(key, key)


def _ensure_edge_type_exists(conn: sqlite3.Connection, type_name: str) -> bool:
    """Register a canonical type in edge_types if it doesn't already exist.

    Args:
        conn: SQLite connection.
        type_name: Canonical type name to ensure exists.

    Returns:
        True if a new row was inserted, False if it already existed.
    """
    existing = conn.execute(
        "SELECT id FROM edge_types WHERE name = ?", (type_name,)
    ).fetchone()
    if existing is not None:
        return False

    conn.execute(
        "INSERT INTO edge_types (name, description) VALUES (?, ?)",
        (type_name, f"Auto-registered by janitor normalization"),
    )
    return True


def _verify_schema(conn: sqlite3.Connection) -> None:
    """Verify the schema has been migrated to v006 (edge_types + canonical_reason).

    Raises:
        EdgeNormalizeError: If required schema elements are missing.
    """
    # Check edge_types table exists
    table_check = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='edge_types'"
    ).fetchone()
    if table_check is None:
        raise EdgeNormalizeError(
            "edge_types table not found. Run migrations first (schema v006 required).",
            exit_code=2,
        )

    # Check canonical_reason column exists on edges
    cols = {row[1] for row in conn.execute("PRAGMA table_info(edges)").fetchall()}
    if "canonical_reason" not in cols:
        raise EdgeNormalizeError(
            "canonical_reason column not found on edges table. "
            "Run migrations first (schema v006 required).",
            exit_code=2,
        )
