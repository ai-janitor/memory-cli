# =============================================================================
# FILE: src/memory_cli/gate/gate_compute_densest_node.py
# PURPOSE: Find the densest node (most edges) in a memory store — the "gate".
# RATIONALE: The gate is the natural entry point into a memory mansion. It has
#            the most connections and thus the most context about the store.
# RESPONSIBILITY:
#   - compute_densest_node(conn) -> GateResult or None
#   - _count_edges_per_neuron(conn) -> sqlite3.Row or None
# ORGANIZATION:
#   1. GateResult NamedTuple
#   2. compute_densest_node — public API
#   3. _count_edges_per_neuron — SQL helper
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import NamedTuple, Optional


# =============================================================================
# DATA TYPES
# =============================================================================
class GateResult(NamedTuple):
    """The front-door neuron and its total edge count."""

    neuron_id: int
    edge_count: int


def compute_densest_node(conn: sqlite3.Connection) -> Optional[GateResult]:
    """Find the neuron with the most total edges in the store.

    The densest node is the "gate" — the natural entry point into the memory
    mansion. It has the most connections and thus the most context about
    the store's knowledge graph.

    Logic flow:
    1. Query: UNION ALL source_id and target_id from edges to count all
       edge endpoints per neuron.
    2. JOIN with neurons table to exclude orphaned edges.
    3. ORDER BY edge_count DESC, id ASC (tie-break by lowest ID).
    4. LIMIT 1 — return only the top neuron.
    5. If no rows (empty store), return None.
    6. Otherwise, return GateResult(neuron_id, edge_count).

    Args:
        conn: SQLite connection with neurons and edges tables.

    Returns:
        GateResult with the densest neuron's id and edge count, or None
        if the store has no edges.
    """
    row = _count_edges_per_neuron(conn)
    if row is None:
        return None
    return GateResult(neuron_id=row[0], edge_count=row[1])


def _count_edges_per_neuron(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """Aggregate total edge degree per neuron and return the top row.

    SQL strategy:
    - UNION ALL the two directions: outgoing (source_id) and incoming (target_id)
      into a single column of neuron_ids.
    - JOIN with neurons to filter to existing neurons.
    - GROUP BY neuron_id, COUNT(*) as edge_count.
    - ORDER BY edge_count DESC, neuron_id ASC.
    - LIMIT 1.

    Args:
        conn: SQLite connection.

    Returns:
        Single sqlite3.Row with (neuron_id, edge_count), or None.
    """
    return conn.execute(
        """
        SELECT n.id AS neuron_id, COUNT(*) AS edge_count
        FROM (
            SELECT source_id AS neuron_id FROM edges
            UNION ALL
            SELECT target_id AS neuron_id FROM edges
        ) AS all_endpoints
        INNER JOIN neurons n ON n.id = all_endpoints.neuron_id
        GROUP BY n.id
        ORDER BY edge_count DESC, n.id ASC
        LIMIT 1
        """
    ).fetchone()
