# =============================================================================
# Module: export_neurons_tags_edges_to_json.py
# Purpose: Query neurons from the database with optional tag filters, resolve
#   internal IDs to portable string names for tags and attributes, filter edges
#   to only those where both endpoints are in the export set, and produce the
#   final export data structure ready for envelope wrapping.
# Rationale: The export must be fully self-contained and DB-independent. Tags
#   and attrs are stored as internal integer IDs in the DB, but exported as
#   human-readable string names. Edges referencing neurons outside the export
#   set are silently dropped — partial edge exports would create broken refs
#   on import. Vectors are opt-in because they're large (768 floats each).
# Responsibility:
#   - Accept filter params (--tags AND, --tags-any OR, mutually exclusive)
#   - Query matching neurons from DB, ordered by created_at ASC
#   - Resolve tag IDs to tag names for each neuron
#   - Resolve attribute IDs to key/value string pairs for each neuron
#   - Optionally include vector embeddings and vector_model per neuron
#   - Build the set of exported neuron IDs
#   - Query all edges, filter to those where BOTH source and target are in set
#   - Return structured dict ready for envelope wrapping
# Organization:
#   1. Imports
#   2. export_neurons() — main entry point
#   3. _query_neurons_with_tag_filter() — DB query with AND/OR tag filtering
#   4. _resolve_neuron_tags() — map tag IDs to tag name strings
#   5. _resolve_neuron_attrs() — map attr IDs to key/value string pairs
#   6. _fetch_neuron_vector() — retrieve vector embedding if requested
#   7. _serialize_neuron() — build single neuron dict for export
#   8. _filter_edges_to_export_set() — keep only edges within the neuron set
#   9. _serialize_edge() — build single edge dict for export
# =============================================================================

from __future__ import annotations

import sqlite3
import struct
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set


def export_neurons(
    db_conn: sqlite3.Connection,
    tags_and: Optional[List[str]] = None,
    tags_any: Optional[List[str]] = None,
    include_vectors: bool = False,
) -> Dict[str, Any]:
    """Query neurons, resolve names, filter edges, return export-ready data.

    Args:
        db_conn: Active SQLite connection to the memory database.
        tags_and: If provided, only export neurons that have ALL of these tags.
        tags_any: If provided, export neurons that have ANY of these tags.
            Mutually exclusive with tags_and.
        include_vectors: If True, include 768-float vector and vector_model
            per neuron.

    Returns:
        Dict with keys: neurons (list), edges (list), vector_model (str or None),
        vector_dimensions (int or None), vectors_included (bool).

    Logic flow:
    1. Validate that tags_and and tags_any are not both provided
       — raise ValueError if both are set
    2. Call _query_neurons_with_tag_filter() to get raw neuron rows
    3. For each neuron row:
       a. Call _resolve_neuron_tags() to get list of tag name strings
       b. Call _resolve_neuron_attrs() to get dict of key-value string pairs
       c. If include_vectors, call _fetch_neuron_vector() to get float list
       d. Call _serialize_neuron() to build the export dict for this neuron
    4. Collect all exported neuron IDs into a set
    5. Call _filter_edges_to_export_set() with that ID set
    6. Serialize each edge via _serialize_edge()
    7. Determine vector_model and vector_dimensions from DB config if vectors included
    8. Return the assembled dict with neurons, edges, and vector metadata

    Error paths:
    - tags_and + tags_any both set -> raise ValueError
    - DB query failure -> propagate sqlite3 error
    - Zero neurons matched -> valid result (empty lists), not an error
    """
    # 1. Validate that tags_and and tags_any are not both provided
    if tags_and and tags_any:
        raise ValueError("tags_and and tags_any are mutually exclusive — provide at most one")

    # 2. Call _query_neurons_with_tag_filter() to get raw neuron rows
    neuron_rows = _query_neurons_with_tag_filter(db_conn, tags_and=tags_and, tags_any=tags_any)

    # 3. For each neuron row, resolve tags, attrs, optional vector
    serialized_neurons: List[Dict[str, Any]] = []
    for row in neuron_rows:
        tags = _resolve_neuron_tags(db_conn, row["id"])
        attrs = _resolve_neuron_attrs(db_conn, row["id"])
        vector: Optional[List[float]] = None
        vector_model: Optional[str] = None
        if include_vectors:
            vector = _fetch_neuron_vector(db_conn, row["id"])
            if vector is not None:
                # Read vector model from meta
                meta_row = db_conn.execute(
                    "SELECT value FROM meta WHERE key = 'vector_model'",
                ).fetchone()
                vector_model = meta_row["value"] if meta_row else None
        serialized_neurons.append(
            _serialize_neuron(row, tags, attrs, vector=vector, vector_model=vector_model)
        )

    # 4. Collect all exported neuron IDs into a set
    exported_neuron_ids: Set[int] = {row["id"] for row in neuron_rows}

    # 5. Call _filter_edges_to_export_set() with that ID set
    edge_rows = _filter_edges_to_export_set(db_conn, exported_neuron_ids)

    # 6. Serialize each edge
    serialized_edges = [_serialize_edge(e) for e in edge_rows]

    # 7. Determine vector_model and vector_dimensions from DB config if vectors included
    db_vector_model: Optional[str] = None
    db_vector_dims: Optional[int] = None
    if include_vectors:
        meta_model = db_conn.execute(
            "SELECT value FROM meta WHERE key = 'vector_model'",
        ).fetchone()
        meta_dims = db_conn.execute(
            "SELECT value FROM meta WHERE key = 'vector_dimensions'",
        ).fetchone()
        db_vector_model = meta_model["value"] if meta_model else None
        db_vector_dims = int(meta_dims["value"]) if meta_dims else None

    # 8. Return the assembled dict
    return {
        "neurons": serialized_neurons,
        "edges": serialized_edges,
        "vectors_included": include_vectors,
        "vector_model": db_vector_model,
        "vector_dimensions": db_vector_dims,
    }


def _query_neurons_with_tag_filter(
    db_conn: sqlite3.Connection,
    tags_and: Optional[List[str]] = None,
    tags_any: Optional[List[str]] = None,
) -> List[sqlite3.Row]:
    """Query neurons from DB with optional tag filtering.

    Args:
        db_conn: Active SQLite connection.
        tags_and: AND filter — neuron must have ALL these tags.
        tags_any: OR filter — neuron must have at least ONE of these tags.

    Returns:
        List of neuron rows ordered by created_at ASC.

    Logic flow:
    1. If no filters: SELECT all non-archived neurons ORDER BY created_at ASC
    2. If tags_and:
       a. Resolve tag names to tag IDs via tag registry lookup
       b. JOIN neuron_tags on neuron_id
       c. WHERE tag_id IN (resolved IDs)
       d. GROUP BY neuron_id HAVING COUNT(DISTINCT tag_id) = len(tags_and)
       e. ORDER BY created_at ASC
    3. If tags_any:
       a. Resolve tag names to tag IDs via tag registry lookup
       b. JOIN neuron_tags on neuron_id
       c. WHERE tag_id IN (resolved IDs)
       d. SELECT DISTINCT to avoid duplicates when neuron matches multiple tags
       e. ORDER BY created_at ASC
    4. All queries order by created_at ASC for deterministic output
    """
    db_conn.row_factory = sqlite3.Row
    # 1. No filters: SELECT all active neurons ORDER BY created_at ASC
    if not tags_and and not tags_any:
        return db_conn.execute(
            "SELECT * FROM neurons WHERE status = 'active' ORDER BY created_at ASC"
        ).fetchall()

    # 2. tags_and: neuron must have ALL these tags (HAVING COUNT match)
    if tags_and:
        # Resolve tag names to IDs; skip unknown tags (no neurons can match)
        tag_ids = []
        for name in tags_and:
            row = db_conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
            if row is None:
                return []  # tag doesn't exist, no neurons can match ALL
            tag_ids.append(row["id"])
        placeholders = ",".join("?" * len(tag_ids))
        query = f"""
            SELECT n.*
            FROM neurons n
            JOIN neuron_tags nt ON nt.neuron_id = n.id
            WHERE n.status = 'active' AND nt.tag_id IN ({placeholders})
            GROUP BY n.id
            HAVING COUNT(DISTINCT nt.tag_id) = {len(tag_ids)}
            ORDER BY n.created_at ASC
        """
        return db_conn.execute(query, tag_ids).fetchall()

    # 3. tags_any: neuron must have at least ONE of these tags
    if tags_any:
        tag_ids = []
        for name in tags_any:
            row = db_conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
            if row is not None:
                tag_ids.append(row["id"])
        if not tag_ids:
            return []  # none of the tags exist
        placeholders = ",".join("?" * len(tag_ids))
        query = f"""
            SELECT DISTINCT n.*
            FROM neurons n
            JOIN neuron_tags nt ON nt.neuron_id = n.id
            WHERE n.status = 'active' AND nt.tag_id IN ({placeholders})
            ORDER BY n.created_at ASC
        """
        return db_conn.execute(query, tag_ids).fetchall()

    return []


def _resolve_neuron_tags(
    db_conn: sqlite3.Connection,
    neuron_id: int,
) -> List[str]:
    """Map a neuron's tag associations to tag name strings.

    Logic flow:
    1. Query neuron_tags table for this neuron_id
    2. JOIN with tags table to get tag names
    3. Return sorted list of tag name strings (sorted for determinism)
    """
    # 1. Query neuron_tags JOIN tags to get tag names
    rows = db_conn.execute(
        """
        SELECT t.name
        FROM neuron_tags nt
        JOIN tags t ON nt.tag_id = t.id
        WHERE nt.neuron_id = ?
        ORDER BY t.name ASC
        """,
        (neuron_id,),
    ).fetchall()
    return [row[0] for row in rows]


def _resolve_neuron_attrs(
    db_conn: sqlite3.Connection,
    neuron_id: int,
) -> Dict[str, str]:
    """Map a neuron's attribute associations to key-value string pairs.

    Logic flow:
    1. Query neuron_attrs table for this neuron_id
    2. JOIN with attr_keys table to get attr key names
    3. Return dict of {attr_key_name: attr_value}
    """
    # 1. Query neuron_attrs JOIN attr_keys to get key names and values
    rows = db_conn.execute(
        """
        SELECT ak.name, na.value
        FROM neuron_attrs na
        JOIN attr_keys ak ON na.attr_key_id = ak.id
        WHERE na.neuron_id = ?
        """,
        (neuron_id,),
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def _fetch_neuron_vector(
    db_conn: sqlite3.Connection,
    neuron_id: int,
) -> Optional[List[float]]:
    """Retrieve the vector embedding for a neuron if it exists.

    Logic flow:
    1. Query the vectors table for this neuron_id
    2. Deserialize the stored blob into a list of 768 floats
    3. Return the list, or None if no vector stored

    Note: Vector storage format is sqlite-vec's native blob format.
    Deserialization must match the serialization used in the embedding module.
    """
    # 1. Query the neurons_vec table for this neuron_id
    row = db_conn.execute(
        "SELECT embedding FROM neurons_vec WHERE neuron_id = ?",
        (neuron_id,),
    ).fetchone()
    if row is None:
        return None
    # 2. Deserialize the stored blob into a list of floats
    # sqlite-vec stores vectors as packed 32-bit little-endian floats
    blob = row[0]
    num_floats = len(blob) // 4
    return list(struct.unpack(f"<{num_floats}f", blob))


def _serialize_neuron(
    neuron_row: sqlite3.Row,
    tags: List[str],
    attrs: Dict[str, str],
    vector: Optional[List[float]] = None,
    vector_model: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a single neuron dict for the export envelope.

    Output fields:
    - id: int (integer primary key from neurons table)
    - content: str
    - created_at: str (ISO 8601)
    - updated_at: str (ISO 8601)
    - project: str or null
    - source: str or null
    - tags: list[str] (tag names)
    - attributes: dict[str, str] (key-value)
    - vector: list[float] (only if include_vectors, else omitted entirely)
    - vector_model: str (only if include_vectors, else omitted entirely)

    Logic flow:
    1. Extract core fields from neuron_row: id, content, created_at, updated_at,
       project, source
    2. Attach resolved tags list
    3. Attach resolved attrs dict
    4. If vector is not None, attach vector list and vector_model string
    5. Return the assembled dict
    """
    # 1. Extract core fields from neuron_row
    # created_at and updated_at are stored as epoch ms integers — convert to ISO 8601
    created_ms = neuron_row["created_at"]
    updated_ms = neuron_row["updated_at"]
    created_at_iso = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).isoformat()
    updated_at_iso = datetime.fromtimestamp(updated_ms / 1000, tz=timezone.utc).isoformat()

    # 2. Build neuron dict with core fields, tags, attrs
    neuron_dict: Dict[str, Any] = {
        "id": neuron_row["id"],
        "content": neuron_row["content"],
        "created_at": created_at_iso,
        "updated_at": updated_at_iso,
        "project": neuron_row["project"],
        "source": neuron_row["source"],
        "tags": tags,
        "attributes": attrs,
    }

    # 3. If vector is not None, attach vector list and vector_model string
    if vector is not None:
        neuron_dict["vector"] = vector
        neuron_dict["vector_model"] = vector_model

    return neuron_dict


def _filter_edges_to_export_set(
    db_conn: sqlite3.Connection,
    exported_neuron_ids: Set[int],
) -> List[sqlite3.Row]:
    """Query all edges where BOTH source and target are in the export set.

    Logic flow:
    1. Query all edges from edges table
    2. Filter to those where source_id IN exported_neuron_ids
       AND target_id IN exported_neuron_ids
    3. Could be done in SQL with IN clause, or post-filter in Python
       — SQL preferred for large datasets, Python filter as fallback
    4. Order by created_at ASC for determinism

    Note: Edges to neurons outside the export set are silently dropped.
    This is intentional — partial edges would break referential integrity
    on import.
    """
    if not exported_neuron_ids:
        return []
    # Use SQL IN clause with the exported ID set for efficiency
    id_list = list(exported_neuron_ids)
    placeholders = ",".join("?" * len(id_list))
    query = f"""
        SELECT *
        FROM edges
        WHERE source_id IN ({placeholders})
          AND target_id IN ({placeholders})
        ORDER BY created_at ASC
    """
    # Pass the list twice (once for source_id, once for target_id)
    return db_conn.execute(query, id_list + id_list).fetchall()


def _serialize_edge(edge_row: sqlite3.Row) -> Dict[str, Any]:
    """Build a single edge dict for the export envelope.

    Output fields:
    - source_id: int (integer ID of source neuron)
    - target_id: int (integer ID of target neuron)
    - reason: str (semantic label for the relationship)
    - weight: float
    - created_at: str (ISO 8601)

    Logic flow:
    1. Extract fields from edge_row
    2. Return dict with string representations
    """
    # created_at is stored as epoch ms integer — convert to ISO 8601
    created_ms = edge_row["created_at"]
    created_at_iso = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).isoformat()
    return {
        "source_id": edge_row["source_id"],
        "target_id": edge_row["target_id"],
        "reason": edge_row["reason"],
        "weight": edge_row["weight"],
        "created_at": created_at_iso,
    }
