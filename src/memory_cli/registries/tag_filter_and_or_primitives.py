# =============================================================================
# Module: tag_filter_and_or_primitives.py
# Purpose: AND/OR tag filtering primitives for the search pipeline — given a
#   set of tag specifiers, produce SQL conditions that filter neurons by tag
#   membership.
# Rationale: Tag filtering is the primary mechanism for narrowing neuron search
#   results. Two modes are needed: AND (neuron must have ALL specified tags) and
#   OR (neuron must have ANY specified tag). These are kept as primitives rather
#   than a complex boolean engine — v1 does not support nested grouping. The
#   primitives return SQL fragments and parameter lists that the search pipeline
#   can compose into its final query.
# Responsibility:
#   - Resolve tag specifiers (names or IDs) to integer tag IDs
#   - Build AND filter: SQL condition requiring ALL tag IDs present
#   - Build OR filter: SQL condition requiring ANY tag ID present
#   - Handle empty filter lists (no filtering = pass-through)
# Organization:
#   1. Imports
#   2. TagFilterError — custom exception for resolution failures
#   3. resolve_tag_specifiers() — resolve list of names/IDs to tag IDs
#   4. build_and_filter() — SQL fragment for AND (must have all)
#   5. build_or_filter() — SQL fragment for OR (must have any)
#   6. apply_tag_filter() — convenience: resolve + build in one call
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import List, Optional, Tuple, Union


class TagFilterError(Exception):
    """Raised when tag filter resolution fails.

    Attributes:
        specifier: The tag name or ID that could not be resolved.
        reason: Why resolution failed (not found, empty name, etc.).
    """

    pass


def resolve_tag_specifiers(
    conn: sqlite3.Connection,
    specifiers: List[str],
) -> List[int]:
    """Resolve a list of tag specifiers (names or IDs) to integer tag IDs.

    Logic flow:
    1. For each specifier in the list:
       a. Try to parse as int -> look up by ID in tags table
          - If found -> add to result list
          - If not found -> raise TagFilterError (ID does not exist)
       b. If not an int -> normalize name, look up by name in tags table
          - If found -> add to result list
          - If not found -> raise TagFilterError (name does not exist)
    2. Return list of resolved integer tag IDs

    Note: This does NOT auto-create tags. Filter specifiers must reference
    existing tags. If a user filters by a tag that doesn't exist, that's an
    error, not an auto-create opportunity.

    Deduplication:
    - If the same tag is specified twice (by name and by ID, or twice by name),
      the result list will contain duplicates. The SQL builder handles this
      gracefully (duplicates in IN clause are harmless; duplicate HAVING COUNT
      is still correct).

    Args:
        conn: SQLite connection.
        specifiers: List of tag names (strings) or tag IDs (string-encoded ints).

    Returns:
        List of integer tag IDs.

    Raises:
        TagFilterError: If any specifier cannot be resolved.
    """
    # Import normalization function here to avoid circular imports at module level
    from .tag_registry_crud_normalize_autocreate import normalize_tag_name

    resolved: List[int] = []
    for spec in specifiers:
        # 1. Try to parse as int ID first
        try:
            tag_id_int = int(spec)
            row = conn.execute(
                "SELECT id FROM tags WHERE id = ?", (tag_id_int,)
            ).fetchone()
            if row is None:
                raise TagFilterError(
                    f"Tag ID {tag_id_int} not found. Filter specifiers must reference existing tags."
                )
            resolved.append(row[0])
        except ValueError:
            # 2. Not an int — normalize and look up by name
            try:
                name = normalize_tag_name(spec)
            except Exception as exc:
                raise TagFilterError(
                    f"Invalid tag specifier {spec!r}: {exc}"
                ) from exc
            row = conn.execute(
                "SELECT id FROM tags WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                raise TagFilterError(
                    f"Tag {name!r} not found. Filter specifiers must reference existing tags."
                )
            resolved.append(row[0])
    return resolved


def build_and_filter(
    tag_ids: List[int],
) -> Tuple[str, List[int]]:
    """Build a SQL fragment for AND tag filtering (neuron must have ALL tags).

    SQL strategy:
    - Use a subquery on the neuron_tags junction table:
      SELECT neuron_id FROM neuron_tags
      WHERE tag_id IN (?, ?, ...)
      GROUP BY neuron_id
      HAVING COUNT(DISTINCT tag_id) = ?
    - The HAVING clause ensures the neuron has ALL specified tags,
      not just some of them.

    Logic flow:
    1. If tag_ids is empty -> return ("", []) — no filter, pass-through
    2. Build the subquery with len(tag_ids) placeholders
    3. The final parameter list is: [...tag_ids, len(tag_ids)]
    4. Return (sql_fragment, params)

    The returned SQL fragment is meant to be used as:
      WHERE neurons.id IN (<fragment>)

    Args:
        tag_ids: List of integer tag IDs (already resolved).

    Returns:
        Tuple of (sql_fragment: str, params: list[int]).
        Empty string and empty list if no filtering needed.
    """
    # 1. Empty list — no filter, pass-through
    if not tag_ids:
        return ("", [])
    # 2. Build subquery with one placeholder per tag ID
    placeholders = ", ".join(["?"] * len(tag_ids))
    sql = (
        f"SELECT neuron_id FROM neuron_tags "
        f"WHERE tag_id IN ({placeholders}) "
        f"GROUP BY neuron_id "
        f"HAVING COUNT(DISTINCT tag_id) = ?"
    )
    # 3. Params: all tag IDs + the count for HAVING
    params = list(tag_ids) + [len(tag_ids)]
    return (sql, params)


def build_or_filter(
    tag_ids: List[int],
) -> Tuple[str, List[int]]:
    """Build a SQL fragment for OR tag filtering (neuron must have ANY tag).

    SQL strategy:
    - Use a subquery on the neuron_tags junction table:
      SELECT DISTINCT neuron_id FROM neuron_tags
      WHERE tag_id IN (?, ?, ...)
    - Any neuron that has at least one of the specified tags is included.

    Logic flow:
    1. If tag_ids is empty -> return ("", []) — no filter, pass-through
    2. Build the subquery with len(tag_ids) placeholders
    3. Return (sql_fragment, tag_ids)

    The returned SQL fragment is meant to be used as:
      WHERE neurons.id IN (<fragment>)

    Args:
        tag_ids: List of integer tag IDs (already resolved).

    Returns:
        Tuple of (sql_fragment: str, params: list[int]).
        Empty string and empty list if no filtering needed.
    """
    # 1. Empty list — no filter, pass-through
    if not tag_ids:
        return ("", [])
    # 2. Build subquery — DISTINCT neuron_id, any matching tag qualifies
    placeholders = ", ".join(["?"] * len(tag_ids))
    sql = (
        f"SELECT DISTINCT neuron_id FROM neuron_tags "
        f"WHERE tag_id IN ({placeholders})"
    )
    return (sql, list(tag_ids))


def apply_tag_filter(
    conn: sqlite3.Connection,
    specifiers: List[str],
    mode: str = "and",
) -> Tuple[str, List[int]]:
    """Convenience function: resolve specifiers and build filter in one call.

    Logic flow:
    1. If specifiers is empty or None -> return ("", []) — pass-through
    2. Call resolve_tag_specifiers(conn, specifiers) to get tag IDs
    3. Based on mode:
       - "and" -> call build_and_filter(tag_ids)
       - "or"  -> call build_or_filter(tag_ids)
       - other -> raise ValueError (invalid mode)
    4. Return the (sql_fragment, params) tuple

    This is the primary entry point for the search pipeline. It handles
    the full flow from user-provided tag names to SQL fragments.

    Args:
        conn: SQLite connection.
        specifiers: List of tag names/IDs from --tags or --tags-any CLI flag.
        mode: "and" for --tags (must have all), "or" for --tags-any (must have any).

    Returns:
        Tuple of (sql_fragment: str, params: list[int]).

    Raises:
        TagFilterError: If any specifier cannot be resolved.
        ValueError: If mode is not "and" or "or".
    """
    # 1. Empty / None specifiers — pass-through, no filter
    if not specifiers:
        return ("", [])
    # 2. Resolve specifiers to tag IDs (raises TagFilterError if any not found)
    tag_ids = resolve_tag_specifiers(conn, specifiers)
    # 3. Build filter based on mode
    if mode == "and":
        return build_and_filter(tag_ids)
    elif mode == "or":
        return build_or_filter(tag_ids)
    else:
        raise ValueError(f"Invalid filter mode {mode!r}. Must be 'and' or 'or'.")
