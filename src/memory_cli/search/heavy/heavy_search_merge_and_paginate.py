# =============================================================================
# Module: heavy_search_merge_and_paginate.py
# Purpose: Merge re-ranked candidates with query expansion results, deduplicate
#   by neuron ID, and apply the user's original limit/offset pagination.
# Rationale: The merge step is the final assembly point where re-ranking
#   quality and expansion breadth combine into the final result set. Keeping
#   it separate from the orchestrator makes the merge logic testable with
#   synthetic data and the priority/dedup rules explicit.
# Responsibility:
#   - Accept reranked candidate list (primary, ordered by Haiku relevance)
#   - Accept expansion result list (secondary, may overlap with reranked)
#   - Deduplicate: expansion results that are already in reranked set are dropped
#   - Preserve order: reranked first, then unique expansion results
#   - Apply user's limit and offset to the merged list
#   - Build and return result envelope matching light search output schema
# Organization:
#   1. Imports
#   2. merge_and_paginate() — main entry point
#   3. _deduplicate_by_neuron_id() — remove duplicates preserving order
#   4. _apply_pagination() — slice by offset and limit
#   5. _build_result_envelope() — construct output dict
# =============================================================================

from __future__ import annotations

from typing import Any, Dict, List, Set


def merge_and_paginate(
    query: str,
    reranked: List[Dict[str, Any]],
    expansion_results: List[Dict[str, Any]],
    limit: int,
    offset: int,
) -> Dict[str, Any]:
    """Merge reranked + expansion results, deduplicate, and paginate.

    Merge strategy:
    1. Start with reranked list (already in Haiku-determined order)
    2. Collect all neuron IDs from reranked into a seen set
    3. Walk expansion_results in order:
       a. If neuron ID already in seen set: skip (duplicate)
       b. Otherwise: append to merged list, add ID to seen set
    4. merged_list = reranked + unique_expansion
    5. total = len(merged_list)
    6. Apply pagination: merged_list[offset : offset + limit]
    7. Build result envelope

    Edge cases:
    - reranked is empty (light search found nothing): expansion only
    - expansion_results is empty (expansion failed/skipped): reranked only
    - Both empty: return empty envelope
    - offset beyond total: return empty results with correct total
    - limit = 0: return empty results (shouldn't happen, but defensive)
    - Duplicate neuron across multiple expansion queries: first occurrence wins

    Args:
        query: Original query string (for envelope).
        reranked: Reranked neuron result dicts (primary set).
        expansion_results: Expansion neuron result dicts (secondary set).
        limit: User's requested result count.
        offset: User's requested offset.

    Returns:
        Result envelope dict:
        {
            "query": str,
            "results": List[Dict],
            "total": int,
            "limit": int,
            "offset": int,
        }
    """
    # --- Step 1: Merge with deduplication ---
    # merged = _deduplicate_by_neuron_id(reranked, expansion_results)
    merged = _deduplicate_by_neuron_id(reranked, expansion_results)

    # --- Step 2: Apply pagination ---
    # page = _apply_pagination(merged, limit, offset)
    page = _apply_pagination(merged, limit, offset)

    # --- Step 3: Build envelope ---
    # return _build_result_envelope(query, page, len(merged), limit, offset)
    return _build_result_envelope(query, page, len(merged), limit, offset)


def _deduplicate_by_neuron_id(
    primary: List[Dict[str, Any]],
    secondary: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge primary and secondary lists, deduplicating by neuron ID.

    Priority: primary list items always win. Secondary items are only
    included if their neuron ID is not already in the primary set.

    Logic:
    1. Initialize result list with all items from primary
    2. Build seen_ids set from primary neuron IDs
    3. For each item in secondary:
       a. If item["id"] in seen_ids: skip
       b. Else: append to result, add ID to seen_ids
    4. Return result

    Args:
        primary: Primary result list (reranked candidates).
        secondary: Secondary result list (expansion results).

    Returns:
        Merged list with no duplicate neuron IDs.
    """
    result = list(primary)
    seen_ids: Set[Any] = {item["id"] for item in primary}
    for item in secondary:
        if item["id"] not in seen_ids:
            result.append(item)
            seen_ids.add(item["id"])
    return result


def _apply_pagination(
    merged: List[Dict[str, Any]],
    limit: int,
    offset: int,
) -> List[Dict[str, Any]]:
    """Apply offset and limit to get a page of results.

    Simple slice: merged[offset : offset + limit]

    Edge cases:
    - offset >= len(merged): return []
    - offset + limit > len(merged): return merged[offset:]
    - offset < 0: treat as 0
    - limit <= 0: return []

    Args:
        merged: Full merged result list.
        limit: Page size.
        offset: Starting position.

    Returns:
        Sliced result list.
    """
    if limit <= 0:
        return []
    start = max(0, offset)
    return merged[start: start + limit]


def _build_result_envelope(
    query: str,
    results: List[Dict[str, Any]],
    total: int,
    limit: int,
    offset: int,
) -> Dict[str, Any]:
    """Construct the result envelope dict matching light search schema.

    The envelope is identical to light search output — the caller (CLI layer)
    cannot distinguish heavy from light search results. This is intentional:
    --heavy is a quality knob, not a schema change.

    Args:
        query: Original query string.
        results: Paginated result list.
        total: Total results before pagination.
        limit: Requested limit.
        offset: Requested offset.

    Returns:
        {
            "query": query,
            "results": results,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    """
    return {
        "query": query,
        "results": results,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
