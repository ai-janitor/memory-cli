# =============================================================================
# Module: edge_remove_by_source_target.py
# Purpose: Look up an edge by its (source_id, target_id) composite key and
#   delete it. Does NOT cascade to neurons — removing an edge only removes
#   the relationship, both endpoint neurons remain intact.
# Rationale: Edge removal is a simple lookup-then-delete. The unique
#   constraint on (source_id, target_id) guarantees at most one edge per
#   direction, so the lookup is unambiguous. We don't delete neurons because
#   edge semantics are purely relational — a neuron's existence is independent
#   of its connections.
# Responsibility:
#   - Look up edge by (source_id, target_id)
#   - If not found -> raise EdgeRemoveError (exit 1)
#   - If found -> delete the edge row, return the deleted edge info
#   - Neurons are never modified or deleted by this operation
# Organization:
#   1. Imports
#   2. EdgeRemoveError — custom exception
#   3. edge_remove() — main entry point
#   4. _lookup_edge() — find edge by composite key
#   5. _delete_edge() — execute the DELETE
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional


class EdgeRemoveError(Exception):
    """Raised when edge removal fails (edge not found).

    Attributes:
        exit_code: CLI exit code — 1 for not-found errors.
        message: Human-readable description of the failure.
    """

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def edge_remove(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
) -> Dict[str, Any]:
    """Remove the directed edge from source to target.

    CLI: `memory edge remove --source <id> --target <id>`

    Logic flow:
    1. Look up edge via _lookup_edge(conn, source_id, target_id)
       - Not found -> raise EdgeRemoveError(exit_code=1)
       - Found -> capture edge data for return value
    2. Delete edge via _delete_edge(conn, source_id, target_id)
    3. Return the deleted edge record (so caller can confirm what was removed)

    Important: This does NOT delete or modify the source or target neurons.
    Both neurons remain in the database with all their data intact. Only the
    relationship (edge row) is removed.

    Args:
        conn: SQLite connection with edges table.
        source_id: Source neuron ID of the edge to remove.
        target_id: Target neuron ID of the edge to remove.

    Returns:
        Dict with the deleted edge record: source_id, target_id, reason, weight, created_at.

    Raises:
        EdgeRemoveError: If no edge exists between source and target (exit_code=1).
    """
    # --- Step 1: Look up the edge ---
    # edge_data = _lookup_edge(conn, source_id, target_id)
    # If None -> raise EdgeRemoveError(
    #     f"No edge from {source_id} to {target_id}", exit_code=1
    # )
    edge_data = _lookup_edge(conn, source_id, target_id)
    if edge_data is None:
        raise EdgeRemoveError(f"No edge from {source_id} to {target_id}", exit_code=1)

    # --- Step 2: Delete the edge ---
    # _delete_edge(conn, source_id, target_id)
    _delete_edge(conn, source_id, target_id)

    # --- Step 3: Return deleted edge info ---
    # return edge_data
    return edge_data


def _lookup_edge(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
) -> Optional[Dict[str, Any]]:
    """Find an edge by its (source_id, target_id) composite key.

    Logic:
    1. SELECT source_id, target_id, reason, weight, created_at
       FROM edges
       WHERE source_id = ? AND target_id = ?
    2. If row found -> return dict with all columns
    3. If no row -> return None

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


def _delete_edge(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
) -> None:
    """Execute DELETE for the edge row.

    Logic:
    1. DELETE FROM edges WHERE source_id = ? AND target_id = ?
    2. No return value — caller already has the edge data from lookup

    Note: This only deletes the edge row. Neurons, tags, attrs, embeddings,
    and any other data associated with the source and target neurons are
    completely unaffected.

    Args:
        conn: SQLite connection.
        source_id: Source neuron ID.
        target_id: Target neuron ID.
    """
    conn.execute(
        "DELETE FROM edges WHERE source_id = ? AND target_id = ?",
        (source_id, target_id),
    )
