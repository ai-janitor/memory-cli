# =============================================================================
# Module: neuron_archive_and_restore.py
# Purpose: Archive and restore lifecycle transitions for neurons — soft-delete
#   semantics that preserve all data (vectors, FTS entries, edges).
# Rationale: Neurons are never hard-deleted. Archive sets status to 'archived',
#   making the neuron invisible to default list/search queries but preserving
#   all associated data. Restore reverses this. Both operations are idempotent
#   (archiving an archived neuron is a no-op). This keeps the data model simple
#   and avoids orphaned edges/vectors.
# Responsibility:
#   - neuron_archive: set status='archived', no-op if already archived
#   - neuron_restore: set status='active', no-op if already active
#   - Both update updated_at timestamp when a real transition happens
#   - Neither operation touches vectors, FTS entries, or edges
# Organization:
#   1. Imports
#   2. Constants
#   3. NeuronLifecycleError — custom exception
#   4. neuron_archive() — archive a neuron
#   5. neuron_restore() — restore a neuron
#   6. _transition_status() — shared transition logic
# =============================================================================

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, Optional


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"


class NeuronLifecycleError(Exception):
    """Raised when an archive/restore operation fails.

    Attributes:
        reason: Why it failed (not_found).
    """

    pass


def neuron_archive(conn: sqlite3.Connection, neuron_id: int) -> Dict[str, Any]:
    """Archive a neuron — set status to 'archived'.

    CLI: `memory neuron archive <id>`

    Logic flow:
    1. Call _transition_status(conn, neuron_id, target_status='archived')
    2. Return the updated neuron dict

    No-op behavior: if the neuron is already archived, _transition_status
    detects no change and returns the current record without updating
    updated_at. This is intentional — idempotent archive.

    Preservation: archiving does NOT delete:
    - Embedding vectors (still in sqlite-vec)
    - FTS entries (still in FTS table)
    - Edges (still in edges table, both as source and target)
    - Tag associations (still in neuron_tags)
    - Attribute pairs (still in neuron_attrs)

    Args:
        conn: SQLite connection.
        neuron_id: ID of the neuron to archive.

    Returns:
        Fully hydrated neuron dict after transition.

    Raises:
        NeuronLifecycleError: If neuron not found.
    """
    # Delegate to shared transition logic
    # return _transition_status(conn, neuron_id, STATUS_ARCHIVED)

    return _transition_status(conn, neuron_id, STATUS_ARCHIVED)


def neuron_restore(conn: sqlite3.Connection, neuron_id: int) -> Dict[str, Any]:
    """Restore an archived neuron — set status to 'active'.

    CLI: `memory neuron restore <id>`

    Logic flow:
    1. Call _transition_status(conn, neuron_id, target_status='active')
    2. Return the updated neuron dict

    No-op behavior: if the neuron is already active, _transition_status
    detects no change and returns the current record without updating
    updated_at. This is intentional — idempotent restore.

    Args:
        conn: SQLite connection.
        neuron_id: ID of the neuron to restore.

    Returns:
        Fully hydrated neuron dict after transition.

    Raises:
        NeuronLifecycleError: If neuron not found.
    """
    # Delegate to shared transition logic
    # return _transition_status(conn, neuron_id, STATUS_ACTIVE)

    return _transition_status(conn, neuron_id, STATUS_ACTIVE)


def _transition_status(
    conn: sqlite3.Connection,
    neuron_id: int,
    target_status: str,
) -> Dict[str, Any]:
    """Shared logic for archive and restore transitions.

    Logic flow:
    1. SELECT id, status FROM neurons WHERE id = ?
       - Not found -> raise NeuronLifecycleError("Neuron {id} not found")
    2. Check current status:
       - If current_status == target_status -> no-op, skip to step 4
       - If current_status != target_status -> proceed to step 3
    3. UPDATE neurons SET status = ?, updated_at = ? WHERE id = ?
       - updated_at = current UTC milliseconds via int(time.time() * 1000)
       - Only update when an actual transition occurs
    4. Return fully hydrated neuron dict via neuron_get()

    Args:
        conn: SQLite connection.
        neuron_id: ID of the neuron.
        target_status: Target status string ('active' or 'archived').

    Returns:
        Fully hydrated neuron dict.

    Raises:
        NeuronLifecycleError: If neuron not found.
    """
    # --- Step 1: Lookup ---
    # SELECT id, status FROM neurons WHERE id = ?
    # Not found -> raise NeuronLifecycleError

    # --- Step 2: Check current status ---
    # if current_status == target_status: skip update (no-op)

    # --- Step 3: Transition ---
    # UPDATE neurons SET status = ?, updated_at = ? WHERE id = ?

    # --- Step 4: Return hydrated record ---
    # from .neuron_get_by_id import neuron_get
    # return neuron_get(conn, neuron_id)

    from .neuron_get_by_id import neuron_get

    row = conn.execute(
        "SELECT id, status FROM neurons WHERE id = ?",
        (neuron_id,)
    ).fetchone()

    if row is None:
        raise NeuronLifecycleError(f"Neuron {neuron_id} not found")

    if row["status"] != target_status:
        now_ms = int(time.time() * 1000)
        conn.execute(
            "UPDATE neurons SET status = ?, updated_at = ? WHERE id = ?",
            (target_status, now_ms, neuron_id)
        )
        conn.commit()

    return neuron_get(conn, neuron_id)
