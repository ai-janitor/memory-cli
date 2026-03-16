# =============================================================================
# Module: search_result_hydration_and_envelope.py
# Purpose: Result hydration and output envelope — stage 10 of the light
#   search pipeline. Hydrates neuron records (content, tags, attrs) and builds
#   the structured output envelope with pagination metadata.
# Rationale: Search pipeline stages operate on lightweight candidate dicts
#   (neuron_id + scores). The final output needs full neuron records with
#   content, tags, and attributes. Hydration is deferred to the end so only
#   the paginated slice (not all candidates) incurs the hydration cost.
#   The envelope provides a stable contract for CLI output formatting.
# Responsibility:
#   - Hydrate neuron records for paginated candidates (content, tags, attrs)
#   - Attach search metadata to each result (match_type, hop_distance,
#     edge_reason, score, score_breakdown)
#   - Build output envelope with results + pagination (total, limit, offset)
#   - Handle missing neurons gracefully (skip if neuron deleted between
#     search and hydration)
# Organization:
#   1. Imports
#   2. hydrate_results() — main entry point
#   3. _hydrate_single_neuron() — fetch and merge one neuron's fields
#   4. _build_result_record() — combine neuron fields + search metadata
#   5. build_envelope() — construct final SearchResultEnvelope
# =============================================================================

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List


def hydrate_results(
    conn: sqlite3.Connection,
    paginated_candidates: List[Dict[str, Any]],
    explain: bool = False,
) -> List[Dict[str, Any]]:
    """Hydrate paginated candidates into full result records.

    Logic flow:
    1. Extract neuron_ids from paginated_candidates.
    2. Batch-fetch neuron records from DB:
       SELECT id, content, created_at, updated_at, project, source, status
       FROM neurons WHERE id IN (?, ?, ...)
    3. Batch-fetch tags for all neuron_ids (reuse tag fetch pattern).
    4. For each candidate in paginated order:
       a. Look up neuron record from batch results.
       b. If neuron not found → skip (deleted between search and hydration).
       c. Build result record via _build_result_record().
       d. If explain → score_breakdown already attached by explain stage.
    5. Return list of hydrated result dicts.

    Why batch: Fetching neurons one-at-a-time would be N+1. The paginated
    slice is small (typically 20), so a single IN query is efficient.

    Args:
        conn: SQLite connection with neurons, neuron_tags, tags tables.
        paginated_candidates: Paginated slice of scored candidates.
        explain: Whether --explain was requested (breakdown already attached).

    Returns:
        List of fully hydrated result dicts in ranking order.
    """
    # --- Extract neuron IDs ---
    # neuron_ids = [c["neuron_id"] for c in paginated_candidates]
    # if not neuron_ids:
    #     return []
    neuron_ids = [c["neuron_id"] for c in paginated_candidates]
    if not neuron_ids:
        return []

    # --- Batch-fetch neurons ---
    # placeholders = ",".join("?" * len(neuron_ids))
    # rows = conn.execute(
    #     f"SELECT id, content, created_at, updated_at, project, source, status "
    #     f"FROM neurons WHERE id IN ({placeholders})",
    #     neuron_ids,
    # ).fetchall()
    # neuron_map = {row[0]: row for row in rows}
    placeholders = ",".join("?" * len(neuron_ids))
    rows = conn.execute(
        f"SELECT id, content, created_at, updated_at, project, source, status "
        f"FROM neurons WHERE id IN ({placeholders})",
        neuron_ids,
    ).fetchall()
    neuron_map = {row[0]: row for row in rows}

    # --- Batch-fetch tags ---
    # tag_rows = conn.execute(
    #     f"SELECT nt.neuron_id, t.name FROM neuron_tags nt "
    #     f"JOIN tags t ON nt.tag_id = t.id "
    #     f"WHERE nt.neuron_id IN ({placeholders})",
    #     neuron_ids,
    # ).fetchall()
    # tags_map: Dict[int, List[str]] = {}
    # for neuron_id, tag_name in tag_rows:
    #     tags_map.setdefault(neuron_id, []).append(tag_name)
    tag_rows = conn.execute(
        f"SELECT nt.neuron_id, t.name FROM neuron_tags nt "
        f"JOIN tags t ON nt.tag_id = t.id "
        f"WHERE nt.neuron_id IN ({placeholders})",
        neuron_ids,
    ).fetchall()
    tags_map: Dict[int, List[str]] = {}
    for neuron_id, tag_name in tag_rows:
        tags_map.setdefault(neuron_id, []).append(tag_name)

    # --- Batch-fetch edge topology summaries ---
    from memory_cli.edge.edge_list_by_neuron_direction import edge_type_summary

    edge_summaries = edge_type_summary(conn, neuron_ids)

    # --- Bump access tracking for all hydrated neurons ---
    now_ms = int(time.time() * 1000)
    hit_ids = [nid for nid in neuron_ids if nid in neuron_map]
    if hit_ids:
        hit_placeholders = ",".join("?" * len(hit_ids))
        conn.execute(
            f"UPDATE neurons SET access_count = access_count + 1, "
            f"last_accessed_at = ? WHERE id IN ({hit_placeholders})",
            [now_ms] + hit_ids,
        )

    # --- Build results in ranking order ---
    results = []
    for candidate in paginated_candidates:
        nid = candidate["neuron_id"]
        neuron_row = neuron_map.get(nid)
        if neuron_row is None:
            continue  # Neuron deleted between search and hydration
        neuron_tags = sorted(tags_map.get(nid, []))
        edge_summary = edge_summaries.get(nid, {"top_types": [], "total": 0})
        result = _build_result_record(candidate, neuron_row, neuron_tags, edge_summary)
        results.append(result)

    return results


def _hydrate_single_neuron(
    conn: sqlite3.Connection,
    neuron_id: int,
) -> Dict[str, Any]:
    """Fetch a single neuron's full record with tags.

    Fallback for single-neuron hydration when batch is not applicable.

    Logic flow:
    1. SELECT id, content, created_at, updated_at, project, source, status
       FROM neurons WHERE id = ?
    2. If not found → return empty dict.
    3. Fetch tags via JOIN on neuron_tags + tags.
    4. Return neuron dict with tags list.

    Args:
        conn: SQLite connection.
        neuron_id: ID of the neuron to hydrate.

    Returns:
        Neuron dict with tags, or empty dict if not found.
    """
    row = conn.execute(
        "SELECT id, content, created_at, updated_at, project, source, status "
        "FROM neurons WHERE id = ?",
        (neuron_id,),
    ).fetchone()
    if row is None:
        return {}
    tag_rows = conn.execute(
        "SELECT t.name FROM neuron_tags nt JOIN tags t ON nt.tag_id = t.id "
        "WHERE nt.neuron_id = ?",
        (neuron_id,),
    ).fetchall()
    return {
        "id": row[0],
        "content": row[1],
        "created_at": row[2],
        "updated_at": row[3],
        "project": row[4],
        "source": row[5],
        "status": row[6],
        "tags": sorted([r[0] for r in tag_rows]),
    }


def _build_result_record(
    candidate: Dict[str, Any],
    neuron_row: tuple,
    neuron_tags: List[str],
    edge_summary: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Combine neuron fields with search metadata into a result record.

    Output record fields:
    - id: neuron ID
    - content: neuron content text
    - created_at: creation timestamp (ms)
    - updated_at: last update timestamp (ms)
    - project: project name
    - source: source identifier
    - status: neuron status
    - tags: list of tag name strings
    - match_type: "direct_match" or "fan_out"
    - hop_distance: hops from nearest seed (0 for direct match)
    - edge_reason: reason string from connecting edge (None for direct)
    - score: final_score for display
    - score_breakdown: full breakdown dict (only if --explain, else omitted)

    Logic flow:
    1. Unpack neuron_row tuple into named fields.
    2. Merge with candidate's search metadata.
    3. Conditionally include score_breakdown if present.
    4. Return result dict.

    Args:
        candidate: Scored candidate dict.
        neuron_row: Raw DB row tuple (id, content, created_at, ...).
        neuron_tags: Sorted list of tag names.

    Returns:
        Merged result dict for output envelope.
    """
    # result = {
    #     "id": neuron_row[0],
    #     "content": neuron_row[1],
    #     "created_at": neuron_row[2],
    #     "updated_at": neuron_row[3],
    #     "project": neuron_row[4],
    #     "source": neuron_row[5],
    #     "status": neuron_row[6],
    #     "tags": neuron_tags,
    #     "match_type": candidate.get("match_type", "direct_match"),
    #     "hop_distance": candidate.get("hop_distance", 0),
    #     "edge_reason": candidate.get("edge_reason"),
    #     "score": candidate.get("final_score", 0.0),
    # }

    # # Only include breakdown if --explain was used (it's pre-attached)
    # if "score_breakdown" in candidate:
    #     result["score_breakdown"] = candidate["score_breakdown"]

    # return result
    result = {
        "id": neuron_row[0],
        "content": neuron_row[1],
        "created_at": neuron_row[2],
        "updated_at": neuron_row[3],
        "project": neuron_row[4],
        "source": neuron_row[5],
        "status": neuron_row[6],
        "tags": neuron_tags,
        "match_type": candidate.get("match_type", "direct_match"),
        "hop_distance": candidate.get("hop_distance") or 0,
        "edge_reason": candidate.get("edge_reason"),
        "score": candidate.get("final_score", 0.0),
        "tag_affinity_depth": candidate.get("tag_affinity_depth"),
    }

    # Only include breakdown if --explain was used (it's pre-attached)
    if "score_breakdown" in candidate:
        result["score_breakdown"] = candidate["score_breakdown"]

    # Attach edge topology summary
    if edge_summary is not None:
        result["edges"] = edge_summary

    return result


def build_envelope(
    results: List[Dict[str, Any]],
    total_before_pagination: int,
    limit: int,
    offset: int,
    vector_unavailable: bool = False,
) -> Dict[str, Any]:
    """Construct the final search result envelope.

    Envelope structure:
    {
        "results": [...hydrated result records...],
        "pagination": {
            "total": <total candidates before pagination>,
            "limit": <page size>,
            "offset": <page offset>,
            "has_more": <bool, total > offset + limit>,
        },
        "metadata": {
            "vector_unavailable": <bool>,
            "result_count": <number of results in this page>,
        },
    }

    Logic flow:
    1. Build pagination sub-object.
    2. Build metadata sub-object.
    3. Assemble and return envelope dict.

    Args:
        results: Hydrated result records.
        total_before_pagination: Total candidates before limit/offset.
        limit: Page size.
        offset: Page offset.
        vector_unavailable: Whether vector retrieval was unavailable.

    Returns:
        Envelope dict ready for JSON serialization.
    """
    # return {
    #     "results": results,
    #     "pagination": {
    #         "total": total_before_pagination,
    #         "limit": limit,
    #         "offset": offset,
    #         "has_more": total_before_pagination > offset + limit,
    #     },
    #     "metadata": {
    #         "vector_unavailable": vector_unavailable,
    #         "result_count": len(results),
    #     },
    # }
    return {
        "results": results,
        "pagination": {
            "total": total_before_pagination,
            "limit": limit,
            "offset": offset,
            "has_more": total_before_pagination > offset + limit,
        },
        "metadata": {
            "vector_unavailable": vector_unavailable,
            "result_count": len(results),
        },
    }
