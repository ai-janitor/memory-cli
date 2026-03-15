# =============================================================================
# Module: neuron_get_by_id.py
# Purpose: Single neuron lookup by ID with full tag, attribute, and edge hydration.
# Rationale: Get-by-ID is the most common read path — used by the CLI
#   `memory neuron get <id>` command, by the edge module to validate link
#   targets, and by the search pipeline to hydrate results. The hydration
#   logic (joining tags, attrs, and edges) is non-trivial and must be consistent
#   everywhere, so it lives in one place.
# Responsibility:
#   - Lookup neuron by integer ID
#   - Hydrate tag names from neuron_tags junction + tags table
#   - Hydrate attribute key-value pairs from neuron_attrs junction + attr_keys table
#   - Hydrate edges (both outgoing and incoming) from edges table
#   - Return None if not found (caller decides exit code)
#   - Archived neurons ARE retrievable (no status filter)
# Organization:
#   1. Imports
#   2. Constants
#   3. neuron_get() — main entry point
#   4. _hydrate_tags() — join neuron_tags to get tag names
#   5. _hydrate_attrs() — join neuron_attrs to get key-value pairs
#   6. _hydrate_edges() — query edges table for both directions
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional


# -----------------------------------------------------------------------------
# Constants — table and column names referenced in queries.
# -----------------------------------------------------------------------------
NEURONS_TABLE = "neurons"
NEURON_TAGS_TABLE = "neuron_tags"
NEURON_ATTRS_TABLE = "neuron_attrs"
TAGS_TABLE = "tags"
ATTR_KEYS_TABLE = "attr_keys"


def neuron_get(conn: sqlite3.Connection, neuron_id: int) -> Optional[Dict[str, Any]]:
    """Look up a single neuron by ID with full tag and attribute hydration.

    CLI: `memory neuron get <id>`

    Logic flow:
    1. SELECT * FROM neurons WHERE id = ?
       - Not found -> return None (caller should exit 1 with "not found" message)
    2. Convert row to dict with keys:
       id, content, created_at, updated_at, project, source, status,
       embedding_updated_at
    3. Hydrate tags via _hydrate_tags(conn, neuron_id)
       - Returns list of tag name strings
       - Add as "tags" key in dict
    4. Hydrate attrs via _hydrate_attrs(conn, neuron_id)
       - Returns dict of attr_key_name -> value
       - Add as "attrs" key in dict
    5. Return the fully hydrated dict

    Important: Archived neurons are retrievable — no status filter applied.
    This allows inspecting archived neurons before deciding to restore.

    Args:
        conn: SQLite connection with neuron/tag/attr tables.
        neuron_id: Integer ID of the neuron to retrieve.

    Returns:
        Fully hydrated neuron dict, or None if not found.
    """
    # --- Step 1: Lookup neuron row ---
    # SELECT id, content, created_at, updated_at, project, source, status,
    #        embedding_updated_at
    # FROM neurons WHERE id = ?
    # If no row returned -> return None

    # --- Step 2: Convert to dict ---
    # Map row columns to dict keys

    # --- Step 3: Hydrate tags ---
    # neuron_dict["tags"] = _hydrate_tags(conn, neuron_id)

    # --- Step 4: Hydrate attrs ---
    # neuron_dict["attrs"] = _hydrate_attrs(conn, neuron_id)

    # --- Step 5: Return ---
    # return neuron_dict

    row = conn.execute(
        """SELECT id, content, created_at, updated_at, project, source, status,
                  embedding_updated_at
           FROM neurons WHERE id = ?""",
        (neuron_id,)
    ).fetchone()

    if row is None:
        return None

    neuron_dict = dict(row)
    neuron_dict["tags"] = _hydrate_tags(conn, neuron_id)
    neuron_dict["attrs"] = _hydrate_attrs(conn, neuron_id)
    neuron_dict["edges"] = _hydrate_edges(conn, neuron_id)
    return neuron_dict


def _hydrate_tags(conn: sqlite3.Connection, neuron_id: int) -> List[str]:
    """Fetch all tag names associated with a neuron.

    Logic flow:
    1. SELECT t.name
       FROM neuron_tags nt
       JOIN tags t ON nt.tag_id = t.id
       WHERE nt.neuron_id = ?
       ORDER BY t.name ASC
    2. Return list of tag name strings (may be empty)

    Ordering by name provides deterministic output for display and testing.

    Args:
        conn: SQLite connection.
        neuron_id: ID of the neuron.

    Returns:
        Sorted list of tag name strings.
    """
    rows = conn.execute(
        """SELECT t.name
           FROM neuron_tags nt
           JOIN tags t ON nt.tag_id = t.id
           WHERE nt.neuron_id = ?
           ORDER BY t.name ASC""",
        (neuron_id,)
    ).fetchall()
    return [row[0] for row in rows]


def _hydrate_attrs(conn: sqlite3.Connection, neuron_id: int) -> Dict[str, str]:
    """Fetch all attribute key-value pairs associated with a neuron.

    Logic flow:
    1. SELECT ak.name, na.value
       FROM neuron_attrs na
       JOIN attr_keys ak ON na.attr_key_id = ak.id
       WHERE na.neuron_id = ?
       ORDER BY ak.name ASC
    2. Build dict mapping attr_key_name -> value
    3. Return dict (may be empty)

    Args:
        conn: SQLite connection.
        neuron_id: ID of the neuron.

    Returns:
        Dict mapping attribute key names to their values.
    """
    rows = conn.execute(
        """SELECT ak.name, na.value
           FROM neuron_attrs na
           JOIN attr_keys ak ON na.attr_key_id = ak.id
           WHERE na.neuron_id = ?
           ORDER BY ak.name ASC""",
        (neuron_id,)
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def _hydrate_edges(conn: sqlite3.Connection, neuron_id: int) -> List[Dict[str, Any]]:
    """Fetch all edges connected to a neuron (both outgoing and incoming).

    Logic flow:
    1. Query outgoing edges (source_id = neuron_id):
       SELECT target_id, reason, weight FROM edges WHERE source_id = ?
       For each: {"direction": "out", "target": target_id, "reason": reason, "weight": weight}
    2. Query incoming edges (target_id = neuron_id):
       SELECT source_id, reason, weight FROM edges WHERE target_id = ?
       For each: {"direction": "in", "source": source_id, "reason": reason, "weight": weight}
    3. Combine and return as a single list, outgoing first then incoming.

    The edge list is intentionally lightweight — no content snippets, no
    pagination. This is inline hydration for the neuron view, not a full
    edge exploration command (use `memory edge list` for that).

    Args:
        conn: SQLite connection.
        neuron_id: ID of the neuron.

    Returns:
        List of edge dicts with direction, connected neuron ID, reason, and weight.
        Empty list if no edges exist.
    """
    edges: List[Dict[str, Any]] = []

    # Outgoing edges: this neuron -> target
    outgoing = conn.execute(
        """SELECT target_id, reason, weight
           FROM edges
           WHERE source_id = ?
           ORDER BY created_at DESC""",
        (neuron_id,)
    ).fetchall()
    for row in outgoing:
        edges.append({
            "direction": "out",
            "target": row[0],
            "reason": row[1],
            "weight": row[2],
        })

    # Incoming edges: source -> this neuron
    incoming = conn.execute(
        """SELECT source_id, reason, weight
           FROM edges
           WHERE target_id = ?
           ORDER BY created_at DESC""",
        (neuron_id,)
    ).fetchall()
    for row in incoming:
        edges.append({
            "direction": "in",
            "source": row[0],
            "reason": row[1],
            "weight": row[2],
        })

    return edges
