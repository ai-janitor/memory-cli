# =============================================================================
# stale_and_blank_vector_detection.py — Query for blank/stale neuron IDs
# =============================================================================
# Purpose:     Identify neurons that need (re-)embedding: "blank" neurons have
#              no vector at all in the vec0 table, "stale" neurons have been
#              updated since their last embedding. Provides query interfaces
#              for both, with optional filtering.
# Rationale:   After neuron content or tags change, the existing embedding no
#              longer reflects the current text. Stale detection compares
#              neurons.updated_at vs neurons.embedding_updated_at. Blank
#              detection checks for neuron IDs with no corresponding vec0 row.
#              Both are needed by the batch re-embed orchestrator.
# Responsibility:
#   - get_blank_neuron_ids: neurons with no vec0 row
#   - get_stale_neuron_ids: neurons where updated_at > embedding_updated_at
#   - get_all_reembed_candidates: union of blank + stale (deduplicated)
#   - Optional project_id filter on all queries
#   - Return lists of neuron IDs, not full neuron records
# Organization:
#   get_blank_neuron_ids(conn, project_id?) -> list[str]
#   get_stale_neuron_ids(conn, project_id?) -> list[str]
#   get_all_reembed_candidates(conn, project_id?) -> list[str]
# =============================================================================

from __future__ import annotations

import sqlite3


def get_blank_neuron_ids(
    conn: sqlite3.Connection,
    project_id: str | None = None,
) -> list[int]:
    """Return neuron IDs that have no corresponding vector in neurons_vec.

    A "blank" neuron was stored without an embedding — either because the
    model was missing at write time, or the neuron predates embedding support.

    Args:
        conn: An open sqlite3.Connection.
        project_id: Optional project to filter by. If None, returns all
                    blank neurons across all projects.

    Returns:
        List of neuron IDs (integers) with no vec0 row.
    """
    # --- Step 1: Build the query ---
    # SELECT n.id FROM neurons n
    # LEFT JOIN neurons_vec v ON n.id = v.rowid
    # WHERE v.rowid IS NULL
    #   AND n.archived_at IS NULL  -- skip archived neurons
    # If project_id is not None:
    #   AND n.project_id = ?
    sql = """
        SELECT n.id FROM neurons n
        LEFT JOIN neurons_vec v ON n.id = v.neuron_id
        WHERE v.neuron_id IS NULL
          AND n.status = 'active'
    """
    params: list = []
    if project_id is not None:
        sql += " AND n.project = ?"
        params.append(project_id)

    # --- Step 2: Execute and collect results ---
    # cursor = conn.execute(sql, params)
    # return [row[0] for row in cursor.fetchall()]
    cursor = conn.execute(sql, params)
    return [row[0] for row in cursor.fetchall()]


def get_stale_neuron_ids(
    conn: sqlite3.Connection,
    project_id: str | None = None,
) -> list[int]:
    """Return neuron IDs where content has changed since last embedding.

    A "stale" neuron has updated_at > embedding_updated_at, meaning its
    content or tags were modified after the current embedding was generated.

    Args:
        conn: An open sqlite3.Connection.
        project_id: Optional project to filter by. If None, returns all
                    stale neurons across all projects.

    Returns:
        List of neuron IDs (integers) with outdated embeddings.
    """
    # --- Step 1: Build the query ---
    # SELECT n.id FROM neurons n
    # WHERE n.updated_at > n.embedding_updated_at
    #   AND n.embedding_updated_at IS NOT NULL  -- blanks handled separately
    #   AND n.archived_at IS NULL  -- skip archived neurons
    # If project_id is not None:
    #   AND n.project_id = ?
    sql = """
        SELECT n.id FROM neurons n
        WHERE n.updated_at > n.embedding_updated_at
          AND n.embedding_updated_at IS NOT NULL
          AND n.status = 'active'
    """
    params: list = []
    if project_id is not None:
        sql += " AND n.project = ?"
        params.append(project_id)

    # --- Step 2: Execute and collect results ---
    # cursor = conn.execute(sql, params)
    # return [row[0] for row in cursor.fetchall()]
    cursor = conn.execute(sql, params)
    return [row[0] for row in cursor.fetchall()]


def get_all_reembed_candidates(
    conn: sqlite3.Connection,
    project_id: str | None = None,
) -> list[int]:
    """Return all neuron IDs that need embedding: blank + stale, deduplicated.

    Convenience function that combines blank and stale detection into a
    single deduplicated list. Order is blanks first, then stale.

    Args:
        conn: An open sqlite3.Connection.
        project_id: Optional project to filter by.

    Returns:
        Deduplicated list of neuron IDs (integers) needing (re-)embedding.
    """
    # --- Step 1: Get blank and stale lists ---
    # blank_ids = get_blank_neuron_ids(conn, project_id)
    # stale_ids = get_stale_neuron_ids(conn, project_id)
    blank_ids = get_blank_neuron_ids(conn, project_id)
    stale_ids = get_stale_neuron_ids(conn, project_id)

    # --- Step 2: Deduplicate while preserving order (blanks first) ---
    # seen = set(blank_ids)
    # result = list(blank_ids)
    # for nid in stale_ids:
    #   if nid not in seen:
    #     result.append(nid)
    #     seen.add(nid)
    seen = set(blank_ids)
    result = list(blank_ids)
    for nid in stale_ids:
        if nid not in seen:
            result.append(nid)
            seen.add(nid)

    # --- Step 3: Return combined list ---
    # return result
    return result
