# =============================================================================
# Module: final_score_combine_and_rank.py
# Purpose: Final score computation and ranking — stage 8 of the light search
#   pipeline. Combines RRF/activation scores with temporal weights into a
#   single final_score per candidate, then sorts descending.
# Rationale: Upstream stages produce different score types: direct matches
#   have RRF scores, fan-out neurons have activation scores, and all have
#   temporal weights. This stage normalizes the two paths into a single
#   comparable final_score for unified ranking. The formulas are simple
#   multiplications to keep scoring interpretable and debuggable via --explain.
# Responsibility:
#   - Compute final_score for direct_match neurons: rrf_score * temporal_weight
#   - Compute final_score for fan_out neurons: activation_score * temporal_weight
#   - Sort all candidates by final_score descending
#   - Handle edge cases: missing scores default to 0, missing weights default to 1
# Organization:
#   1. Imports
#   2. compute_final_scores() — main entry point
#   3. _score_direct_match() — RRF * temporal formula
#   4. _score_fan_out() — activation * temporal formula
# =============================================================================

from __future__ import annotations

from typing import Any, Dict, List


def compute_final_scores(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compute final_score for all candidates and sort descending.

    Logic flow:
    1. For each candidate:
       a. Read match_type (must be "direct_match" or "fan_out").
       b. If direct_match → final_score = _score_direct_match(candidate).
       c. If fan_out → final_score = _score_fan_out(candidate).
       d. Attach final_score to candidate dict.
    2. Sort candidates by final_score descending.
       - Ties broken by neuron_id ascending (deterministic ordering).
    3. Return sorted list.

    Args:
        candidates: List of candidate dicts with match_type, rrf_score or
            activation_score, and temporal_weight.

    Returns:
        Same candidates sorted by final_score descending.
    """
    # --- Compute final_score for each candidate ---
    # for candidate in candidates:
    #     match_type = candidate.get("match_type", "direct_match")
    #     if match_type == "direct_match":
    #         candidate["final_score"] = _score_direct_match(candidate)
    #     else:
    #         candidate["final_score"] = _score_fan_out(candidate)
    for candidate in candidates:
        match_type = candidate.get("match_type", "direct_match")
        if match_type == "direct_match":
            candidate["final_score"] = _score_direct_match(candidate)
        elif match_type == "tag_affinity":
            candidate["final_score"] = _score_tag_affinity(candidate)
        else:
            candidate["final_score"] = _score_fan_out(candidate)

    # --- Sort descending by final_score, tiebreak by neuron_id ascending ---
    # candidates.sort(key=lambda c: (-c["final_score"], c["neuron_id"]))
    candidates.sort(key=lambda c: (-c["final_score"], c["neuron_id"]))

    # return candidates
    return candidates


def _score_direct_match(candidate: Dict[str, Any]) -> float:
    """Compute final score for a direct match (RRF seed neuron).

    Formula: final_score = rrf_score * temporal_weight

    Both components are in (0, 1] range:
    - rrf_score: from RRF fusion (higher = better text/vector match)
    - temporal_weight: from temporal decay (higher = more recent)

    Defaults: rrf_score=0.0 if missing, temporal_weight=1.0 if missing.

    Args:
        candidate: Candidate dict with rrf_score and temporal_weight.

    Returns:
        Final score as float.
    """
    # rrf_score = candidate.get("rrf_score", 0.0)
    # temporal_weight = candidate.get("temporal_weight", 1.0)
    # return rrf_score * temporal_weight
    rrf_score = candidate.get("rrf_score", 0.0)
    temporal_weight = candidate.get("temporal_weight", 1.0)
    tag_affinity_score = candidate.get("tag_affinity_score", 0.0)
    salience_weight = candidate.get("salience_weight", 1.0)
    return (rrf_score + tag_affinity_score) * temporal_weight * salience_weight


def _score_fan_out(candidate: Dict[str, Any]) -> float:
    """Compute final score for a fan-out neuron (discovered via activation).

    Formula: final_score = activation_score * temporal_weight

    Both components are in (0, 1] range:
    - activation_score: from spreading activation (higher = closer to seed)
    - temporal_weight: from temporal decay (higher = more recent)

    Defaults: activation_score=0.0 if missing, temporal_weight=1.0 if missing.

    Args:
        candidate: Candidate dict with activation_score and temporal_weight.

    Returns:
        Final score as float.
    """
    # activation_score = candidate.get("activation_score", 0.0)
    # temporal_weight = candidate.get("temporal_weight", 1.0)
    # return activation_score * temporal_weight
    activation_score = candidate.get("activation_score", 0.0)
    temporal_weight = candidate.get("temporal_weight", 1.0)
    tag_affinity_score = candidate.get("tag_affinity_score", 0.0)
    salience_weight = candidate.get("salience_weight", 1.0)
    return (activation_score + tag_affinity_score) * temporal_weight * salience_weight


def _score_tag_affinity(candidate: Dict[str, Any]) -> float:
    """Compute final score for a tag-affinity-only neuron (no edge/RRF connection).

    Formula: final_score = tag_affinity_score * temporal_weight

    These neurons were discovered purely through shared tags with seeds —
    they had no direct text/vector match and no edge-based activation.

    Defaults: tag_affinity_score=0.0 if missing, temporal_weight=1.0 if missing.

    Args:
        candidate: Candidate dict with tag_affinity_score and temporal_weight.

    Returns:
        Final score as float.
    """
    tag_affinity_score = candidate.get("tag_affinity_score", 0.0)
    temporal_weight = candidate.get("temporal_weight", 1.0)
    salience_weight = candidate.get("salience_weight", 1.0)
    return tag_affinity_score * temporal_weight * salience_weight
