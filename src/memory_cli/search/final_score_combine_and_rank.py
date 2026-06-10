# =============================================================================
# Module: final_score_combine_and_rank.py
# Purpose: Final score computation and ranking — stage 8 of the light search
#   pipeline. Combines each candidate's MATCH-QUALITY signal (RRF for direct
#   matches, activation for fan-out, tag-affinity for tag-only neighbors) with
#   temporal / affinity / salience MODIFIERS into a single final_score, then
#   sorts descending.
# Rationale: Upstream stages produce scores on wildly different scales:
#     - rrf_score   : RANK-based, hard ceiling 2/61 ≈ 0.0328 (k=60)
#     - activation_score : 0..1 (spreading activation)
#     - tag_affinity_score : ~0..1 (sum of 1/count tag weights)
#     - temporal_weight : 0..1 (exponential decay)
#     - salience_weight : >= 1.0, UNBOUNDED above (access-count log boost)
#   The OLD formula `(rrf_score + tag_affinity_score) * temporal * salience`
#   ADDED a 0.033-ceiling rank score to a 0..1 affinity score then multiplied
#   by an unbounded salience — so match quality contributed <=4% of the total
#   and old, frequently-accessed, loosely-tagged neurons permanently buried
#   perfect text/vector matches (backlog #71 / MEM-FIX-0006).
#   THE FIX (rescale + bounded modifiers — directions 1+2 of #71, hybrid):
#     1. Normalize the match-quality signal into a 0..1 BASE that DOMINATES.
#        - direct_match : base = rrf_score / RRF_MAX  (perfect match -> 1.0)
#        - fan_out      : base = activation_score      (already 0..1)
#        - tag_affinity : base = capped affinity, kept in a sub-1.0 band so a
#                         tag-only neighbor can never outrank a strong direct
#                         match (see TAG_AFFINITY_BASE_CAP).
#     2. Apply affinity / salience as BOUNDED multipliers centered on 1.0, and
#        temporal as its natural 0..1 multiplier:
#            final = base * temporal_weight
#                         * (1 + AFFINITY_GAIN * min(tag_affinity, 1.0))
#                         * (1 + SALIENCE_GAIN * min(salience_weight - 1, SAL_CAP))
#        Salience is clamped HERE (we do NOT change how it is computed upstream).
#   Result: a top-rrf direct match with weak modifiers outranks a mid-rrf match
#   with maxed modifiers — match quality is the dominant signal, modifiers only
#   nudge. Formula is fixed (no config knobs), interpretable, debuggable via
#   --explain (explain_scoring_breakdown.py passes the component fields through
#   unchanged — it does NOT recompute, so it stays consistent automatically).
# Responsibility:
#   - direct_match final_score: normalized_rrf * temporal * affinity_mod * salience_mod
#   - fan_out final_score:      activation     * temporal * affinity_mod * salience_mod
#   - tag_affinity final_score: capped_affinity_base * temporal * salience_mod
#   - Sort all candidates by final_score descending (tiebreak neuron_id asc)
#   - Handle edge cases: missing scores default to 0, missing weights default to 1
# Organization:
#   1. Imports
#   2. Constants (RRF_MAX, gains, caps)
#   3. compute_final_scores() — main entry point
#   4. _affinity_modifier() / _salience_modifier() — shared bounded modifiers
#   5. _score_direct_match() — normalized-RRF base * modifiers
#   6. _score_fan_out() — activation base * modifiers
#   7. _score_tag_affinity() — capped affinity base * modifiers (no match signal)
# =============================================================================

from __future__ import annotations

from typing import Any, Dict, List


# -----------------------------------------------------------------------------
# Constants — fixed, interpretable, no config knobs (per backlog #71).
# -----------------------------------------------------------------------------

# Maximum possible rrf_score: a candidate at rank 0 in BOTH the BM25 and the
# vector list scores 2 * 1/(60+0+1) = 2/61. Dividing rrf_score by this maps a
# perfect dual-list match to a normalized base of 1.0. (Matches the live trace
# in backlog #71: GLOBAL-686 rrf=0.0328 == RRF_MAX -> base 1.0.)
RRF_MAX = 2.0 / 61.0  # ≈ 0.032787

# Affinity modifier gain. tag_affinity (clamped to 1.0) contributes at most this
# fraction as a boost: affinity_modifier ∈ [1.0, 1 + AFFINITY_GAIN].
AFFINITY_GAIN = 0.25

# Salience modifier gain + clamp. Upstream salience_weight is >= 1.0 and
# UNBOUNDED above (log access-count boost). We clamp its EXCESS (weight - 1) to
# SALIENCE_CAP before applying gain, so salience_modifier ∈ [1.0, 1 + GAIN*CAP].
# We do NOT touch how salience is computed — only how much it is allowed to move
# the final ranking. With GAIN=0.25, CAP=1.0 -> salience_modifier ∈ [1.0, 1.25].
SALIENCE_GAIN = 0.25
SALIENCE_CAP = 1.0

# Base ceiling for the tag-affinity-ONLY pool. These neurons have NO text/vector
# match and NO edge activation — only shared tags. Their base is capped well
# below 1.0 so that even a maxed tag-affinity neighbor (cap * salience_mod) stays
# below a strong direct match (base near 1.0). Concretely the affinity-pool
# ceiling is 0.5 * 1.25(salience) = 0.625 < a strong direct match.
TAG_AFFINITY_BASE_CAP = 0.5


def compute_final_scores(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compute final_score for all candidates and sort descending.

    Logic flow:
    1. For each candidate:
       a. Read match_type ("direct_match", "fan_out", or "tag_affinity").
       b. direct_match  -> final_score = _score_direct_match(candidate)
       c. fan_out       -> final_score = _score_fan_out(candidate)
       d. tag_affinity  -> final_score = _score_tag_affinity(candidate)
       e. Attach final_score to candidate dict.
    2. Sort candidates by final_score descending.
       - Ties broken by neuron_id ascending (deterministic ordering).
    3. Return sorted list.

    All three pools share ONE comparable scale: match-quality base (0..1,
    capped <0.625 for the tag-affinity-only pool) times bounded modifiers, so
    a strong direct match always outranks a tag-affinity-only neighbor.

    Args:
        candidates: List of candidate dicts with match_type and the relevant
            score components (rrf_score / activation_score / tag_affinity_score,
            temporal_weight, salience_weight).

    Returns:
        Same candidates sorted by final_score descending.
    """
    for candidate in candidates:
        match_type = candidate.get("match_type", "direct_match")
        if match_type == "direct_match":
            candidate["final_score"] = _score_direct_match(candidate)
        elif match_type == "tag_affinity":
            candidate["final_score"] = _score_tag_affinity(candidate)
        else:
            candidate["final_score"] = _score_fan_out(candidate)

    # --- Sort descending by final_score, tiebreak by neuron_id ascending ---
    candidates.sort(key=lambda c: (-c["final_score"], c["neuron_id"]))

    return candidates


# -----------------------------------------------------------------------------
# Shared bounded modifiers — keep affinity/salience near 1.0 so they NUDGE the
# ranking instead of swamping the match-quality base.
# -----------------------------------------------------------------------------

def _affinity_modifier(tag_affinity_score: float) -> float:
    """Bounded tag-affinity multiplier centered on 1.0.

    modifier = 1 + AFFINITY_GAIN * min(tag_affinity_score, 1.0)

    Range: [1.0, 1 + AFFINITY_GAIN]. Clamping at 1.0 keeps an unusually large
    multi-tag affinity sum from acting as a runaway boost.
    """
    return 1.0 + AFFINITY_GAIN * min(tag_affinity_score, 1.0)


def _salience_modifier(salience_weight: float) -> float:
    """Bounded salience multiplier centered on 1.0.

    modifier = 1 + SALIENCE_GAIN * min(max(salience_weight - 1.0, 0.0), SALIENCE_CAP)

    Upstream salience_weight is >= 1.0 and unbounded above. We clamp its EXCESS
    to SALIENCE_CAP so a heavily-accessed neuron gets a fixed, bounded nudge
    instead of dominating the ranking. Range: [1.0, 1 + SALIENCE_GAIN*SALIENCE_CAP].
    """
    excess = max(salience_weight - 1.0, 0.0)
    return 1.0 + SALIENCE_GAIN * min(excess, SALIENCE_CAP)


def _score_direct_match(candidate: Dict[str, Any]) -> float:
    """Compute final score for a direct match (RRF seed neuron).

    Formula:
        base  = rrf_score / RRF_MAX                      (0..1, dominant)
        final = base * temporal_weight
                     * _affinity_modifier(tag_affinity_score)
                     * _salience_modifier(salience_weight)

    rrf_score is RANK-based with hard ceiling RRF_MAX (= 2/61). Normalizing it
    makes a perfect dual-list match a base of 1.0; affinity/salience/temporal
    only modulate around that. This is the core of the MEM-FIX-0006 fix: the
    match signal dominates, the modifiers nudge.

    Defaults: rrf_score=0.0, temporal_weight=1.0, tag_affinity_score=0.0,
    salience_weight=1.0 (all missing -> neutral).

    Args:
        candidate: Candidate dict with rrf_score, temporal_weight,
            tag_affinity_score, salience_weight.

    Returns:
        Final score as float.
    """
    rrf_score = candidate.get("rrf_score", 0.0)
    temporal_weight = candidate.get("temporal_weight", 1.0)
    tag_affinity_score = candidate.get("tag_affinity_score", 0.0)
    salience_weight = candidate.get("salience_weight", 1.0)

    base = rrf_score / RRF_MAX
    return (
        base
        * temporal_weight
        * _affinity_modifier(tag_affinity_score)
        * _salience_modifier(salience_weight)
    )


def _score_fan_out(candidate: Dict[str, Any]) -> float:
    """Compute final score for a fan-out neuron (discovered via activation).

    Formula:
        base  = activation_score                         (already 0..1, dominant)
        final = base * temporal_weight
                     * _affinity_modifier(tag_affinity_score)
                     * _salience_modifier(salience_weight)

    Same discipline as direct matches: activation (the match-quality signal for
    graph-discovered neurons) is the dominant base; affinity/salience/temporal
    are bounded modifiers. Fixes the same additive scale defect the OLD formula
    had here (`(activation + tag_affinity) * temporal * salience`).

    Defaults: activation_score=0.0, temporal_weight=1.0, tag_affinity_score=0.0,
    salience_weight=1.0.

    Args:
        candidate: Candidate dict with activation_score, temporal_weight,
            tag_affinity_score, salience_weight.

    Returns:
        Final score as float.
    """
    activation_score = candidate.get("activation_score", 0.0)
    temporal_weight = candidate.get("temporal_weight", 1.0)
    tag_affinity_score = candidate.get("tag_affinity_score", 0.0)
    salience_weight = candidate.get("salience_weight", 1.0)

    base = activation_score
    return (
        base
        * temporal_weight
        * _affinity_modifier(tag_affinity_score)
        * _salience_modifier(salience_weight)
    )


def _score_tag_affinity(candidate: Dict[str, Any]) -> float:
    """Compute final score for a tag-affinity-only neuron (no edge/RRF connection).

    Formula:
        base  = min(tag_affinity_score, 1.0) * TAG_AFFINITY_BASE_CAP   (<= 0.5)
        final = base * temporal_weight * _salience_modifier(salience_weight)

    These neurons were discovered PURELY through shared tags with seeds — they
    have no text/vector match and no edge-based activation, so affinity IS their
    only "match" signal. To keep the three pools comparable in ONE sorted list,
    their base is capped at TAG_AFFINITY_BASE_CAP (0.5) so even a maxed
    tag-affinity neighbor (0.5 * 1.25 salience = 0.625) cannot outrank a strong
    direct match (base near 1.0). No separate affinity_modifier here — affinity
    already IS the base for this pool (applying it twice would double-count).

    Defaults: tag_affinity_score=0.0, temporal_weight=1.0, salience_weight=1.0.

    Args:
        candidate: Candidate dict with tag_affinity_score, temporal_weight,
            salience_weight.

    Returns:
        Final score as float.
    """
    tag_affinity_score = candidate.get("tag_affinity_score", 0.0)
    temporal_weight = candidate.get("temporal_weight", 1.0)
    salience_weight = candidate.get("salience_weight", 1.0)

    base = min(tag_affinity_score, 1.0) * TAG_AFFINITY_BASE_CAP
    return base * temporal_weight * _salience_modifier(salience_weight)
