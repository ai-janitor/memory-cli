# =============================================================================
# Module: tag_filter_post_activation.py
# Purpose: Post-activation AND/OR tag filtering — stage 7 of the light search
#   pipeline. Filters candidates by tag requirements AFTER spreading activation,
#   so activation energy flows through all neurons regardless of tags.
# Rationale: Tag filtering is applied POST-activation (not pre-activation)
#   because the graph structure should determine what gets activated — tags
#   only determine what the USER sees in results. A neuron that fails the tag
#   filter can still propagate activation to its neighbors. This prevents
#   tag filters from creating dead-end islands in the activation graph.
# Responsibility:
#   - Filter candidates by tag requirements (AND mode or OR mode)
#   - AND: candidate must have ALL specified tags
#   - OR: candidate must have at least ONE specified tag
#   - Look up neuron tags via registry/DB (not cached in candidate dict)
#   - Return filtered list preserving order and all candidate metadata
#   - Empty tag list → return all candidates unfiltered
# Organization:
#   1. Imports
#   2. filter_by_tags() — main entry point
#   3. _fetch_neuron_tags_batch() — batch lookup of tags for candidate neurons
#   4. _matches_and_filter() — check if neuron tags satisfy AND requirement
#   5. _matches_or_filter() — check if neuron tags satisfy OR requirement
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Set


def filter_by_tags(
    conn: sqlite3.Connection,
    candidates: List[Dict[str, Any]],
    required_tags: List[str],
    tag_mode: str = "AND",
) -> List[Dict[str, Any]]:
    """Filter candidates by tag requirements using AND or OR mode.

    Logic flow:
    1. If required_tags is empty → return candidates unmodified.
    2. Normalize tag_mode to uppercase. Validate is "AND" or "OR".
       - Invalid mode → default to "AND" with warning.
    3. Batch-fetch tags for all candidate neuron IDs.
       - tags_map = _fetch_neuron_tags_batch(conn, [c["neuron_id"] for c in candidates])
    4. Normalize required_tags to lowercase set for case-insensitive matching.
    5. Filter candidates:
       - AND mode: keep if _matches_and_filter(neuron_tags, required_tags_set)
       - OR mode: keep if _matches_or_filter(neuron_tags, required_tags_set)
    6. Return filtered list preserving original order.

    Important: This runs AFTER spreading activation. Fan-out neurons that
    fail the tag filter are excluded from results but their activation
    contributions to OTHER neurons are already baked in.

    Args:
        conn: SQLite connection with neuron_tags and tags tables.
        candidates: List of candidate dicts (must have neuron_id).
        required_tags: List of tag names to filter by.
        tag_mode: "AND" (all tags required) or "OR" (any tag sufficient).

    Returns:
        Filtered candidate list (subset of input, same order).
    """
    # --- Guard: no tags → no filtering ---
    # if not required_tags:
    #     return candidates

    # --- Normalize ---
    # tag_mode = tag_mode.upper()
    # if tag_mode not in ("AND", "OR"):
    #     tag_mode = "AND"
    # required_set = {t.lower() for t in required_tags}

    # --- Batch fetch tags ---
    # neuron_ids = [c["neuron_id"] for c in candidates]
    # tags_map = _fetch_neuron_tags_batch(conn, neuron_ids)

    # --- Filter ---
    # filtered = []
    # for candidate in candidates:
    #     nid = candidate["neuron_id"]
    #     neuron_tags = tags_map.get(nid, set())
    #     if tag_mode == "AND":
    #         if _matches_and_filter(neuron_tags, required_set):
    #             filtered.append(candidate)
    #     else:  # OR
    #         if _matches_or_filter(neuron_tags, required_set):
    #             filtered.append(candidate)

    # return filtered

    pass


def _fetch_neuron_tags_batch(
    conn: sqlite3.Connection,
    neuron_ids: List[int],
) -> Dict[int, Set[str]]:
    """Batch-fetch tags for multiple neurons.

    Logic flow:
    1. If neuron_ids is empty → return empty dict.
    2. Query:
       SELECT nt.neuron_id, t.name
       FROM neuron_tags nt
       JOIN tags t ON nt.tag_id = t.id
       WHERE nt.neuron_id IN (?, ?, ...)
    3. Build dict: {neuron_id: {tag_name_lower, ...}}
    4. Normalize tag names to lowercase for case-insensitive comparison.

    Args:
        conn: SQLite connection.
        neuron_ids: List of neuron IDs to fetch tags for.

    Returns:
        Dict mapping neuron_id to set of lowercase tag name strings.
    """
    # if not neuron_ids:
    #     return {}

    # placeholders = ",".join("?" * len(neuron_ids))
    # rows = conn.execute(
    #     f"SELECT nt.neuron_id, t.name FROM neuron_tags nt "
    #     f"JOIN tags t ON nt.tag_id = t.id "
    #     f"WHERE nt.neuron_id IN ({placeholders})",
    #     neuron_ids,
    # ).fetchall()

    # tags_map: Dict[int, Set[str]] = {}
    # for neuron_id, tag_name in rows:
    #     tags_map.setdefault(neuron_id, set()).add(tag_name.lower())

    # return tags_map

    pass


def _matches_and_filter(neuron_tags: Set[str], required_tags: Set[str]) -> bool:
    """Check if neuron tags satisfy AND requirement.

    AND means the neuron must have ALL required tags.

    Args:
        neuron_tags: Set of lowercase tag names the neuron has.
        required_tags: Set of lowercase tag names all required.

    Returns:
        True if required_tags is a subset of neuron_tags.
    """
    # return required_tags.issubset(neuron_tags)

    pass


def _matches_or_filter(neuron_tags: Set[str], required_tags: Set[str]) -> bool:
    """Check if neuron tags satisfy OR requirement.

    OR means the neuron must have at least ONE of the required tags.

    Args:
        neuron_tags: Set of lowercase tag names the neuron has.
        required_tags: Set of lowercase tag names, at least one required.

    Returns:
        True if neuron_tags intersects with required_tags.
    """
    # return bool(neuron_tags & required_tags)

    pass
