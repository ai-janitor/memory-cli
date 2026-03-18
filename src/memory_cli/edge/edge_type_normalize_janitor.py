# =============================================================================
# Module: edge_type_normalize_janitor.py
# Purpose: Janitor pass to normalize free-text edge reason fields by mapping
#   them to canonical types from the edge_types dimension table.
# Rationale: Edge reasons accumulate synonyms organically — "interviewer",
#   "has_interviewer", "interviewed_by" all describe the same relationship.
#   The janitor clusters these under a single canonical_reason without touching
#   the original reason (provenance preserved). Once normalized, edges can be
#   queried by canonical_reason for consistent type-based filtering.
# Responsibility:
#   - Load canonical types from edge_types table
#   - For each edge with NULL canonical_reason, try to match reason to a canonical type
#   - Match strategy (in priority order):
#     1. Exact match (case-insensitive)
#     2. Predefined synonym lookup (hardcoded synonym → canonical mapping)
#     3. Slug normalization match (underscores/hyphens stripped, lowercase)
#     4. Substring containment (reason contains canonical name as whole word)
#   - Update canonical_reason on matched edges (original reason untouched)
#   - Return summary: total_processed, matched, unmatched
#   - Idempotent: re-running does not corrupt already-normalized edges
# Organization:
#   1. Imports
#   2. Constants / synonym map
#   3. normalize_edge_types() — main entry point
#   4. _load_canonical_types() — read edge_types from DB
#   5. _build_synonym_map() — merge synonym table with predefined synonyms
#   6. _match_reason() — resolve reason → canonical name
#   7. _normalize_slug() — lowercase + strip separators for comparison
# =============================================================================

from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------------------------------------------------------
# Predefined synonyms: free-text reason patterns → canonical edge type name.
# Keys are lowercased slugs (underscores normalized). Values are canonical names.
# This is the primary clustering table — expand as new patterns emerge.
# -----------------------------------------------------------------------------
_PREDEFINED_SYNONYMS: Dict[str, str] = {
    # interviewer cluster
    "has_interviewer":        "interviewer",
    "interviewed_by":         "interviewer",
    "interview_by":           "interviewer",
    "interviewedby":          "interviewer",
    "hasinterviewer":         "interviewer",
    "interviewer":            "interviewer",
    # interviewee cluster
    "has_interviewee":        "interviewee",
    "interview_subject":      "interviewee",
    "interviewee":            "interviewee",
    # related_to cluster
    "related":                "related_to",
    "related to":             "related_to",
    "relates_to":             "related_to",
    "relatedto":              "related_to",
    "related_to":             "related_to",
    "associated_with":        "related_to",
    "associatedwith":         "related_to",
    # derived_from cluster
    "derived_from":           "derived_from",
    "derivedfrom":            "derived_from",
    "based_on":               "derived_from",
    "extends":                "derived_from",
    "inherits_from":          "derived_from",
    "child_of":               "derived_from",
    # contradicts cluster
    "contradicts":            "contradicts",
    "contradicted_by":        "contradicts",
    "conflicts_with":         "contradicts",
    "opposes":                "contradicts",
    # supports cluster
    "supports":               "supports",
    "supported_by":           "supports",
    "evidence_for":           "supports",
    "confirms":               "supports",
    # references cluster
    "references":             "references",
    "ref":                    "references",
    "cites":                  "references",
    "cited_by":               "references",
    "links_to":               "references",
    "see_also":               "references",
    # part_of cluster
    "part_of":                "part_of",
    "partof":                 "part_of",
    "member_of":              "part_of",
    "belongs_to":             "part_of",
    "contained_in":           "part_of",
    "component_of":           "part_of",
    # parent_of cluster
    "parent_of":              "parent_of",
    "parentof":               "parent_of",
    "has_child":              "parent_of",
    "has_subtopic":           "parent_of",
    # authored_by cluster
    "authored_by":            "authored_by",
    "authoredby":             "authored_by",
    "written_by":             "authored_by",
    "created_by":             "authored_by",
    "author":                 "authored_by",
    # similar_to cluster
    "similar_to":             "similar_to",
    "similarto":              "similar_to",
    "synonym_of":             "similar_to",
    "same_as":                "similar_to",
    # causes cluster
    "causes":                 "causes",
    "caused_by":              "causes",
    "leads_to":               "causes",
    "results_in":             "causes",
    # precedes cluster
    "precedes":               "precedes",
    "followed_by":            "precedes",
    "before":                 "precedes",
    # mentions cluster
    "mentions":               "mentions",
    "mentioned_in":           "mentions",
    "refers_to":              "mentions",
    # colleague cluster
    "colleague":              "colleague",
    "coworker":               "colleague",
    "co_worker":              "colleague",
    "works_with":             "colleague",
}


class NormalizeResult:
    """Result of a janitor normalize pass.

    Attributes:
        total_processed: Number of edges examined.
        matched: Number of edges where canonical_reason was set.
        unmatched: Number of edges where no canonical match was found.
        skipped: Edges already having canonical_reason (not re-processed).
    """

    def __init__(
        self,
        total_processed: int = 0,
        matched: int = 0,
        unmatched: int = 0,
        skipped: int = 0,
    ) -> None:
        self.total_processed = total_processed
        self.matched = matched
        self.unmatched = unmatched
        self.skipped = skipped

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_processed": self.total_processed,
            "matched": self.matched,
            "unmatched": self.unmatched,
            "skipped": self.skipped,
        }


def normalize_edge_types(
    conn: sqlite3.Connection,
    force: bool = False,
    dry_run: bool = False,
) -> NormalizeResult:
    """Run janitor pass: normalize edge reason → canonical_reason.

    Logic flow:
    1. Check that canonical_reason column exists (v007 migration).
       - If missing, raise RuntimeError.
    2. Load canonical type names from edge_types table.
    3. Build synonym map: merge _PREDEFINED_SYNONYMS with DB-seeded names.
    4. Fetch edges to process:
       - If force=False: only edges with canonical_reason IS NULL.
       - If force=True: all edges (re-normalize everything).
    5. For each edge:
       a. Try to match reason → canonical type via _match_reason().
       b. If matched and not dry_run: UPDATE edges SET canonical_reason=? WHERE rowid=?.
       c. Increment matched or unmatched counter.
    6. Return NormalizeResult.

    Idempotent: Without force=True, already-normalized edges are skipped.
    Provenance-safe: original reason column is NEVER modified.

    Args:
        conn: SQLite connection with edges and edge_types tables.
        force: If True, re-normalize already-normalized edges.
        dry_run: If True, compute matches but do not write to DB.

    Returns:
        NormalizeResult with counts of matched/unmatched/skipped edges.

    Raises:
        RuntimeError: If canonical_reason column does not exist (migration not applied).
    """
    # --- Step 1: Verify canonical_reason column exists ---
    cols = {row[1] for row in conn.execute("PRAGMA table_info(edges)").fetchall()}
    if "canonical_reason" not in cols:
        raise RuntimeError(
            "canonical_reason column missing — run `memory db migrate` first (requires v007)"
        )

    # --- Step 2: Load canonical types from DB ---
    canonical_names = _load_canonical_types(conn)

    # --- Step 3: Build synonym map ---
    synonym_map = _build_synonym_map(canonical_names)

    # --- Step 4: Fetch edges to process ---
    if force:
        rows = conn.execute(
            "SELECT rowid, reason, canonical_reason FROM edges"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT rowid, reason, canonical_reason FROM edges "
            "WHERE canonical_reason IS NULL"
        ).fetchall()

    result = NormalizeResult()

    # Count already-canonical edges (not fetched if force=False)
    if not force:
        skipped_count = conn.execute(
            "SELECT COUNT(*) FROM edges WHERE canonical_reason IS NOT NULL"
        ).fetchone()[0]
        result.skipped = skipped_count

    # --- Step 5: Process each edge ---
    for edge_rowid, reason, existing_canonical in rows:
        if not force and existing_canonical is not None:
            result.skipped += 1
            continue

        result.total_processed += 1

        canonical = _match_reason(reason or "", synonym_map, canonical_names)

        if canonical is not None:
            result.matched += 1
            if not dry_run:
                conn.execute(
                    "UPDATE edges SET canonical_reason = ? WHERE rowid = ?",
                    (canonical, edge_rowid),
                )
        else:
            result.unmatched += 1

    return result


def _load_canonical_types(conn: sqlite3.Connection) -> List[str]:
    """Load all canonical type names from the edge_types table.

    Returns an empty list if the edge_types table does not exist
    (graceful degradation — synonym map will rely solely on predefined list).

    Args:
        conn: SQLite connection.

    Returns:
        List of canonical type name strings (lowercase).
    """
    try:
        rows = conn.execute("SELECT name FROM edge_types").fetchall()
        return [row[0].lower() for row in rows]
    except Exception:
        return []


def _build_synonym_map(canonical_names: List[str]) -> Dict[str, str]:
    """Build the full synonym-to-canonical map.

    Combines:
    1. _PREDEFINED_SYNONYMS (hardcoded synonym clusters)
    2. Self-mappings for each canonical name (every canonical maps to itself)

    Canonical names from the DB are authoritative — if a DB name is not in
    the predefined synonyms, it's still added as a self-mapping.

    Args:
        canonical_names: List of canonical type names (lowercased) from DB.

    Returns:
        Dict mapping normalized slug → canonical name.
    """
    synonym_map: Dict[str, str] = {}

    # Add predefined synonyms
    synonym_map.update(_PREDEFINED_SYNONYMS)

    # Add self-mappings for all canonical names (DB names win for self-refs)
    for name in canonical_names:
        slug = _normalize_slug(name)
        if slug not in synonym_map:
            synonym_map[slug] = name

    return synonym_map


def _match_reason(
    reason: str,
    synonym_map: Dict[str, str],
    canonical_names: List[str],
) -> Optional[str]:
    """Resolve a free-text edge reason to a canonical type name.

    Match strategy (in priority order):
    1. Direct synonym lookup after slug normalization.
    2. Exact match against canonical names (case-insensitive).
    3. Canonical name appears as a whole-word substring of the reason.

    Args:
        reason: The raw edge reason string.
        synonym_map: Dict of normalized slug → canonical name.
        canonical_names: List of canonical type names for substring fallback.

    Returns:
        Canonical type name string, or None if no match found.
    """
    if not reason or not reason.strip():
        return None

    # Step 1: Slug normalization + synonym lookup
    slug = _normalize_slug(reason)
    if slug in synonym_map:
        return synonym_map[slug]

    # Step 2: Exact match against canonical names (case-insensitive)
    reason_lower = reason.lower().strip()
    for canonical in canonical_names:
        if reason_lower == canonical.lower():
            return canonical

    # Step 3: Whole-word substring containment
    # e.g., "my_interviewer_role" contains "interviewer"
    for canonical in canonical_names:
        # Build word-boundary regex for the canonical name (handles underscores as separators)
        pattern = r"(?<![a-z0-9])" + re.escape(canonical.lower()) + r"(?![a-z0-9])"
        if re.search(pattern, reason_lower):
            return canonical

    return None


def _normalize_slug(text: str) -> str:
    """Normalize text to a comparison slug.

    Lowercase, strip whitespace, collapse underscores/hyphens/spaces to
    underscores so "related to", "related-to", "related_to" all compare equal.

    Args:
        text: Raw string to normalize.

    Returns:
        Normalized slug string.
    """
    t = text.lower().strip()
    # Replace hyphens, spaces, multiple underscores with single underscore
    t = re.sub(r"[\s\-]+", "_", t)
    t = re.sub(r"_+", "_", t)
    t = t.strip("_")
    return t
