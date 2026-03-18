# =============================================================================
# Module: neuron_delete_hard.py
# Purpose: Hard-delete a single neuron and all associated records (edges,
#   tags, attrs, vector embedding). Unlike prune (bulk archive), delete is
#   surgical and permanent — the neuron cannot be restored.
# Rationale: Agents and users need a way to surgically remove a single neuron
#   without going through archive → prune. This is the "rm" to prune's
#   "find ... -delete".
# Responsibility:
#   - neuron_delete: validate neuron exists, hard-delete neuron + edges +
#     tags + attrs + vector embedding, return summary
# Organization:
#   1. Imports
#   2. NeuronDeleteError exception
#   3. neuron_delete() — main entry point
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import Any, Dict


class NeuronDeleteError(Exception):
    """Raised when neuron deletion fails (e.g., neuron not found)."""


def neuron_delete(
    conn: sqlite3.Connection,
    neuron_id: int,
) -> Dict[str, Any]:
    """Hard-delete a neuron and all its edges, tags, attrs, and vector.

    CLI: `memory neuron delete <id> --confirm`

    This is a PERMANENT operation. The neuron cannot be restored after
    deletion. Use `memory neuron archive <id>` for soft-delete.

    Args:
        conn: SQLite connection.
        neuron_id: ID of the neuron to delete.

    Returns:
        Dict with keys:
            - id: int — the deleted neuron's ID
            - content_preview: str — first 80 chars of content
            - edges_removed: int — number of edges removed
            - deleted: True

    Raises:
        NeuronDeleteError: If neuron does not exist.
    """
    # Verify neuron exists and capture content for the response
    row = conn.execute(
        "SELECT id, content FROM neurons WHERE id = ?",
        (neuron_id,),
    ).fetchone()
    if row is None:
        raise NeuronDeleteError(f"Neuron {neuron_id} not found")

    content = row[1]
    preview = (content[:80] + "...") if len(content) > 80 else content

    # Count edges before deletion (for the report)
    edge_row = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE source_id = ? OR target_id = ?",
        (neuron_id, neuron_id),
    ).fetchone()
    edges_removed = edge_row[0] if edge_row else 0

    # Delete edges
    conn.execute(
        "DELETE FROM edges WHERE source_id = ? OR target_id = ?",
        (neuron_id, neuron_id),
    )

    # Delete tags junction
    conn.execute(
        "DELETE FROM neuron_tags WHERE neuron_id = ?",
        (neuron_id,),
    )

    # Delete attrs junction
    conn.execute(
        "DELETE FROM neuron_attrs WHERE neuron_id = ?",
        (neuron_id,),
    )

    # Delete vector embedding (may not exist — that's fine)
    try:
        conn.execute(
            "DELETE FROM neurons_vec WHERE neuron_id = ?",
            (neuron_id,),
        )
    except Exception:
        pass  # vec0 table may not exist in all configurations

    # Delete the neuron itself
    conn.execute(
        "DELETE FROM neurons WHERE id = ?",
        (neuron_id,),
    )

    conn.commit()

    return {
        "id": neuron_id,
        "content_preview": preview,
        "edges_removed": edges_removed,
        "deleted": True,
    }
