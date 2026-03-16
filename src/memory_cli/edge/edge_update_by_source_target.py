# =============================================================================
# Module: edge_update_by_source_target.py
# Purpose: Update fields on an existing edge identified by its (source_id,
#   target_id) composite key. Supports modifying reason (type) and weight
#   without deleting and recreating the edge.
# Rationale: Previously, modifying an edge required remove + add, which loses
#   the original created_at timestamp and is not atomic. An update-in-place
#   operation preserves the edge's identity and creation time while allowing
#   field changes.
# Responsibility:
#   - Look up edge by (source_id, target_id)
#   - Validate at least one field is being updated
#   - Validate new weight > 0.0 if provided
#   - Validate new reason is non-empty if provided
#   - UPDATE the edge row in place
#   - Return the updated edge record
# Organization:
#   1. Imports
#   2. EdgeUpdateError — custom exception
#   3. edge_update() — main entry point
#   4. _lookup_edge() — find edge by composite key
#   5. _build_update() — construct SET clause from provided fields
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional


class EdgeUpdateError(Exception):
    """Raised when edge update fails validation or lookup.

    Attributes:
        exit_code: CLI exit code — 1 for not-found, 2 for validation errors.
        message: Human-readable description of the failure.
    """

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def edge_update(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
    reason: Optional[str] = None,
    weight: Optional[float] = None,
) -> Dict[str, Any]:
    """Update fields on an existing edge.

    CLI: `memory edge update <source> <target> [--type <text>] [--weight <float>]`

    Logic flow:
    1. Validate at least one of reason or weight is provided
       - Neither -> EdgeUpdateError(exit_code=2)
    2. Look up edge by (source_id, target_id)
       - Not found -> EdgeUpdateError(exit_code=1)
    3. Validate reason is non-empty if provided
       - Empty after strip -> EdgeUpdateError(exit_code=2)
    4. Validate weight > 0.0 if provided
       - Zero or negative -> EdgeUpdateError(exit_code=2)
    5. Build and execute UPDATE statement
    6. Return the updated edge record

    Args:
        conn: SQLite connection with edges table.
        source_id: Source neuron ID of the edge to update.
        target_id: Target neuron ID of the edge to update.
        reason: New reason/type for the edge (optional).
        weight: New weight for the edge (optional).

    Returns:
        Dict with updated edge: source_id, target_id, reason, weight, created_at.

    Raises:
        EdgeUpdateError: On validation failure or edge not found.
    """
    # --- Step 1: At least one field must be provided ---
    if reason is None and weight is None:
        raise EdgeUpdateError(
            "At least one of --type or --weight must be provided", exit_code=2
        )

    # --- Step 2: Look up the edge ---
    existing = _lookup_edge(conn, source_id, target_id)
    if existing is None:
        raise EdgeUpdateError(
            f"No edge from {source_id} to {target_id}", exit_code=1
        )

    # --- Step 3: Validate reason if provided ---
    clean_reason = None
    if reason is not None:
        clean_reason = reason.strip()
        if not clean_reason:
            raise EdgeUpdateError("Reason cannot be empty", exit_code=2)

    # --- Step 4: Validate weight if provided ---
    if weight is not None and weight <= 0.0:
        raise EdgeUpdateError(
            f"Weight must be greater than 0.0, got {weight}", exit_code=2
        )

    # --- Step 5: Build and execute UPDATE ---
    set_parts = []
    params = []
    if clean_reason is not None:
        set_parts.append("reason = ?")
        params.append(clean_reason)
    if weight is not None:
        set_parts.append("weight = ?")
        params.append(weight)

    params.extend([source_id, target_id])
    sql = f"UPDATE edges SET {', '.join(set_parts)} WHERE source_id = ? AND target_id = ?"
    conn.execute(sql, params)

    # --- Step 6: Return updated edge ---
    updated = _lookup_edge(conn, source_id, target_id)
    return updated  # type: ignore[return-value]


def _lookup_edge(
    conn: sqlite3.Connection, source_id: int, target_id: int
) -> Optional[Dict[str, Any]]:
    """Find an edge by its (source_id, target_id) composite key.

    Args:
        conn: SQLite connection.
        source_id: Source neuron ID.
        target_id: Target neuron ID.

    Returns:
        Dict with edge data if found, None otherwise.
    """
    row = conn.execute(
        "SELECT source_id, target_id, reason, weight, created_at FROM edges WHERE source_id = ? AND target_id = ?",
        (source_id, target_id),
    ).fetchone()
    if row is None:
        return None
    return dict(row)
