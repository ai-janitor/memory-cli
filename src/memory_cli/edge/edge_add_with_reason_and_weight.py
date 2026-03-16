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
DEFAULT_PROVENANCE = "authored"
DEFAULT_CONFIDENCE = 1.0
VALID_PROVENANCES = ("authored", "extracted")


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
    provenance: Optional[str] = None,
    confidence: Optional[float] = None,
) -> Dict[str, Any]:
    """Create a directed edge from source neuron to target neuron.

    CLI: `memory edge add --source <id> --target <id> --reason <text> [--weight <float>]
          [--provenance authored|extracted] [--confidence <float>]`

    Args:
        conn: SQLite connection with edges and neurons tables.
        source_id: ID of the source neuron (must exist).
        target_id: ID of the target neuron (must exist).
        reason: Human-readable reason for the relationship (required, non-empty).
        weight: Optional edge weight (default 1.0, must be > 0.0).
        provenance: 'authored' (agent-created) or 'extracted' (model-inferred).
            Default 'authored'.
        confidence: Confidence score in (0.0, 1.0]. Default 1.0 for authored,
            must be < 1.0 for extracted edges.

    Returns:
        Dict with edge record including provenance and confidence.

    Raises:
        EdgeAddError: On validation failure or duplicate edge.
    """
    _validate_neuron_exists(conn, source_id)
    _validate_neuron_exists(conn, target_id)
    clean_reason = _validate_reason(reason)

    resolved_weight = weight if weight is not None else DEFAULT_WEIGHT
    _validate_weight(resolved_weight)

    resolved_provenance = provenance if provenance is not None else DEFAULT_PROVENANCE
    _validate_provenance(resolved_provenance)

    resolved_confidence = confidence if confidence is not None else DEFAULT_CONFIDENCE
    _validate_confidence(resolved_confidence)

    _check_duplicate(conn, source_id, target_id)

    edge_dict = _insert_edge(
        conn, source_id, target_id, clean_reason, resolved_weight,
        resolved_provenance, resolved_confidence,
    )
    return edge_dict


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
    row = conn.execute("SELECT id FROM neurons WHERE id = ?", (neuron_id,)).fetchone()
    if row is None:
        raise EdgeAddError(f"Neuron {neuron_id} not found", exit_code=1)


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
    stripped = reason.strip()
    if not stripped:
        raise EdgeAddError("Reason cannot be empty", exit_code=2)
    return stripped


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
    if weight <= 0.0:
        raise EdgeAddError(f"Weight must be greater than 0.0, got {weight}", exit_code=2)


def _validate_provenance(provenance: str) -> None:
    """Validate that provenance is one of the allowed values.

    Args:
        provenance: The provenance string to validate.

    Raises:
        EdgeAddError: If provenance is not in VALID_PROVENANCES (exit_code=2).
    """
    if provenance not in VALID_PROVENANCES:
        raise EdgeAddError(
            f"Provenance must be one of {VALID_PROVENANCES}, got '{provenance}'",
            exit_code=2,
        )


def _validate_confidence(confidence: float) -> None:
    """Validate that confidence is in the range (0.0, 1.0].

    Args:
        confidence: The confidence value to validate.

    Raises:
        EdgeAddError: If confidence is not in (0.0, 1.0] (exit_code=2).
    """
    if confidence <= 0.0 or confidence > 1.0:
        raise EdgeAddError(
            f"Confidence must be in (0.0, 1.0], got {confidence}",
            exit_code=2,
        )


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
    row = conn.execute(
        "SELECT reason FROM edges WHERE source_id = ? AND target_id = ?",
        (source_id, target_id),
    ).fetchone()
    if row is not None:
        existing_reason = row[0]
        raise EdgeAddError(
            f"Edge from {source_id} to {target_id} already exists (reason: '{existing_reason}')",
            exit_code=2,
        )


def _insert_edge(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
    reason: str,
    weight: float,
    provenance: str = DEFAULT_PROVENANCE,
    confidence: float = DEFAULT_CONFIDENCE,
) -> Dict[str, Any]:
    """Insert the edge row into the edges table.

    Args:
        conn: SQLite connection.
        source_id: Source neuron ID.
        target_id: Target neuron ID.
        reason: Validated, stripped reason string.
        weight: Validated positive weight.
        provenance: 'authored' or 'extracted'.
        confidence: Confidence score in (0.0, 1.0].

    Returns:
        Dict with the created edge record.
    """
    created_at = int(time.time() * 1000)
    # Check if provenance columns exist (v004 migration)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(edges)").fetchall()}
    if "provenance" in cols:
        conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, weight, created_at, provenance, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source_id, target_id, reason, weight, created_at, provenance, confidence),
        )
    else:
        conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, weight, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (source_id, target_id, reason, weight, created_at),
        )
    return {
        "source_id": source_id,
        "target_id": target_id,
        "reason": reason,
        "weight": weight,
        "created_at": created_at,
        "provenance": provenance,
        "confidence": confidence,
    }
