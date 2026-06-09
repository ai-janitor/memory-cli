# =============================================================================
# Module: tree_recursive_lineage.py
# Purpose: Recursive multi-hop tree traversal from a root neuron. Returns a
#   nested tree of descendants (down), ancestors (up), or both, depth-bounded
#   and cycle-safe. The multi-hop analog of goto_follow_edges_single_hop.
# Rationale: Goto answers "what is connected to X?" (one hop). Tree answers
#   "what is the full subtree rooted at X?" (all hops up to depth limit).
#   Agents use this to materialise hub structures, lineage chains, and
#   component hierarchies without repeated single-hop calls.
# Responsibility:
#   - Recurse goto_follow_edges for each hop (down=outgoing, up=incoming)
#   - Filter results by edge_type (reason) when provided
#   - Bound recursion at depth limit
#   - Prevent infinite loops via visited set (cycle-safe)
#   - Return nested dict: {id, content, depth, children: [...]}
#   - Read-only: no data modification, no embeddings, no LLMs
# Organization:
#   1. Imports and constants
#   2. tree_lineage() — public entry point
#   3. _expand_node() — recursive inner helper
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Set

from memory_cli.traversal.goto_follow_edges_single_hop import goto_follow_edges


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
_DIRECTION_MAP = {
    "down": "outgoing",
    "up": "incoming",
    "both": "both",
}
# Large limit so pagination never silently drops children. [?] A4
_HOP_LIMIT = 10_000


def tree_lineage(
    conn: sqlite3.Connection,
    root_id: int,
    direction: str = "down",
    depth: int = 10,
    edge_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a nested tree of neurons reachable from root_id.

    Args:
        conn:       SQLite connection with neuron/edge tables.
        root_id:    ID of the root neuron.
        direction:  "down" (descendants), "up" (ancestors), or "both".
        depth:      Max levels to recurse (depth=0 = root only, depth=1 = root + one level).
        edge_type:  If set, only follow edges whose reason == edge_type.

    Returns:
        Nested dict: {id, content, depth, children: [...same shape...]}

    Raises:
        LookupError: If root_id does not exist.
    """
    goto_dir = _DIRECTION_MAP.get(direction, "outgoing")

    # Validate root exists by attempting a goto call (raises LookupError if missing)
    goto_follow_edges(conn, root_id, direction=goto_dir, limit=1, offset=0)

    # Fetch root content
    row = conn.execute("SELECT content FROM neurons WHERE id = ?", (root_id,)).fetchone()
    root_content = row[0] if row else ""

    visited: Set[int] = set()
    return _expand_node(conn, root_id, root_content, goto_dir, depth, edge_type, visited, current_depth=0)


def _expand_node(
    conn: sqlite3.Connection,
    neuron_id: int,
    content: str,
    goto_dir: str,
    max_depth: int,
    edge_type: Optional[str],
    visited: Set[int],
    current_depth: int,
) -> Dict[str, Any]:
    """Recursively build one node of the tree.

    Args:
        conn:          SQLite connection.
        neuron_id:     Current node ID.
        content:       Current node content.
        goto_dir:      goto direction ("outgoing"/"incoming"/"both").
        max_depth:     Max recursion depth from root.
        edge_type:     Optional edge reason filter.
        visited:       Set of already-visited neuron IDs (mutation in place).
        current_depth: Depth level of this node from root.

    Returns:
        {id, content, depth, children: [...]}
    """
    visited.add(neuron_id)

    children: List[Dict[str, Any]] = []

    if current_depth < max_depth:
        envelope = goto_follow_edges(conn, neuron_id, direction=goto_dir, limit=_HOP_LIMIT, offset=0)
        results = envelope.get("results", [])

        for item in results:
            edge = item.get("edge", {})
            # Filter by edge_type when specified
            if edge_type is not None and edge.get("reason") != edge_type:
                continue
            child = item.get("neuron", {})
            child_id = child.get("id")
            child_content = child.get("content", "")
            if child_id is None or child_id in visited:
                continue
            child_node = _expand_node(
                conn, child_id, child_content, goto_dir,
                max_depth, edge_type, visited, current_depth + 1
            )
            children.append(child_node)

    return {
        "id": neuron_id,
        "content": content,
        "depth": current_depth,
        "children": children,
    }
