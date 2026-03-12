# =============================================================================
# Module: edge_add_with_reason_and_weight.py
# Purpose: Validate inputs and insert a directed edge between two neurons.
#   Enforces referential integrity (both endpoints must exist), reason
#   non-emptiness, weight positivity, and uniqueness on (source_id, target_id).
# Rationale: Edge creation is the primary write path for graph structure.
#   Validation must be strict because bad edges corrupt traversal, spreading
#   activation, and search results. Self-loops are intentionally allowed
#   (a neuron can reference itself), and circular graphs are valid (A->B->A).
# Responsibility:
#   - Validate source neuron exists (exit 1 if not)
#   - Validate target neuron exists (exit 1 if not)
#   - Validate reason is non-empty after strip (exit 2 if not)
#   - Validate weight > 0.0 (exit 2 if not)
#   - Check for duplicate (source_id, target_id) pair (exit 2 with existing reason)
#   - Insert edge row with reason, weight, created_at
#   - Return the created edge record
# Organization:
#   1. Imports
#   2. Constants (table name, default weight)
#   3. EdgeAddError — custom exception with exit_code attribute
#   4. edge_add() — main entry point
#   5. _validate_neuron_exists() — check neuron existence by ID
#   6. _validate_reason() — non-empty check
#   7. _validate_weight() — positive float check
#   8. _check_duplicate() — unique constraint pre-check
#   9. _insert_edge() — the actual INSERT
# =============================================================================

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, Optional


# -----------------------------------------------------------------------------
# Constants — table name, column references, default weight.
# Single source of truth for edge table schema references.
# -----------------------------------------------------------------------------
EDGES_TABLE = "edges"
DEFAULT_WEIGHT = 1.0


class EdgeAddError(Exception):
    """Raised when edge add fails validation or insert.

    Attributes:
        exit_code: CLI exit code — 1 for not-found errors, 2 for validation errors.
        message: Human-readable description of the failure.
    """

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def edge_add(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
    reason: str,
    weight: Optional[float] = None,
) -> Dict[str, Any]:
    """Create a directed edge from source neuron to target neuron.

    CLI: `memory edge add --source <id> --target <id> --reason <text> [--weight <float>]`

    Validation order (matches spec #7):
    1. Validate source neuron exists via _validate_neuron_exists(conn, source_id)
       - Not found -> EdgeAddError(exit_code=1)
    2. Validate target neuron exists via _validate_neuron_exists(conn, target_id)
       - Not found -> EdgeAddError(exit_code=1)
    3. Validate reason non-empty via _validate_reason(reason)
       - Empty or whitespace-only -> EdgeAddError(exit_code=2)
    4. Resolve weight: use provided value or DEFAULT_WEIGHT (1.0)
    5. Validate weight > 0.0 via _validate_weight(weight)
       - Zero or negative -> EdgeAddError(exit_code=2)
    6. Check duplicate via _check_duplicate(conn, source_id, target_id)
       - Exists -> EdgeAddError(exit_code=2, message includes existing reason)
    7. Insert edge via _insert_edge(conn, source_id, target_id, reason, weight)
    8. Return created edge as dict

    Note: self-loops (source_id == target_id) are intentionally allowed.
    Note: circular graphs (A->B and B->A) are intentionally allowed —
    they are two distinct edges with distinct reasons.

    Args:
        conn: SQLite connection with edges and neurons tables.
        source_id: ID of the source neuron (must exist).
        target_id: ID of the target neuron (must exist).
        reason: Human-readable reason for the relationship (required, non-empty).
        weight: Optional edge weight (default 1.0, must be > 0.0).

    Returns:
        Dict with edge record: source_id, target_id, reason, weight, created_at.

    Raises:
        EdgeAddError: On validation failure or duplicate edge.
    """
    # --- Step 1: Validate source neuron exists ---
    # _validate_neuron_exists(conn, source_id)
    # Raises EdgeAddError(exit_code=1) if not found

    # --- Step 2: Validate target neuron exists ---
    # _validate_neuron_exists(conn, target_id)
    # Raises EdgeAddError(exit_code=1) if not found

    # --- Step 3: Validate reason non-empty ---
    # _validate_reason(reason)
    # Raises EdgeAddError(exit_code=2) if empty/whitespace

    # --- Step 4: Resolve weight ---
    # resolved_weight = weight if weight is not None else DEFAULT_WEIGHT

    # --- Step 5: Validate weight > 0.0 ---
    # _validate_weight(resolved_weight)
    # Raises EdgeAddError(exit_code=2) if <= 0.0

    # --- Step 6: Check duplicate ---
    # _check_duplicate(conn, source_id, target_id)
    # Raises EdgeAddError(exit_code=2) with existing reason if duplicate

    # --- Step 7: Insert edge ---
    # edge_dict = _insert_edge(conn, source_id, target_id, reason, resolved_weight)

    # --- Step 8: Return created edge ---
    # return edge_dict

    pass


def _validate_neuron_exists(conn: sqlite3.Connection, neuron_id: int) -> None:
    """Check that a neuron with the given ID exists in the neurons table.

    Logic:
    1. SELECT id FROM neurons WHERE id = ?
    2. If no row returned -> raise EdgeAddError with exit_code=1
       Message: "Neuron {neuron_id} not found"

    Args:
        conn: SQLite connection.
        neuron_id: The neuron ID to check.

    Raises:
        EdgeAddError: If neuron does not exist (exit_code=1).
    """
    pass


def _validate_reason(reason: str) -> str:
    """Validate and normalize the edge reason string.

    Logic:
    1. Strip whitespace from reason
    2. If empty after strip -> raise EdgeAddError(exit_code=2)
       Message: "Reason cannot be empty"
    3. Return stripped reason

    Args:
        reason: Raw reason string from CLI input.

    Returns:
        Stripped reason string.

    Raises:
        EdgeAddError: If reason is empty after stripping (exit_code=2).
    """
    pass


def _validate_weight(weight: float) -> None:
    """Validate that edge weight is strictly positive.

    Logic:
    1. If weight <= 0.0 -> raise EdgeAddError(exit_code=2)
       Message: "Weight must be greater than 0.0, got {weight}"

    Args:
        weight: The resolved weight value.

    Raises:
        EdgeAddError: If weight <= 0.0 (exit_code=2).
    """
    pass


def _check_duplicate(
    conn: sqlite3.Connection, source_id: int, target_id: int
) -> None:
    """Check if an edge already exists between source and target.

    Logic:
    1. SELECT reason FROM edges WHERE source_id = ? AND target_id = ?
    2. If row found -> raise EdgeAddError(exit_code=2)
       Message: "Edge from {source_id} to {target_id} already exists (reason: '{existing_reason}')"

    Args:
        conn: SQLite connection.
        source_id: Source neuron ID.
        target_id: Target neuron ID.

    Raises:
        EdgeAddError: If duplicate edge exists (exit_code=2).
    """
    pass


def _insert_edge(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
    reason: str,
    weight: float,
) -> Dict[str, Any]:
    """Insert the edge row into the edges table.

    Logic:
    1. Generate created_at = current UTC milliseconds: int(time.time() * 1000)
    2. INSERT INTO edges (source_id, target_id, reason, weight, created_at)
       VALUES (?, ?, ?, ?, ?)
    3. Build and return dict: {source_id, target_id, reason, weight, created_at}

    Args:
        conn: SQLite connection.
        source_id: Source neuron ID.
        target_id: Target neuron ID.
        reason: Validated, stripped reason string.
        weight: Validated positive weight.

    Returns:
        Dict with the created edge record.
    """
    pass
