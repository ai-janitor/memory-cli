# =============================================================================
# Module: tag_affinity_scoring_shared_tags.py
# Purpose: Tag-affinity scoring — inserted after spreading activation (stage 5)
#   and before temporal decay (stage 6) in the light search pipeline. Boosts
#   neurons that share tags with seed neurons. Rare tags (fewer neurons) produce
#   stronger affinity signals than common tags. Supports depth=2: after the
#   depth=1 pass discovers tag neighbors, a second pass finds neurons sharing
#   tags with those depth=1 results. Weight decays multiplicatively across hops.
# Rationale: Spreading activation discovers related neurons via edges, but misses
#   neurons connected only by shared tags (no explicit edge exists). Tag-affinity
#   scoring fills this gap: if a seed neuron has tag "rust" and another neuron
#   also has tag "rust", that second neuron gets a boost proportional to how rare
#   "rust" is (1 / count_of_neurons_with_that_tag). Multiple shared tags sum.
#   Depth=2 extends this: depth=1 results become intermediate seeds, and neurons
#   sharing tags with THOSE get discovered with multiplicatively decayed weight
#   (hop1_score × hop2_weight). This enables multi-hop tag traversal like:
#   arc-b60 →(cpp)→ GLOBAL-131 →(architecture)→ GLOBAL-124.
#   No threshold cutoff: weak tag-links are still returned because "I found
#   something weakly connected" beats "I found nothing."
# Responsibility:
#   - Collect tags from seed neurons (match_type == "direct_match")
#   - Compute tag weight = 1 / count(neurons_with_tag) for each seed tag
#   - For each candidate, sum weights of shared tags with seeds
#   - Attach tag_affinity_score and tag_affinity_depth to each candidate dict
#   - Discover NEW neurons sharing tags with seeds (not already in candidates)
#     and inject them as tag_affinity match_type candidates (depth=1)
#   - Run depth=2 pass: use depth=1 discoveries as intermediate seeds,
#     discover neurons sharing tags with those, inject with multiplicative weight
#   - No new edges created, no schema changes
# Organization:
#   1. Imports
#   2. apply_tag_affinity() — main entry point (depth=1 + depth=2)
#   3. _collect_seed_tags() — get tags for seed neurons from DB
#   4. _compute_tag_weights() — weight = 1/count(neurons_with_tag)
#   5. _score_candidates() — sum shared-tag weights per candidate
#   6. _discover_tag_neighbors() — find new neurons sharing tags with seeds
#   7. _run_depth2_pass() — second hop: depth=1 results → their tag neighbors
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Set, Tuple


def apply_tag_affinity(
    conn: sqlite3.Connection,
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Apply tag-affinity scoring (depth=1 + depth=2) to candidates.

    Logic flow:
    1. Identify seed neurons (match_type == "direct_match") from candidates.
    2. Collect tags for all seed neurons from the neuron_tags + tags tables.
       - If seeds have no tags → return candidates unchanged (all get
         tag_affinity_score = 0.0).
    3. Compute tag weights: for each seed tag, weight = 1 / count(neurons
       with that tag). Rare tags get higher weight.
    4. For each existing candidate:
       a. Look up its tags from the DB.
       b. Sum weights of tags shared with seed tags.
       c. Attach tag_affinity_score to the candidate dict.
    5. Discover new neurons that share tags with seeds but are NOT already
       in the candidate set. Inject them as new candidates with
       match_type = "tag_affinity", tag_affinity_depth = 1.
    6. Depth=2 pass: use depth=1 discovered neurons as intermediate seeds.
       Collect their tags, find neurons sharing those tags that are NOT
       already in the candidate set. Weight = hop1_score × hop2_weight
       (multiplicative decay). Inject with tag_affinity_depth = 2.
    7. Return the augmented candidate list (original + depth=1 + depth=2).

    No threshold cutoff: even weak tag_affinity_scores are kept.
    No new edges created, no schema changes.

    Args:
        conn: SQLite connection with neuron_tags and tags tables.
        candidates: List of candidate dicts from spreading activation stage.

    Returns:
        Same candidates with tag_affinity_score and tag_affinity_depth added,
        plus newly discovered tag-neighbor neurons from depth=1 and depth=2.
    """
    # --- Identify seed neuron IDs ---
    seed_ids = [
        c["neuron_id"] for c in candidates
        if c.get("match_type") == "direct_match"
    ]

    # --- Early exit: no seeds → nothing to compute ---
    if not seed_ids:
        for c in candidates:
            c["tag_affinity_score"] = 0.0
            c["tag_affinity_depth"] = None
        return candidates

    # --- Collect seed tags ---
    seed_tag_ids = _collect_seed_tags(conn, seed_ids)

    # --- Early exit: seeds have no tags → nothing to compute ---
    if not seed_tag_ids:
        for c in candidates:
            c["tag_affinity_score"] = 0.0
            c["tag_affinity_depth"] = None
        return candidates

    # --- Compute tag weights (1 / count of neurons with that tag) ---
    tag_weights = _compute_tag_weights(conn, seed_tag_ids)

    # --- Score existing candidates ---
    existing_ids = _score_candidates(conn, candidates, seed_tag_ids, tag_weights)

    # --- Mark existing candidates with no tag_affinity_depth ---
    for c in candidates:
        if "tag_affinity_depth" not in c:
            c["tag_affinity_depth"] = None

    # --- Depth=1: Discover new tag-neighbor neurons ---
    depth1_candidates = _discover_tag_neighbors(
        conn, seed_tag_ids, tag_weights, existing_ids
    )
    # Mark depth=1 discoveries
    for c in depth1_candidates:
        c["tag_affinity_depth"] = 1

    # --- Update existing_ids to include depth=1 discoveries ---
    all_ids_after_depth1 = existing_ids | {c["neuron_id"] for c in depth1_candidates}

    # --- Depth=2: Use depth=1 discoveries as intermediate seeds ---
    depth2_candidates = _run_depth2_pass(
        conn, depth1_candidates, tag_weights, all_ids_after_depth1
    )

    # --- Merge: original + depth=1 + depth=2 ---
    return candidates + depth1_candidates + depth2_candidates


def _collect_seed_tags(
    conn: sqlite3.Connection,
    seed_ids: List[int],
) -> Set[int]:
    """Get the set of tag IDs attached to any seed neuron.

    Logic flow:
    1. Query neuron_tags for all rows where neuron_id IN seed_ids.
    2. Return the set of distinct tag_ids.

    Args:
        conn: SQLite connection.
        seed_ids: List of seed neuron IDs.

    Returns:
        Set of tag IDs found on seed neurons.
    """
    if not seed_ids:
        return set()

    placeholders = ",".join("?" for _ in seed_ids)
    rows = conn.execute(
        f"SELECT DISTINCT tag_id FROM neuron_tags WHERE neuron_id IN ({placeholders})",
        seed_ids,
    ).fetchall()
    return {row[0] for row in rows}


def _compute_tag_weights(
    conn: sqlite3.Connection,
    tag_ids: Set[int],
) -> Dict[int, float]:
    """Compute weight for each tag: weight = 1 / count(neurons with that tag).

    Rare tags (few neurons) get higher weight; common tags get lower weight.

    Logic flow:
    1. For each tag_id, COUNT neurons in neuron_tags with that tag_id.
    2. weight = 1.0 / count. If count is 0 (shouldn't happen if tag_id
       came from seed), weight = 0.0 to avoid division by zero.
    3. Return {tag_id: weight}.

    Args:
        conn: SQLite connection.
        tag_ids: Set of tag IDs to compute weights for.

    Returns:
        Dict mapping tag_id → weight (float).
    """
    if not tag_ids:
        return {}

    placeholders = ",".join("?" for _ in tag_ids)
    rows = conn.execute(
        f"SELECT tag_id, COUNT(*) FROM neuron_tags "
        f"WHERE tag_id IN ({placeholders}) GROUP BY tag_id",
        list(tag_ids),
    ).fetchall()

    weights: Dict[int, float] = {}
    for tag_id, count in rows:
        weights[tag_id] = 1.0 / count if count > 0 else 0.0
    return weights


def _score_candidates(
    conn: sqlite3.Connection,
    candidates: List[Dict[str, Any]],
    seed_tag_ids: Set[int],
    tag_weights: Dict[int, float],
) -> Set[int]:
    """Score existing candidates by summing shared-tag weights with seeds.

    Logic flow:
    1. Collect all candidate neuron_ids.
    2. Batch-query their tags from neuron_tags.
    3. For each candidate, sum tag_weights[tag_id] for tags shared with seeds.
    4. Attach tag_affinity_score to each candidate dict.
    5. Return set of all candidate neuron_ids (for dedup in discovery step).

    Args:
        conn: SQLite connection.
        candidates: List of candidate dicts to score.
        seed_tag_ids: Set of tag IDs from seed neurons.
        tag_weights: Dict mapping tag_id → weight.

    Returns:
        Set of all neuron IDs that are already in the candidate list.
    """
    # --- Collect candidate neuron IDs ---
    candidate_ids = [c["neuron_id"] for c in candidates]
    existing_ids = set(candidate_ids)

    if not candidate_ids:
        return existing_ids

    # --- Batch-query tags for all candidates ---
    placeholders = ",".join("?" for _ in candidate_ids)
    rows = conn.execute(
        f"SELECT neuron_id, tag_id FROM neuron_tags "
        f"WHERE neuron_id IN ({placeholders})",
        candidate_ids,
    ).fetchall()

    # --- Build neuron_id → set of tag_ids ---
    neuron_tags: Dict[int, Set[int]] = {}
    for neuron_id, tag_id in rows:
        neuron_tags.setdefault(neuron_id, set()).add(tag_id)

    # --- Score each candidate ---
    for candidate in candidates:
        nid = candidate["neuron_id"]
        tags = neuron_tags.get(nid, set())
        shared = tags & seed_tag_ids
        score = sum(tag_weights.get(tid, 0.0) for tid in shared)
        candidate["tag_affinity_score"] = score

    return existing_ids


def _discover_tag_neighbors(
    conn: sqlite3.Connection,
    seed_tag_ids: Set[int],
    tag_weights: Dict[int, float],
    existing_ids: Set[int],
) -> List[Dict[str, Any]]:
    """Find neurons sharing tags with seeds that are NOT already candidates.

    Logic flow:
    1. Query neuron_tags for all neurons having any seed tag.
    2. Filter out neurons already in existing_ids.
    3. For each new neuron, sum tag_weights for its shared tags.
    4. Return as new candidate dicts with match_type="tag_affinity".

    Args:
        conn: SQLite connection.
        seed_tag_ids: Set of tag IDs from seed neurons.
        tag_weights: Dict mapping tag_id → weight.
        existing_ids: Neuron IDs already in the candidate set.

    Returns:
        List of new candidate dicts with tag_affinity metadata.
    """
    if not seed_tag_ids:
        return []

    placeholders = ",".join("?" for _ in seed_tag_ids)
    rows = conn.execute(
        f"SELECT neuron_id, tag_id FROM neuron_tags "
        f"WHERE tag_id IN ({placeholders})",
        list(seed_tag_ids),
    ).fetchall()

    # --- Group by neuron_id, filter out existing ---
    neighbor_tags: Dict[int, Set[int]] = {}
    for neuron_id, tag_id in rows:
        if neuron_id not in existing_ids:
            neighbor_tags.setdefault(neuron_id, set()).add(tag_id)

    # --- Build new candidate dicts ---
    new_candidates: List[Dict[str, Any]] = []
    for neuron_id, tags in neighbor_tags.items():
        shared = tags & seed_tag_ids
        score = sum(tag_weights.get(tid, 0.0) for tid in shared)
        if score > 0:
            new_candidates.append({
                "neuron_id": neuron_id,
                "tag_affinity_score": score,
                "match_type": "tag_affinity",
                "activation_score": 0.0,
                "rrf_score": 0.0,
                "hop_distance": None,
                "edge_reason": None,
            })

    return new_candidates


def _run_depth2_pass(
    conn: sqlite3.Connection,
    depth1_candidates: List[Dict[str, Any]],
    depth1_tag_weights: Dict[int, float],
    existing_ids: Set[int],
) -> List[Dict[str, Any]]:
    """Run the depth=2 tag-affinity pass using depth=1 discoveries as seeds.

    Logic flow:
    1. Use depth=1 discovered neurons as intermediate seeds.
    2. Collect their tags from the DB.
    3. Compute tag weights for THOSE tags (1/count as usual).
    4. Find neurons sharing those tags that are NOT already in existing_ids.
    5. For each depth=2 discovery:
       a. Compute hop2_weight = sum of shared tag weights with the hop1 neuron(s).
       b. Find the best hop1 score among the depth=1 neurons that connect to
          this depth=2 neuron via shared tags.
       c. Final depth=2 score = max(hop1_score × hop2_weight) across all
          connecting hop1 neurons (take the strongest path).
    6. Inject as new candidates with match_type="tag_affinity",
       tag_affinity_depth=2.

    Weight decay is multiplicative: the depth=2 score is always less than
    the depth=1 score it derives from, ensuring depth=2 results rank below
    depth=1 results by default.

    Args:
        conn: SQLite connection.
        depth1_candidates: Candidates discovered at depth=1.
        depth1_tag_weights: Tag weights computed during depth=1 pass.
        existing_ids: All neuron IDs already in the candidate set
            (original + depth=1).

    Returns:
        List of new candidate dicts for depth=2 discoveries.
    """
    if not depth1_candidates:
        return []

    # --- Collect hop1 neuron IDs and their scores ---
    hop1_ids = [c["neuron_id"] for c in depth1_candidates]
    hop1_scores: Dict[int, float] = {
        c["neuron_id"]: c["tag_affinity_score"] for c in depth1_candidates
    }

    # --- Collect tags for hop1 neurons ---
    hop1_tag_ids = _collect_seed_tags(conn, hop1_ids)
    if not hop1_tag_ids:
        return []

    # --- Compute tag weights for hop2 tags ---
    hop2_tag_weights = _compute_tag_weights(conn, hop1_tag_ids)

    # --- Find all neurons sharing tags with hop1 neurons ---
    placeholders = ",".join("?" for _ in hop1_tag_ids)
    rows = conn.execute(
        f"SELECT neuron_id, tag_id FROM neuron_tags "
        f"WHERE tag_id IN ({placeholders})",
        list(hop1_tag_ids),
    ).fetchall()

    # --- Group by neuron_id, filter out existing ---
    neighbor_tags: Dict[int, Set[int]] = {}
    for neuron_id, tag_id in rows:
        if neuron_id not in existing_ids:
            neighbor_tags.setdefault(neuron_id, set()).add(tag_id)

    if not neighbor_tags:
        return []

    # --- Build hop1 neuron → set of tag_ids mapping ---
    hop1_neuron_tags: Dict[int, Set[int]] = {}
    if hop1_ids:
        ph = ",".join("?" for _ in hop1_ids)
        hop1_rows = conn.execute(
            f"SELECT neuron_id, tag_id FROM neuron_tags "
            f"WHERE neuron_id IN ({ph})",
            hop1_ids,
        ).fetchall()
        for neuron_id, tag_id in hop1_rows:
            hop1_neuron_tags.setdefault(neuron_id, set()).add(tag_id)

    # --- Score each depth=2 candidate ---
    # For each depth=2 neuron, find which hop1 neurons connect to it via
    # shared tags, and take the strongest path (max hop1_score × hop2_weight).
    depth2_candidates: List[Dict[str, Any]] = []
    for neuron_id, d2_tags in neighbor_tags.items():
        best_score = 0.0
        for hop1_id, hop1_tags in hop1_neuron_tags.items():
            # Tags shared between this depth=2 neuron and this hop1 neuron
            shared_with_hop1 = d2_tags & hop1_tags
            if not shared_with_hop1:
                continue
            # hop2_weight = sum of tag weights for shared tags
            hop2_weight = sum(hop2_tag_weights.get(tid, 0.0) for tid in shared_with_hop1)
            # Multiplicative decay: hop1_score × hop2_weight
            path_score = hop1_scores.get(hop1_id, 0.0) * hop2_weight
            if path_score > best_score:
                best_score = path_score

        if best_score > 0:
            depth2_candidates.append({
                "neuron_id": neuron_id,
                "tag_affinity_score": best_score,
                "match_type": "tag_affinity",
                "tag_affinity_depth": 2,
                "activation_score": 0.0,
                "rrf_score": 0.0,
                "hop_distance": None,
                "edge_reason": None,
            })

    return depth2_candidates
