# =============================================================================
# Module: edge_list_by_neuron_direction.py
# Purpose: List edges connected to a neuron with direction filtering (outgoing,
#   incoming, both), pagination, and content snippets of connected neurons.
#   This is the primary query path for exploring the graph around a neuron.
# Rationale: Graph exploration needs to show what a neuron connects to, with
#   enough context (content snippet) to decide whether to follow the edge.
#   Direction filtering is essential — outgoing edges represent things this
#   neuron references, incoming edges represent things that reference this
#   neuron. The "both" mode gives a complete neighborhood view.
# Responsibility:
#   - Validate that the anchor neuron exists (exit 1 if not)
#   - Query edges filtered by direction (outgoing, incoming, or both)
#   - Join with neurons table to get content snippets (~100 chars) of connected neurons
#   - Order results by created_at DESC (newest first)
#   - Apply pagination via --limit and --offset
#   - Return empty list on no results (exit 0, not an error)
# Organization:
#   1. Imports
#   2. Constants (default direction, default limit, snippet length)
#   3. EdgeListError — custom exception
#   4. edge_list() — main entry point
#   5. _validate_neuron_exists() — check anchor neuron existence
#   6. _query_outgoing() — SELECT edges where source_id = neuron
#   7. _query_incoming() — SELECT edges where target_id = neuron
#   8. _query_both() — UNION of outgoing and incoming
#   9. _build_edge_row() — format a result row with snippet
#   10. _truncate_content() — truncate content to ~100 chars with ellipsis
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional


# -----------------------------------------------------------------------------
# Constants — default direction, pagination, snippet truncation.
# -----------------------------------------------------------------------------
DEFAULT_DIRECTION = "outgoing"
DEFAULT_LIMIT = 20
DEFAULT_OFFSET = 0
SNIPPET_MAX_LENGTH = 100
VALID_DIRECTIONS = {"outgoing", "incoming", "both"}


class EdgeListError(Exception):
    """Raised when edge listing fails (neuron not found or invalid direction).

    Attributes:
        exit_code: CLI exit code — 1 for not-found, 2 for invalid input.
        message: Human-readable description of the failure.
    """

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def edge_list(
    conn: sqlite3.Connection,
    neuron_id: int,
    direction: str = DEFAULT_DIRECTION,
    limit: int = DEFAULT_LIMIT,
    offset: int = DEFAULT_OFFSET,
) -> List[Dict[str, Any]]:
    """List edges connected to a neuron, filtered by direction.

    CLI: `memory edge list --neuron <id> [--direction outgoing|incoming|both]
          [--limit N] [--offset M]`

    Logic flow:
    1. Validate direction is one of: outgoing, incoming, both
       - Invalid -> EdgeListError(exit_code=2)
    2. Validate anchor neuron exists via _validate_neuron_exists(conn, neuron_id)
       - Not found -> EdgeListError(exit_code=1)
    3. Dispatch to direction-specific query:
       - "outgoing" -> _query_outgoing(conn, neuron_id, limit, offset)
         Returns edges where source_id == neuron_id, joined with target neuron content
       - "incoming" -> _query_incoming(conn, neuron_id, limit, offset)
         Returns edges where target_id == neuron_id, joined with source neuron content
       - "both" -> _query_both(conn, neuron_id, limit, offset)
         UNION of outgoing and incoming, still ordered by created_at DESC, paginated
    4. For each result row, build edge dict via _build_edge_row()
       - Include: source_id, target_id, reason, weight, created_at
       - Include: connected_neuron_id, connected_neuron_snippet
       - The "connected neuron" is the OTHER neuron (not the anchor):
         - For outgoing: connected = target
         - For incoming: connected = source
         - For both: depends on which side the anchor is on
    5. Return list of edge dicts (may be empty — empty is not an error)

    Args:
        conn: SQLite connection with edges and neurons tables.
        neuron_id: ID of the anchor neuron to list edges for.
        direction: One of "outgoing", "incoming", "both" (default "outgoing").
        limit: Maximum number of edges to return (default 20).
        offset: Number of edges to skip for pagination (default 0).

    Returns:
        List of edge dicts with connected neuron snippets. May be empty.

    Raises:
        EdgeListError: If neuron not found (exit_code=1) or invalid direction (exit_code=2).
    """
    # --- Step 1: Validate direction ---
    # if direction not in VALID_DIRECTIONS:
    #     raise EdgeListError(
    #         f"Invalid direction '{direction}', must be one of: {VALID_DIRECTIONS}",
    #         exit_code=2,
    #     )
    if direction not in VALID_DIRECTIONS:
        raise EdgeListError(
            f"Invalid direction '{direction}', must be one of: {sorted(VALID_DIRECTIONS)}",
            exit_code=2,
        )

    # --- Step 2: Validate anchor neuron exists ---
    # _validate_neuron_exists(conn, neuron_id)
    _validate_neuron_exists(conn, neuron_id)

    # --- Step 3: Dispatch to direction-specific query ---
    # if direction == "outgoing":
    #     rows = _query_outgoing(conn, neuron_id, limit, offset)
    # elif direction == "incoming":
    #     rows = _query_incoming(conn, neuron_id, limit, offset)
    # else:  # "both"
    #     rows = _query_both(conn, neuron_id, limit, offset)
    if direction == "outgoing":
        rows = _query_outgoing(conn, neuron_id, limit, offset)
    elif direction == "incoming":
        rows = _query_incoming(conn, neuron_id, limit, offset)
    else:  # "both"
        rows = _query_both(conn, neuron_id, limit, offset)

    # --- Step 4: Build edge dicts ---
    # return [_build_edge_row(row) for row in rows]
    return [_build_edge_row(row) for row in rows]


def _validate_neuron_exists(conn: sqlite3.Connection, neuron_id: int) -> None:
    """Check that the anchor neuron exists.

    Logic:
    1. SELECT id FROM neurons WHERE id = ?
    2. If no row -> raise EdgeListError(
           f"Neuron {neuron_id} not found", exit_code=1
       )

    Args:
        conn: SQLite connection.
        neuron_id: The anchor neuron ID to verify.

    Raises:
        EdgeListError: If neuron does not exist (exit_code=1).
    """
    row = conn.execute("SELECT id FROM neurons WHERE id = ?", (neuron_id,)).fetchone()
    if row is None:
        raise EdgeListError(f"Neuron {neuron_id} not found", exit_code=1)


def _query_outgoing(
    conn: sqlite3.Connection,
    neuron_id: int,
    limit: int,
    offset: int,
) -> List[sqlite3.Row]:
    """Query outgoing edges: source_id == neuron_id, join target content.

    SQL pattern:
        SELECT e.source_id, e.target_id, e.reason, e.weight, e.created_at,
               n.id AS connected_neuron_id, n.content AS connected_content
        FROM edges e
        JOIN neurons n ON n.id = e.target_id
        WHERE e.source_id = ?
        ORDER BY e.created_at DESC
        LIMIT ? OFFSET ?

    The connected neuron is the TARGET (the neuron this anchor points TO).

    Args:
        conn: SQLite connection.
        neuron_id: Anchor neuron ID (used as source_id filter).
        limit: Max rows to return.
        offset: Rows to skip.

    Returns:
        List of Row objects from the query.
    """
    return conn.execute(
        """SELECT e.source_id, e.target_id, e.reason, e.weight, e.created_at,
                  n.id AS connected_neuron_id, n.content AS connected_content
           FROM edges e
           JOIN neurons n ON n.id = e.target_id
           WHERE e.source_id = ?
           ORDER BY e.created_at DESC
           LIMIT ? OFFSET ?""",
        (neuron_id, limit, offset),
    ).fetchall()


def _query_incoming(
    conn: sqlite3.Connection,
    neuron_id: int,
    limit: int,
    offset: int,
) -> List[sqlite3.Row]:
    """Query incoming edges: target_id == neuron_id, join source content.

    SQL pattern:
        SELECT e.source_id, e.target_id, e.reason, e.weight, e.created_at,
               n.id AS connected_neuron_id, n.content AS connected_content
        FROM edges e
        JOIN neurons n ON n.id = e.source_id
        WHERE e.target_id = ?
        ORDER BY e.created_at DESC
        LIMIT ? OFFSET ?

    The connected neuron is the SOURCE (the neuron that points TO this anchor).

    Args:
        conn: SQLite connection.
        neuron_id: Anchor neuron ID (used as target_id filter).
        limit: Max rows to return.
        offset: Rows to skip.

    Returns:
        List of Row objects from the query.
    """
    return conn.execute(
        """SELECT e.source_id, e.target_id, e.reason, e.weight, e.created_at,
                  n.id AS connected_neuron_id, n.content AS connected_content
           FROM edges e
           JOIN neurons n ON n.id = e.source_id
           WHERE e.target_id = ?
           ORDER BY e.created_at DESC
           LIMIT ? OFFSET ?""",
        (neuron_id, limit, offset),
    ).fetchall()


def _query_both(
    conn: sqlite3.Connection,
    neuron_id: int,
    limit: int,
    offset: int,
) -> List[sqlite3.Row]:
    """Query both outgoing and incoming edges via UNION.

    SQL pattern:
        SELECT source_id, target_id, reason, weight, created_at,
               connected_neuron_id, connected_content
        FROM (
            -- Outgoing: anchor is source, connected is target
            SELECT e.source_id, e.target_id, e.reason, e.weight, e.created_at,
                   n.id AS connected_neuron_id, n.content AS connected_content
            FROM edges e
            JOIN neurons n ON n.id = e.target_id
            WHERE e.source_id = ?
            UNION ALL
            -- Incoming: anchor is target, connected is source
            SELECT e.source_id, e.target_id, e.reason, e.weight, e.created_at,
                   n.id AS connected_neuron_id, n.content AS connected_content
            FROM edges e
            JOIN neurons n ON n.id = e.source_id
            WHERE e.target_id = ?
        )
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?

    Note: UNION ALL (not UNION) because the same edge cannot appear in both
    halves — an edge has a single source and single target. Even for self-loops
    (source==target), the two sub-selects return the same row with the same
    connected_neuron_id, which is correct behavior (a self-loop is both
    outgoing and incoming).

    Args:
        conn: SQLite connection.
        neuron_id: Anchor neuron ID.
        limit: Max rows to return.
        offset: Rows to skip.

    Returns:
        List of Row objects from the UNION query.
    """
    return conn.execute(
        """SELECT source_id, target_id, reason, weight, created_at,
                  connected_neuron_id, connected_content
           FROM (
               SELECT e.source_id, e.target_id, e.reason, e.weight, e.created_at,
                      n.id AS connected_neuron_id, n.content AS connected_content
               FROM edges e
               JOIN neurons n ON n.id = e.target_id
               WHERE e.source_id = ?
               UNION ALL
               SELECT e.source_id, e.target_id, e.reason, e.weight, e.created_at,
                      n.id AS connected_neuron_id, n.content AS connected_content
               FROM edges e
               JOIN neurons n ON n.id = e.source_id
               WHERE e.target_id = ?
           )
           ORDER BY created_at DESC
           LIMIT ? OFFSET ?""",
        (neuron_id, neuron_id, limit, offset),
    ).fetchall()


def _build_edge_row(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a query result row into an edge dict with snippet.

    Logic:
    1. Extract: source_id, target_id, reason, weight, created_at,
       connected_neuron_id, connected_content from the row
    2. Truncate connected_content to snippet via _truncate_content()
    3. Return dict with all edge fields + connected_neuron_id + connected_neuron_snippet

    Args:
        row: A sqlite3.Row from one of the query functions.

    Returns:
        Dict with edge fields and connected neuron snippet.
    """
    return {
        "source_id": row["source_id"],
        "target_id": row["target_id"],
        "reason": row["reason"],
        "weight": row["weight"],
        "created_at": row["created_at"],
        "connected_neuron_id": row["connected_neuron_id"],
        "connected_neuron_snippet": _truncate_content(row["connected_content"]),
    }


def _truncate_content(content: str, max_length: int = SNIPPET_MAX_LENGTH) -> str:
    """Truncate content to approximately max_length characters with ellipsis.

    Logic:
    1. If len(content) <= max_length -> return content as-is
    2. Otherwise -> return content[:max_length] + "..."

    The truncation is character-based, not word-based, for simplicity.
    The "..." suffix means the actual visible length is max_length + 3,
    which is acceptable for display purposes.

    Args:
        content: Full neuron content string.
        max_length: Maximum characters before truncation (default 100).

    Returns:
        Content string, truncated with "..." if longer than max_length.
    """
    if len(content) <= max_length:
        return content
    return content[:max_length] + "..."
