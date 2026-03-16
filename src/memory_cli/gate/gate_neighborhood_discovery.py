# =============================================================================
# FILE: src/memory_cli/gate/gate_neighborhood_discovery.py
# PURPOSE: Discover the top N neighbors of a gate neuron by edge weight.
# RATIONALE: Once the gate (densest node) is known, the "houses" in the
#            mansion are its strongest neighbors. This module lists them.
# RESPONSIBILITY:
#   - discover_neighborhood(conn, gate_neuron_id, top_n) -> List[NeighborResult]
#   - _query_neighbors(conn, gate_neuron_id, top_n) -> List[sqlite3.Row]
# ORGANIZATION:
#   1. NeighborResult NamedTuple
#   2. DEFAULT_TOP_N constant
#   3. discover_neighborhood — public API
#   4. _query_neighbors — SQL helper
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import List, NamedTuple


# =============================================================================
# DATA TYPES
# =============================================================================
class NeighborResult(NamedTuple):
    """A neighboring neuron reachable from the gate."""

    target_id: int
    reason: str
    weight: float


# Default number of neighbors to return
DEFAULT_TOP_N = 10


def discover_neighborhood(
    conn: sqlite3.Connection,
    gate_neuron_id: int,
    top_n: int = DEFAULT_TOP_N,
) -> List[NeighborResult]:
    """List the top N neighbors of a gate neuron, sorted by edge weight.

    Traverses all edges connected to the gate neuron (both outgoing and
    incoming). For each edge, the "neighbor" is the neuron on the OTHER end.
    Results are sorted by weight descending — strongest relationships first.

    Logic flow:
    1. Query all edges touching gate_neuron_id (both directions).
    2. For each edge, compute neighbor = the other end of the edge.
    3. Group by neighbor_id, take MAX(weight) for deduplication.
    4. ORDER BY weight DESC, neighbor_id ASC.
    5. LIMIT top_n.
    6. Convert rows to NeighborResult list.

    Args:
        conn: SQLite connection with edges table.
        gate_neuron_id: The gate neuron's ID.
        top_n: Maximum number of neighbors to return.

    Returns:
        List of NeighborResult sorted by weight descending.
    """
    rows = _query_neighbors(conn, gate_neuron_id, top_n)
    return [
        NeighborResult(
            target_id=row["neighbor_id"],
            reason=row["reason"],
            weight=row["weight"],
        )
        for row in rows
    ]


def _query_neighbors(
    conn: sqlite3.Connection,
    gate_neuron_id: int,
    top_n: int,
) -> List[sqlite3.Row]:
    """Query all neighbors of the gate neuron, both directions.

    SQL strategy:
    - UNION ALL of outgoing and incoming edges for the gate neuron.
    - For each edge, compute the "neighbor" as the OTHER end:
        outgoing: neighbor = target_id
        incoming: neighbor = source_id
    - Group by neighbor_id: take MAX(weight) to deduplicate.
    - ORDER BY weight DESC, neighbor_id ASC (tie-break by ID).
    - LIMIT top_n.

    Args:
        conn: SQLite connection.
        gate_neuron_id: The gate neuron's ID.
        top_n: Maximum number of results.

    Returns:
        List of sqlite3.Row with (neighbor_id, reason, weight).
    """
    return conn.execute(
        """
        SELECT neighbor_id, reason, MAX(weight) AS weight
        FROM (
            SELECT target_id AS neighbor_id, reason, weight
            FROM edges
            WHERE source_id = ?
            UNION ALL
            SELECT source_id AS neighbor_id, reason, weight
            FROM edges
            WHERE target_id = ?
        )
        GROUP BY neighbor_id
        ORDER BY weight DESC, neighbor_id ASC
        LIMIT ?
        """,
        (gate_neuron_id, gate_neuron_id, top_n),
    ).fetchall()
