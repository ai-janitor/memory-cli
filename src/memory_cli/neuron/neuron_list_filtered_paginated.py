# =============================================================================
# Module: neuron_list_filtered_paginated.py
# Purpose: Filtered, paginated neuron listing with AND/OR tag filters, status
#   filter, project filter, and offset-based pagination.
# Rationale: List is the primary discovery command for neurons. It must support
#   flexible filtering to be useful in large memory stores. AND/OR tag filtering
#   is the most complex part — AND means "has ALL of these tags", OR means "has
#   ANY of these tags", and they can be combined. This module builds the SQL
#   dynamically based on which filters are active.
# Responsibility:
#   - Build dynamic SQL query based on active filters
#   - AND tag filter: neurons that have ALL specified tags
#   - OR tag filter: neurons that have ANY of the specified tags
#   - Combined AND+OR: must satisfy BOTH conditions
#   - Status filter: active (default), archived, or all
#   - Project filter: exact match on project column
#   - Pagination: LIMIT/OFFSET with most-recent-first ordering
#   - Hydrate each result with tags and attrs
# Organization:
#   1. Imports
#   2. Constants (defaults)
#   3. neuron_list() — main entry point
#   4. _build_list_query() — dynamic SQL builder
#   5. _resolve_tag_ids() — resolve tag names to IDs for filtering
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------------------------------------------------------
# Constants — defaults for pagination and status filtering.
# -----------------------------------------------------------------------------
DEFAULT_STATUS = "active"
DEFAULT_LIMIT = 50
DEFAULT_OFFSET = 0
VALID_STATUSES = {"active", "archived", "all"}


def neuron_list(
    conn: sqlite3.Connection,
    tags_and: Optional[List[str]] = None,
    tags_any: Optional[List[str]] = None,
    status: str = DEFAULT_STATUS,
    project: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = DEFAULT_OFFSET,
) -> List[Dict[str, Any]]:
    """List neurons with optional filters and pagination.

    CLI: `memory neuron list [--tags TAG,...] [--tags-any TAG,...] [--status STATUS]
          [--project PROJECT] [--limit N] [--offset M]`

    Logic flow:
    1. Validate status is one of: active, archived, all
       - Invalid -> raise ValueError
    2. Resolve tag names to IDs (if tag filters provided):
       a. For tags_and: resolve each tag name via tag registry lookup
          - If any tag name doesn't exist -> return empty list early
            (AND filter can't be satisfied with a non-existent tag)
       b. For tags_any: resolve each tag name via tag registry lookup
          - Filter out non-existent tags (OR filter still works with remaining)
          - If ALL tags_any are non-existent -> return empty list early
    3. Build SQL query via _build_list_query()
       - Base: SELECT id FROM neurons
       - Add WHERE clauses based on active filters
       - ORDER BY created_at DESC (most recent first)
       - LIMIT ? OFFSET ?
    4. Execute query and collect neuron IDs
    5. For each neuron ID, call neuron_get() to hydrate full record
       - This ensures consistent hydration logic (DRY with get-by-id)
    6. Return list of hydrated neuron dicts
       - Empty list is a valid result (exit 0, not exit 1)

    Filter combinations:
    - tags_and only: neurons must have ALL specified tags
    - tags_any only: neurons must have ANY of the specified tags
    - tags_and + tags_any: must satisfy BOTH conditions
    - status "active": WHERE status = 'active' (default)
    - status "archived": WHERE status = 'archived'
    - status "all": no status filter
    - project: WHERE project = ?

    Args:
        conn: SQLite connection.
        tags_and: Optional list of tag names — AND filter (must have all).
        tags_any: Optional list of tag names — OR filter (must have any).
        status: Status filter: "active" (default), "archived", or "all".
        project: Optional project name filter (exact match).
        limit: Max number of results (default 50).
        offset: Number of results to skip (default 0).

    Returns:
        List of fully hydrated neuron dicts. Empty list if no matches.

    Raises:
        ValueError: If status is not a valid value.
    """
    # --- Step 1: Validate status ---
    # if status not in VALID_STATUSES: raise ValueError

    # --- Step 2: Resolve tag IDs ---
    # and_tag_ids = _resolve_tag_ids(conn, tags_and) if tags_and else None
    # any_tag_ids = _resolve_tag_ids(conn, tags_any) if tags_any else None
    # Early return [] if AND tags have any None (unresolvable name)
    # Early return [] if ALL OR tags are None (all unresolvable)
    # For OR: filter out Nones, keep resolved IDs

    # --- Step 3: Build query ---
    # query, params = _build_list_query(and_tag_ids, any_tag_ids, status, project, limit, offset)

    # --- Step 4: Execute ---
    # rows = conn.execute(query, params).fetchall()
    # neuron_ids = [row[0] for row in rows]

    # --- Step 5: Hydrate each result ---
    # from .neuron_get_by_id import neuron_get
    # results = [neuron_get(conn, nid) for nid in neuron_ids]
    # Filter out any None results (shouldn't happen, but defensive)

    # --- Step 6: Return ---
    # return results

    from .neuron_get_by_id import neuron_get

    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {VALID_STATUSES}")

    and_tag_ids = None
    if tags_and:
        resolved = _resolve_tag_ids(conn, tags_and)
        if resolved is None or None in resolved:
            return []
        and_tag_ids = [tid for tid in resolved if tid is not None]

    any_tag_ids = None
    if tags_any:
        resolved = _resolve_tag_ids(conn, tags_any)
        if resolved is not None:
            any_tag_ids = [tid for tid in resolved if tid is not None]
            if not any_tag_ids:
                return []

    query, params = _build_list_query(and_tag_ids, any_tag_ids, status, project, limit, offset)
    rows = conn.execute(query, params).fetchall()
    neuron_ids = [row[0] for row in rows]

    results = [neuron_get(conn, nid) for nid in neuron_ids]
    return [n for n in results if n is not None]


def _build_list_query(
    and_tag_ids: Optional[List[int]],
    any_tag_ids: Optional[List[int]],
    status: str,
    project: Optional[str],
    limit: int,
    offset: int,
) -> Tuple[str, List[Any]]:
    """Build dynamic SQL query for neuron listing.

    Constructs a SELECT query with optional WHERE clauses based on
    which filters are active. Tag filters use subqueries on neuron_tags.

    Query construction:
    1. Base: SELECT DISTINCT n.id FROM neurons n
    2. WHERE clauses (all combined with AND):
       a. AND tag filter (if and_tag_ids):
          - For each tag_id in and_tag_ids, add:
            AND EXISTS (SELECT 1 FROM neuron_tags WHERE neuron_id = n.id AND tag_id = ?)
          - This ensures the neuron has ALL specified tags
          - EXISTS subqueries are clear and optimize well with indexes
       b. OR tag filter (if any_tag_ids):
          - AND n.id IN (SELECT neuron_id FROM neuron_tags WHERE tag_id IN (?, ?, ...))
          - This ensures the neuron has at least ONE of the specified tags
       c. Status filter (if status != "all"):
          - AND n.status = ?
       d. Project filter (if project):
          - AND n.project = ?
    3. ORDER BY n.created_at DESC
    4. LIMIT ? OFFSET ?

    Args:
        and_tag_ids: List of tag IDs for AND filter, or None.
        any_tag_ids: List of tag IDs for OR filter, or None.
        status: Status string ("active", "archived", or "all").
        project: Project name string, or None.
        limit: Pagination limit.
        offset: Pagination offset.

    Returns:
        Tuple of (sql_string, params_list).
    """
    # --- Build WHERE clauses ---
    # clauses = []
    # params = []

    # --- AND tag filter ---
    # if and_tag_ids:
    #     for tag_id in and_tag_ids:
    #         clauses.append("EXISTS (SELECT 1 FROM neuron_tags WHERE neuron_id = n.id AND tag_id = ?)")
    #         params.append(tag_id)

    # --- OR tag filter ---
    # if any_tag_ids:
    #     placeholders = ",".join("?" * len(any_tag_ids))
    #     clauses.append(f"n.id IN (SELECT neuron_id FROM neuron_tags WHERE tag_id IN ({placeholders}))")
    #     params.extend(any_tag_ids)

    # --- Status filter ---
    # if status != "all":
    #     clauses.append("n.status = ?")
    #     params.append(status)

    # --- Project filter ---
    # if project:
    #     clauses.append("n.project = ?")
    #     params.append(project)

    # --- Assemble query ---
    # where_str = " AND ".join(clauses) if clauses else "1=1"
    # query = f"SELECT DISTINCT n.id FROM neurons n WHERE {where_str} ORDER BY n.created_at DESC LIMIT ? OFFSET ?"
    # params.extend([limit, offset])
    # return (query, params)

    clauses: List[str] = []
    params: List[Any] = []

    if and_tag_ids:
        for tag_id in and_tag_ids:
            clauses.append("EXISTS (SELECT 1 FROM neuron_tags WHERE neuron_id = n.id AND tag_id = ?)")
            params.append(tag_id)

    if any_tag_ids:
        placeholders = ",".join("?" * len(any_tag_ids))
        clauses.append(f"n.id IN (SELECT neuron_id FROM neuron_tags WHERE tag_id IN ({placeholders}))")
        params.extend(any_tag_ids)

    if status != "all":
        clauses.append("n.status = ?")
        params.append(status)

    if project:
        clauses.append("n.project = ?")
        params.append(project)

    where_str = " AND ".join(clauses) if clauses else "1=1"
    query = f"SELECT DISTINCT n.id FROM neurons n WHERE {where_str} ORDER BY n.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return (query, params)


def _resolve_tag_ids(
    conn: sqlite3.Connection, tag_names: List[str],
) -> Optional[List[Optional[int]]]:
    """Resolve tag names to their integer IDs.

    Uses the tag registry's lookup-by-name to resolve each tag.
    Normalization happens in the registry lookup.

    Logic flow:
    1. For each tag_name in tag_names:
       a. Normalize tag name (strip, lowercase)
       b. SELECT id FROM tags WHERE name = ?
       c. If found, append tag_id to result list
       d. If not found, append None (caller decides how to handle)
    2. Return list of (tag_id or None) values

    The caller uses this to:
    - AND filter: if any is None -> no results possible
    - OR filter: filter out Nones, use remaining; if all None -> no results

    Args:
        conn: SQLite connection.
        tag_names: List of raw tag name strings.

    Returns:
        List of integer tag IDs (with None for unresolvable names),
        or None if input list is empty.
    """
    if not tag_names:
        return None

    result: List[Optional[int]] = []
    for tag_name in tag_names:
        normalized = tag_name.strip().lower()
        row = conn.execute(
            "SELECT id FROM tags WHERE name = ?",
            (normalized,)
        ).fetchone()
        result.append(row[0] if row else None)
    return result
