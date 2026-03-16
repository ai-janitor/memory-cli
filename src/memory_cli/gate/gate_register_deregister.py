# =============================================================================
# FILE: src/memory_cli/gate/gate_register_deregister.py
# PURPOSE: Register and deregister local memory stores in the global store.
# RATIONALE: The global store acts as an index of all local project stores.
#            Each registered project gets a "representative neuron" in the
#            global store, optionally linked to the global gate.
# RESPONSIBILITY:
#   - register(local_conn, local_store_path, global_conn) -> Dict
#   - deregister(local_store_path, global_conn) -> Dict
#   - _find_representative_neuron(global_conn, project_path_str) -> Optional[int]
#   - _hard_delete_neuron(conn, neuron_id) -> int
#   - _build_representative_content(local_store_path, local_gate) -> str
# ORGANIZATION:
#   1. Constants and exceptions
#   2. register — create representative neuron + edge
#   3. deregister — remove representative neuron + edges
#   4. _find_representative_neuron — SQL lookup
#   5. _hard_delete_neuron — cascading delete
#   6. _build_representative_content — content builder
# =============================================================================

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional


# =============================================================================
# CONSTANTS
# =============================================================================

# Source field value for gate registration neurons
GATE_REGISTRATION_SOURCE = "gate:register"


class GateRegistrationError(Exception):
    """Raised when gate register/deregister fails due to validation or store issues.

    Attributes:
        reason: Human-readable description of what went wrong.
    """


def register(
    local_conn: sqlite3.Connection,
    local_store_path: Path,
    global_conn: sqlite3.Connection,
) -> Dict[str, Any]:
    """Create a representative neuron in the GLOBAL store for this local store.

    The representative neuron encodes the project path and local gate info.
    It is then edged to the global gate (densest node in global store),
    if one exists and is different from the new representative.

    Logic flow:
    1. Compute the local store's gate (densest node).
    2. Build representative content string.
    3. Check if a representative neuron already exists for this project path.
       - If yes: raise GateRegistrationError.
    4. Create the representative neuron via neuron_add.
    5. Compute the global gate.
    6. If the global gate exists and differs from the new rep neuron,
       create an edge from global_gate -> rep_neuron.
    7. Return result dict with neuron_id, project_path, edge_created,
       global_gate_id, message.

    Args:
        local_conn: Connection to the local project database.
        local_store_path: Path to the local .memory/ store directory.
        global_conn: Connection to the global ~/.memory/ database.

    Returns:
        Dict with keys: neuron_id, project_path, edge_created,
        global_gate_id, message.

    Raises:
        GateRegistrationError: If the project is already registered.
    """
    from memory_cli.gate.gate_compute_densest_node import compute_densest_node
    from memory_cli.neuron import neuron_add

    # 1. Compute local gate
    local_gate = compute_densest_node(local_conn)

    # 2. Build content
    content = _build_representative_content(local_store_path, local_gate)

    # 3. Check for existing registration
    existing = _find_representative_neuron(global_conn, str(local_store_path))
    if existing is not None:
        raise GateRegistrationError(
            f"Project already registered: {local_store_path}"
            f". Representative neuron ID={existing}"
            f". Run `memory gate deregister` first to re-register."
        )

    # 4. Create representative neuron
    neuron = neuron_add(
        content=content,
        source=GATE_REGISTRATION_SOURCE,
        tags=["gate-registration"],
        no_embed=True,
        conn=global_conn,
    )
    rep_neuron_id = neuron["id"]

    # 5. Compute global gate
    global_gate = compute_densest_node(global_conn)

    # 6. Optionally create edge
    edge_created = False
    global_gate_id = None
    if global_gate is not None and global_gate.neuron_id != rep_neuron_id:
        from memory_cli.edge import edge_add
        try:
            edge_add(
                source_id=global_gate.neuron_id,
                target_id=rep_neuron_id,
                reason=f"gate registration for {local_store_path.name}",
                weight=1.0,
                conn=global_conn,
            )
            edge_created = True
            global_gate_id = global_gate.neuron_id
        except Exception:
            global_gate_id = global_gate.neuron_id

    # 7. Return result
    return {
        "neuron_id": rep_neuron_id,
        "project_path": str(local_store_path),
        "edge_created": edge_created,
        "global_gate_id": global_gate_id,
        "message": (
            f"Registered {local_store_path.name}"
            f" in global store (neuron={rep_neuron_id}"
            f", edge={edge_created})"
        ),
    }


def deregister(
    local_store_path: Path,
    global_conn: sqlite3.Connection,
) -> Dict[str, Any]:
    """Find and remove the representative neuron for this project from GLOBAL store.

    Locates the representative neuron by source=GATE_REGISTRATION_SOURCE and
    project path encoded in content. Hard-deletes the neuron and all its edges.

    Logic flow:
    1. Find the representative neuron by project path.
       - If not found: raise GateRegistrationError.
    2. Hard-delete the neuron (cascading edges, tags, attrs).
    3. Return result dict with neuron_id, project_path, edges_removed, message.

    Args:
        local_store_path: Path to the local .memory/ store directory.
        global_conn: Connection to the global ~/.memory/ database.

    Returns:
        Dict with keys: neuron_id, project_path, edges_removed, message.

    Raises:
        GateRegistrationError: If no registration found for this project.
    """
    rep_id = _find_representative_neuron(global_conn, str(local_store_path))
    if rep_id is None:
        raise GateRegistrationError(
            f"No registration found for project: {local_store_path}"
            f". Run `memory gate register` to register this project."
        )

    edges_removed = _hard_delete_neuron(global_conn, rep_id)

    return {
        "neuron_id": rep_id,
        "project_path": str(local_store_path),
        "edges_removed": edges_removed,
        "message": (
            f"Deregistered {local_store_path.name}"
            f" from global store (neuron={rep_id}"
            f", edges_removed={edges_removed})"
        ),
    }


def _find_representative_neuron(
    global_conn: sqlite3.Connection,
    project_path_str: str,
) -> Optional[int]:
    """Find the representative neuron for a project in the global store.

    Searches neurons by source=GATE_REGISTRATION_SOURCE and content containing
    the project path. Returns the neuron ID or None if not found.

    Args:
        global_conn: Connection to the global database.
        project_path_str: String representation of the project path.

    Returns:
        Neuron ID (int) or None.
    """
    row = global_conn.execute(
        """
        SELECT id FROM neurons
        WHERE source = ?
          AND content LIKE ?
          AND status = 'active'
        ORDER BY id ASC
        LIMIT 1
        """,
        (GATE_REGISTRATION_SOURCE, f"%{project_path_str}%"),
    ).fetchone()
    if row is not None:
        return row[0]
    return None


def _hard_delete_neuron(
    conn: sqlite3.Connection,
    neuron_id: int,
) -> int:
    """Hard-delete a neuron and all its edges and junction records.

    Removes:
    - All edges where source_id = neuron_id OR target_id = neuron_id.
    - All neuron_tags rows for neuron_id.
    - All neuron_attrs rows for neuron_id.
    - The neuron row itself.
    - Commits the transaction.

    Args:
        conn: SQLite connection.
        neuron_id: ID of the neuron to delete.

    Returns:
        Number of edges that were removed.
    """
    edge_count_row = conn.execute(
        """
        SELECT COUNT(*) FROM edges
        WHERE source_id = ? OR target_id = ?
        """,
        (neuron_id, neuron_id),
    ).fetchone()
    edges_removed = edge_count_row[0] if edge_count_row else 0

    conn.execute(
        "DELETE FROM edges WHERE source_id = ? OR target_id = ?",
        (neuron_id, neuron_id),
    )

    conn.execute(
        "DELETE FROM neuron_tags WHERE neuron_id = ?",
        (neuron_id,),
    )

    conn.execute(
        "DELETE FROM neuron_attrs WHERE neuron_id = ?",
        (neuron_id,),
    )

    conn.execute(
        "DELETE FROM neurons WHERE id = ?",
        (neuron_id,),
    )

    conn.commit()
    return edges_removed


def _build_representative_content(
    local_store_path: Path,
    local_gate: Any,
) -> str:
    """Build the content string for the representative neuron.

    Includes the project path and local gate info so the neuron is
    self-describing and discoverable via search.

    Args:
        local_store_path: Absolute path to the local .memory/ store.
        local_gate: GateResult or None from compute_densest_node.

    Returns:
        Multi-line content string.
    """
    gate_info = (
        f"gate_neuron_id={local_gate.neuron_id}, edge_count={local_gate.edge_count}"
        if local_gate is not None
        else "no_gate (store has no edges)"
    )

    return (
        f"Gate registration for project: {local_store_path.name}"
        f"\npath: {local_store_path}"
        f"\nlocal_gate: {gate_info}"
    )
