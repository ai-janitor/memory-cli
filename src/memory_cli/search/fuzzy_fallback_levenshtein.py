# =============================================================================
# Module: fuzzy_fallback_levenshtein.py
# Purpose: Last-resort fuzzy search fallback when BM25 + vector return nothing.
#   Scans active neuron content, tags, and attr values for fuzzy matches using
#   difflib.SequenceMatcher (stdlib, no external dependencies).
# Rationale: When a user misspells a name or term (e.g. "adidit" for "Aditi"),
#   BM25 and vector search both miss. This fallback does a full scan with fuzzy
#   matching to catch near-misses. Acceptable performance because it only fires
#   on the zero-results path — never on the happy path.
# Responsibility:
#   - Load all active neurons with their content, tags, and attr values
#   - Compute fuzzy ratio between query and each searchable field
#   - Filter by threshold, sort by score, return top N
#   - Return candidate dicts compatible with the hydration pipeline
# Organization:
#   1. Imports
#   2. fuzzy_search() — main entry point
#   3. _score_neuron() — compute best fuzzy score for one neuron
#   4. _fuzzy_ratio() — wrapper around SequenceMatcher
# =============================================================================

from __future__ import annotations

import sqlite3
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple


def fuzzy_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 10,
    threshold: float = 0.4,
) -> List[Dict[str, Any]]:
    """Last-resort fuzzy search when BM25 + vector return nothing.

    Logic flow:
    1. Normalize query to lowercase for case-insensitive matching.
    2. Load all active neurons (id, content) from DB.
    3. Load all tags per neuron via neuron_tags JOIN tags.
    4. Load all attr values per neuron via neuron_attrs JOIN attr_keys.
    5. For each neuron, compute best fuzzy score across all fields.
    6. Filter candidates above threshold.
    7. Sort by score descending, return top `limit`.
    8. Return candidate dicts with neuron_id, match_type, fuzzy metadata.

    Args:
        conn: SQLite connection with neurons, neuron_tags, tags,
              neuron_attrs, attr_keys tables.
        query: The user's search query string.
        limit: Maximum number of fuzzy results to return.
        threshold: Minimum fuzzy ratio (0.0-1.0) to include a result.

    Returns:
        List of candidate dicts compatible with the hydration pipeline.
        Each dict has: neuron_id, match_type, fuzzy_score, fuzzy_matched_field,
        final_score, hop_distance, edge_reason.
    """
    # --- Normalize query ---
    query_lower = query.lower().strip()
    if not query_lower:
        return []

    # --- Load all active neurons ---
    # Full table scan is acceptable — this is a rare fallback path.
    neuron_rows = conn.execute(
        "SELECT id, content FROM neurons WHERE status = 'active'"
    ).fetchall()

    if not neuron_rows:
        return []

    # --- Load tags per neuron (batch) ---
    tag_rows = conn.execute(
        "SELECT nt.neuron_id, t.name "
        "FROM neuron_tags nt "
        "JOIN tags t ON nt.tag_id = t.id "
        "JOIN neurons n ON nt.neuron_id = n.id "
        "WHERE n.status = 'active'"
    ).fetchall()
    tags_map: Dict[int, List[str]] = {}
    for neuron_id, tag_name in tag_rows:
        tags_map.setdefault(neuron_id, []).append(tag_name)

    # --- Load attr values per neuron (batch) ---
    attr_rows = conn.execute(
        "SELECT na.neuron_id, ak.name, na.value "
        "FROM neuron_attrs na "
        "JOIN attr_keys ak ON na.attr_key_id = ak.id "
        "JOIN neurons n ON na.neuron_id = n.id "
        "WHERE n.status = 'active'"
    ).fetchall()
    attrs_map: Dict[int, List[Tuple[str, str]]] = {}
    for neuron_id, attr_key, attr_value in attr_rows:
        attrs_map.setdefault(neuron_id, []).append((attr_key, attr_value))

    # --- Score each neuron ---
    scored: List[Tuple[float, str, int]] = []  # (score, matched_field, neuron_id)

    for neuron_id, content in neuron_rows:
        best_score, best_field = _score_neuron(
            query_lower,
            neuron_id,
            content,
            tags_map.get(neuron_id, []),
            attrs_map.get(neuron_id, []),
        )
        if best_score >= threshold:
            scored.append((best_score, best_field, neuron_id))

    # --- Sort by score descending, take top `limit` ---
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]

    # --- Build candidate dicts compatible with hydration pipeline ---
    results: List[Dict[str, Any]] = []
    for score, matched_field, neuron_id in top:
        results.append({
            "neuron_id": neuron_id,
            "match_type": "fuzzy",
            "fuzzy_score": round(score, 4),
            "fuzzy_matched_field": matched_field,
            "final_score": round(score, 4),
            "hop_distance": 0,
            "edge_reason": None,
        })

    return results


def _score_neuron(
    query_lower: str,
    neuron_id: int,
    content: str,
    tags: List[str],
    attrs: List[Tuple[str, str]],
) -> Tuple[float, str]:
    """Compute the best fuzzy score for a single neuron across all fields.

    Logic flow:
    1. Check content for substring match first (cheap).
    2. If no substring match, compute fuzzy ratio on content.
       - For long content, also check individual words/phrases.
    3. Check each tag name for fuzzy match.
    4. Check each attr value for fuzzy match.
    5. Return (best_score, best_field_name).

    Args:
        query_lower: Lowercased query string.
        neuron_id: Neuron ID (unused, kept for debugging).
        content: Neuron content text.
        tags: List of tag names for this neuron.
        attrs: List of (attr_key, attr_value) tuples.

    Returns:
        Tuple of (best_score, field_name) where field_name is one of:
        "content", "tag:<name>", "attr:<key>".
    """
    best_score = 0.0
    best_field = "content"
    content_lower = content.lower()

    # --- Check content ---
    # Substring check first (cheap exact containment)
    if query_lower in content_lower:
        best_score = 1.0
        best_field = "content"
        return best_score, best_field

    # Fuzzy ratio on full content (may be low for long content)
    ratio = _fuzzy_ratio(query_lower, content_lower)
    if ratio > best_score:
        best_score = ratio
        best_field = "content"

    # Also check individual words in content for short queries
    # This helps match "adidit" against "Aditi" in "Aditi Srivastava is..."
    content_words = content_lower.split()
    for word in content_words:
        word_ratio = _fuzzy_ratio(query_lower, word)
        if word_ratio > best_score:
            best_score = word_ratio
            best_field = "content"

    # --- Check tags ---
    for tag_name in tags:
        tag_ratio = _fuzzy_ratio(query_lower, tag_name.lower())
        if tag_ratio > best_score:
            best_score = tag_ratio
            best_field = f"tag:{tag_name}"

    # --- Check attrs ---
    for attr_key, attr_value in attrs:
        attr_ratio = _fuzzy_ratio(query_lower, attr_value.lower())
        if attr_ratio > best_score:
            best_score = attr_ratio
            best_field = f"attr:{attr_key}"
        # Also check individual words in attr values
        for word in attr_value.lower().split():
            word_ratio = _fuzzy_ratio(query_lower, word)
            if word_ratio > best_score:
                best_score = word_ratio
                best_field = f"attr:{attr_key}"

    return best_score, best_field


def _fuzzy_ratio(a: str, b: str) -> float:
    """Compute fuzzy similarity ratio between two strings.

    Uses difflib.SequenceMatcher which implements a variant of the
    Ratcliff/Obershelp algorithm. Returns 0.0-1.0 where 1.0 is identical.

    Args:
        a: First string (typically the query).
        b: Second string (typically the field value).

    Returns:
        Similarity ratio between 0.0 and 1.0.
    """
    return SequenceMatcher(None, a, b).ratio()
