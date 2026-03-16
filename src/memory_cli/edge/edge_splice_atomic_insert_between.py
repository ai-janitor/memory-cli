# =============================================================================
# Module: edge_splice_atomic_insert_between.py
# Purpose: Atomically splice a new neuron into an existing edge. Given an edge
#   A->B and an intermediary neuron C, this operation: (1) removes A->B,
#   (2) creates A->C, (3) creates C->B — all within a single transaction.
#   If any step fails the entire operation rolls back.
# Rationale: The mansion architecture pattern frequently requires inserting
#   clustering neurons between existing edges. Doing this as 3 separate CLI
#   calls is error-prone: a crash between remove and add leaves the graph in
#   a broken state. A single atomic splice guarantees all-or-nothing semantics.
# Responsibility:
#   - Validate the A->B edge exists (exit 1 if not)
#   - Validate neuron C exists (exit 1 if not)
#   - Validate A->C and C->B don't already exist (exit 2 if duplicate)
#   - Within a single transaction: delete A->B, insert A->C, insert C->B
#   - Preserve original edge weight/reason or accept overrides
#   - Rollback on any failure
# Organization:
#   1. Imports
#   2. EdgeSpliceError — custom exception
#   3. edge_splice() — main entry point
#   4. _validate_edge_exists() — check A->B edge
#   5. _validate_neuron_exists() — check neuron C
#   6. _validate_no_duplicate() — check A->C and C->B don't exist
# =============================================================================

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, Optional


class EdgeSpliceError(Exception):
    """Raised when edge splice fails validation or write.

    Attributes:
        exit_code: CLI exit code — 1 for not-found errors, 2 for validation errors.
        message: Human-readable description of the failure.
    """

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def edge_splice(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
    through_id: int,
    reason_a_c: Optional[str] = None,
    reason_c_b: Optional[str] = None,
    weight_a_c: Optional[float] = None,
    weight_c_b: Optional[float] = None,
) -> Dict[str, Any]:
    """Atomically splice neuron C between existing edge A->B.

    CLI: `memory edge splice <source> <target> --through <middle>
          [--reason-ac <text>] [--reason-cb <text>]
          [--weight-ac <float>] [--weight-cb <float>]`

    Logic flow:
    1. Look up existing A->B edge — capture its reason and weight
       - Not found -> EdgeSpliceError(exit_code=1)
    2. Validate neuron C (through_id) exists
       - Not found -> EdgeSpliceError(exit_code=1)
    3. Validate A->C does not already exist
       - Exists -> EdgeSpliceError(exit_code=2)
    4. Validate C->B does not already exist
       - Exists -> EdgeSpliceError(exit_code=2)
    5. In a single transaction:
       a. DELETE A->B
       b. INSERT A->C (with original or overridden reason/weight)
       c. INSERT C->B (with original or overridden reason/weight)
    6. Return dict with removed_edge, new_edges (a_c, c_b)

    Weight/reason resolution:
    - If override provided, use it
    - Otherwise inherit from the original A->B edge

    Args:
        conn: SQLite connection with edges and neurons tables.
        source_id: A — source neuron of the existing edge.
        target_id: B — target neuron of the existing edge.
        through_id: C — the intermediary neuron to splice in.
        reason_a_c: Optional reason for A->C edge (default: inherit from A->B).
        reason_c_b: Optional reason for C->B edge (default: inherit from A->B).
        weight_a_c: Optional weight for A->C edge (default: inherit from A->B).
        weight_c_b: Optional weight for C->B edge (default: inherit from A->B).

    Returns:
        Dict with: removed_edge (the old A->B), edge_a_c, edge_c_b.

    Raises:
        EdgeSpliceError: On validation failure or write error.
    """
    # --- Step 1: Validate A->B edge exists, capture its data ---
    original_edge = _validate_edge_exists(conn, source_id, target_id)

    # --- Step 2: Validate neuron C exists ---
    _validate_neuron_exists(conn, through_id)

    # --- Step 3: Validate A->C does not already exist ---
    _validate_no_duplicate(conn, source_id, through_id, "A->C")

    # --- Step 4: Validate C->B does not already exist ---
    _validate_no_duplicate(conn, through_id, target_id, "C->B")

    # --- Step 5: Resolve reason/weight from original or overrides ---
    resolved_reason_a_c = reason_a_c if reason_a_c is not None else original_edge["reason"]
    resolved_reason_c_b = reason_c_b if reason_c_b is not None else original_edge["reason"]
    resolved_weight_a_c = weight_a_c if weight_a_c is not None else original_edge["weight"]
    resolved_weight_c_b = weight_c_b if weight_c_b is not None else original_edge["weight"]

    # Validate weights are positive if overridden
    if resolved_weight_a_c <= 0.0:
        raise EdgeSpliceError(
            f"Weight for A->C must be > 0.0, got {resolved_weight_a_c}", exit_code=2
        )
    if resolved_weight_c_b <= 0.0:
        raise EdgeSpliceError(
            f"Weight for C->B must be > 0.0, got {resolved_weight_c_b}", exit_code=2
        )

    # Validate reasons are non-empty
    if not resolved_reason_a_c.strip():
        raise EdgeSpliceError("Reason for A->C cannot be empty", exit_code=2)
    if not resolved_reason_c_b.strip():
        raise EdgeSpliceError("Reason for C->B cannot be empty", exit_code=2)

    # --- Step 6: Atomic transaction — delete A->B, insert A->C, insert C->B ---
    try:
        now = int(time.time() * 1000)

        # Delete A->B
        conn.execute(
            "DELETE FROM edges WHERE source_id = ? AND target_id = ?",
            (source_id, target_id),
        )

        # Insert A->C (splicing is an authored action)
        has_prov = _has_provenance_columns(conn)
        if has_prov:
            insert_sql = (
                "INSERT INTO edges (source_id, target_id, reason, weight, created_at, provenance, confidence) "
                "VALUES (?, ?, ?, ?, ?, 'authored', 1.0)"
            )
        else:
            insert_sql = (
                "INSERT INTO edges (source_id, target_id, reason, weight, created_at) "
                "VALUES (?, ?, ?, ?, ?)"
            )
        conn.execute(insert_sql, (source_id, through_id, resolved_reason_a_c.strip(), resolved_weight_a_c, now))

        # Insert C->B (splicing is an authored action)
        conn.execute(insert_sql, (through_id, target_id, resolved_reason_c_b.strip(), resolved_weight_c_b, now))

        edge_a_c = {
            "source_id": source_id,
            "target_id": through_id,
            "reason": resolved_reason_a_c.strip(),
            "weight": resolved_weight_a_c,
            "created_at": now,
            "provenance": "authored",
            "confidence": 1.0,
        }
        edge_c_b = {
            "source_id": through_id,
            "target_id": target_id,
            "reason": resolved_reason_c_b.strip(),
            "weight": resolved_weight_c_b,
            "created_at": now,
            "provenance": "authored",
            "confidence": 1.0,
        }

        return {
            "removed_edge": original_edge,
            "edge_a_c": edge_a_c,
            "edge_c_b": edge_c_b,
        }

    except EdgeSpliceError:
        raise
    except Exception as exc:
        conn.rollback()
        raise EdgeSpliceError(
            f"Splice transaction failed: {exc}", exit_code=2
        ) from exc


def _has_provenance_columns(conn: sqlite3.Connection) -> bool:
    """Check if the edges table has provenance/confidence columns."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(edges)").fetchall()}
    return "provenance" in cols


def _validate_edge_exists(
    conn: sqlite3.Connection, source_id: int, target_id: int
) -> Dict[str, Any]:
    """Check that an edge from source to target exists and return its data.

    Args:
        conn: SQLite connection.
        source_id: Source neuron ID.
        target_id: Target neuron ID.

    Returns:
        Dict with edge data including provenance and confidence.

    Raises:
        EdgeSpliceError: If edge not found (exit_code=1).
    """
    has_prov = _has_provenance_columns(conn)
    if has_prov:
        prov_clause = ", provenance, confidence"
    else:
        prov_clause = ", 'authored' AS provenance, 1.0 AS confidence"
    row = conn.execute(
        f"SELECT source_id, target_id, reason, weight, created_at{prov_clause} "
        f"FROM edges WHERE source_id = ? AND target_id = ?",
        (source_id, target_id),
    ).fetchone()
    if row is None:
        raise EdgeSpliceError(
            f"No edge from {source_id} to {target_id}", exit_code=1
        )
    return dict(row)


def _validate_neuron_exists(conn: sqlite3.Connection, neuron_id: int) -> None:
    """Check that a neuron with the given ID exists.

    Args:
        conn: SQLite connection.
        neuron_id: The neuron ID to check.

    Raises:
        EdgeSpliceError: If neuron not found (exit_code=1).
    """
    row = conn.execute("SELECT id FROM neurons WHERE id = ?", (neuron_id,)).fetchone()
    if row is None:
        raise EdgeSpliceError(f"Neuron {neuron_id} not found", exit_code=1)


def _validate_no_duplicate(
    conn: sqlite3.Connection, source_id: int, target_id: int, label: str
) -> None:
    """Check that no edge already exists between source and target.

    Args:
        conn: SQLite connection.
        source_id: Source neuron ID.
        target_id: Target neuron ID.
        label: Human-readable label for error messages (e.g. "A->C").

    Raises:
        EdgeSpliceError: If edge already exists (exit_code=2).
    """
    row = conn.execute(
        "SELECT reason FROM edges WHERE source_id = ? AND target_id = ?",
        (source_id, target_id),
    ).fetchone()
    if row is not None:
        raise EdgeSpliceError(
            f"Edge {label} from {source_id} to {target_id} already exists (reason: '{row[0]}')",
            exit_code=2,
        )
