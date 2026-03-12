# =============================================================================
# Module: goto_follow_edges_single_hop.py
# Purpose: Follow edges one hop from a reference neuron, returning connected
#   neurons with their edge metadata. Implements `memory neuron goto <neuron-id>`
#   — a structural navigation command that walks the graph by edge, not by time.
# Rationale: Agents need to answer "what is connected to X?" without search.
#   Goto exposes the explicit link structure — edges with reasons and weights —
#   that the agent (or ingestion pipeline) previously created. This is the
#   primary way to navigate the graph as a graph, not as a timeline or search
#   index.
# Responsibility:
#   - Validate reference neuron exists (exit 1 if not found)
#   - Query edges: outgoing (source_id = ref), incoming (target_id = ref), or both
#   - Hydrate the neuron on the OTHER side of each edge
#   - Include edge metadata: reason, weight, created_at, direction label
#   - Self-loops: if ref links to itself, the edge appears in results
#   - Exclude the reference neuron from results (except via self-loop edge)
#   - Order by edge created_at DESC, tie-break by neuron ID ASC
#   - Provide total count (pre-pagination) and paginated result set
#   - Return JSON envelope: {command, reference_id, direction, results, total, limit, offset}
#   - Each result: {neuron: {...}, edge: {reason, weight, created_at, direction}}
#   - Read-only: no data modification, no embedding model, no LLM
# Organization:
#   1. Imports and constants
#   2. goto_follow_edges() — main entry point
#   3. _validate_reference() — check reference neuron exists
#   4. _build_edge_query() — construct SQL for edge direction + pagination
#   5. _count_edges() — total count query (pre-pagination)
#   6. _hydrate_goto_results() — convert rows to neuron+edge output dicts
#   7. _build_envelope() — assemble JSON response envelope
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Literal, Optional


# -----------------------------------------------------------------------------
# Constants — defaults and table references.
# -----------------------------------------------------------------------------
DEFAULT_LIMIT = 20
DEFAULT_OFFSET = 0
DEFAULT_DIRECTION = "outgoing"
NEURONS_TABLE = "neurons"
EDGES_TABLE = "edges"


def goto_follow_edges(
    conn: sqlite3.Connection,
    neuron_id: int,
    direction: Literal["outgoing", "incoming", "both"] = DEFAULT_DIRECTION,
    limit: int = DEFAULT_LIMIT,
    offset: int = DEFAULT_OFFSET,
) -> Dict[str, Any]:
    """Follow edges from a reference neuron, returning connected neurons with edge metadata.

    CLI: `memory neuron goto <neuron-id> [--direction outgoing|incoming|both] [--limit N] [--offset M]`

    Logic flow:
    1. Validate reference neuron exists via _validate_reference()
       - If not found -> raise LookupError (caller maps to exit 1)
    2. Count total matching edges via _count_edges()
       - outgoing: WHERE source_id = ref_id
       - incoming: WHERE target_id = ref_id
       - both: WHERE source_id = ref_id OR target_id = ref_id
    3. Fetch paginated edge rows via _build_edge_query()
       - JOIN with neurons table to get the connected neuron
       - outgoing: connected neuron = target_id side
       - incoming: connected neuron = source_id side
       - both: UNION of outgoing + incoming queries
       - ORDER BY edge.created_at DESC, connected_neuron.id ASC
       - LIMIT ? OFFSET ?
    4. Hydrate results via _hydrate_goto_results()
       - Each row -> {neuron: {id, content, created_at, project, tags, source},
                      edge: {reason, weight, created_at, direction}}
       - direction label per edge: "outgoing" or "incoming" (indicates which
         side the connected neuron is on)
    5. Build envelope via _build_envelope()
    6. Return envelope dict

    Self-loop handling:
    - If ref neuron has an edge to itself (source_id = target_id = ref_id),
      the edge DOES appear in results.
    - For outgoing: self-loop appears (source_id = ref), connected neuron = ref
    - For incoming: self-loop appears (target_id = ref), connected neuron = ref
    - For both: self-loop appears TWICE (once outgoing, once incoming)
      unless deduped — spec says union, so both appearances are valid.

    Reference neuron exclusion:
    - The reference neuron is NOT filtered out of results. If it appears as the
      connected neuron (via self-loop), it is included. The "not in results"
      rule means we don't add the reference as a standalone result — but if an
      edge connects to it, the edge and its target/source are shown.

    Args:
        conn: SQLite connection with neuron and edge tables.
        neuron_id: ID of the reference neuron to follow edges from.
        direction: "outgoing", "incoming", or "both".
        limit: Max results to return (default 20).
        offset: Number of results to skip (default 0).

    Returns:
        JSON-serializable dict:
        {command: "goto", reference_id, direction, results: [...], total, limit, offset}

    Raises:
        LookupError: If reference neuron_id does not exist.
    """
    # --- Step 1: Validate reference neuron exists ---
    # _validate_reference(conn, neuron_id)
    # If None -> raise LookupError(f"Neuron {neuron_id} not found")

    # --- Step 2: Count total edges pre-pagination ---
    # total = _count_edges(conn, neuron_id, direction)

    # --- Step 3: Fetch paginated edge + neuron rows ---
    # rows = _build_edge_query(conn, neuron_id, direction, limit, offset)

    # --- Step 4: Hydrate results ---
    # results = _hydrate_goto_results(conn, rows)

    # --- Step 5: Build envelope ---
    # return _build_envelope(neuron_id, direction, results, total, limit, offset)

    pass


def _validate_reference(conn: sqlite3.Connection, neuron_id: int) -> Optional[sqlite3.Row]:
    """Check that the reference neuron exists and return its row.

    Logic flow:
    1. SELECT id FROM neurons WHERE id = ?
    2. Return row or None

    Args:
        conn: SQLite connection.
        neuron_id: Reference neuron ID.

    Returns:
        Row with id, or None if not found.
    """
    pass


def _build_edge_query(
    conn: sqlite3.Connection,
    ref_id: int,
    direction: Literal["outgoing", "incoming", "both"],
    limit: int,
    offset: int,
) -> List[sqlite3.Row]:
    """Build and execute the paginated edge traversal query.

    Logic flow:
    1. Determine query shape from direction:
       - outgoing:
         SELECT e.id as edge_id, e.source_id, e.target_id, e.reason, e.weight,
                e.created_at as edge_created_at,
                n.id as neuron_id, n.content, n.created_at, n.project, n.source,
                'outgoing' as edge_direction
         FROM edges e
         JOIN neurons n ON e.target_id = n.id
         WHERE e.source_id = ?
       - incoming:
         Same but JOIN neurons n ON e.source_id = n.id
         WHERE e.target_id = ?
         edge_direction = 'incoming'
       - both:
         UNION ALL of outgoing + incoming queries
         (self-loops appear in both halves — this is correct per spec)
    2. Apply ordering: ORDER BY edge_created_at DESC, neuron_id ASC
    3. Apply pagination: LIMIT ? OFFSET ?
    4. Return list of rows

    Note on ordering with UNION ALL (both):
    - Wrap the UNION ALL in a subquery, apply ORDER BY and LIMIT on outer query
    - This ensures correct ordering across both directions

    Args:
        conn: SQLite connection.
        ref_id: Reference neuron ID.
        direction: "outgoing", "incoming", or "both".
        limit: LIMIT value.
        offset: OFFSET value.

    Returns:
        List of rows with edge + connected neuron data.
    """
    pass


def _count_edges(
    conn: sqlite3.Connection,
    ref_id: int,
    direction: Literal["outgoing", "incoming", "both"],
) -> int:
    """Count total edges matching the direction filter (pre-pagination).

    Logic flow:
    1. Determine WHERE clause from direction:
       - outgoing: COUNT(*) FROM edges WHERE source_id = ?
       - incoming: COUNT(*) FROM edges WHERE target_id = ?
       - both: sum of outgoing count + incoming count
         (self-loops counted once per direction, so a self-loop adds 2 to "both" total)
         Alternatively: COUNT from UNION ALL subquery
    2. Return integer count

    Note: "both" count must match the UNION ALL row count, not a simple
    OR-based count, because self-loops appear twice in the UNION ALL.

    Args:
        conn: SQLite connection.
        ref_id: Reference neuron ID.
        direction: "outgoing", "incoming", or "both".

    Returns:
        Total count of matching edges.
    """
    pass


def _hydrate_goto_results(conn: sqlite3.Connection, rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    """Convert raw edge+neuron rows to output dicts with hydrated tags.

    Logic flow:
    1. For each row:
       a. Build neuron dict: {id, content, created_at, project, source}
       b. Hydrate tags for the connected neuron:
          - SELECT t.name FROM neuron_tags nt
            JOIN tags t ON nt.tag_id = t.id
            WHERE nt.neuron_id = ?
            ORDER BY t.name ASC
       c. Add "tags" key to neuron dict
       d. Build edge dict: {reason, weight, created_at, direction}
          - reason: the semantic label for this edge
          - weight: float edge strength
          - created_at: edge creation timestamp (edge_created_at from query)
          - direction: "outgoing" or "incoming" label from query
       e. Combine: {neuron: neuron_dict, edge: edge_dict}
    2. Return list of combined dicts

    Args:
        conn: SQLite connection.
        rows: Raw rows from edge query (edge + neuron columns).

    Returns:
        List of {neuron: {...}, edge: {...}} dicts.
    """
    pass


def _build_envelope(
    reference_id: int,
    direction: str,
    results: List[Dict[str, Any]],
    total: int,
    limit: int,
    offset: int,
) -> Dict[str, Any]:
    """Assemble the JSON response envelope for goto results.

    Logic flow:
    1. Return dict with:
       - command: "goto"
       - reference_id: the reference neuron ID
       - direction: "outgoing", "incoming", or "both"
       - results: list of {neuron, edge} dicts
       - total: pre-pagination count
       - limit: applied limit
       - offset: applied offset

    Args:
        reference_id: The reference neuron ID.
        direction: "outgoing", "incoming", or "both".
        results: Hydrated result dicts.
        total: Pre-pagination total count.
        limit: Applied limit.
        offset: Applied offset.

    Returns:
        JSON-serializable envelope dict.
    """
    pass
