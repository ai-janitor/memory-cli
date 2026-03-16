# =============================================================================
# Module: salience_scoring_access_metrics.py
# Purpose: Salience scoring using access metrics — boosts neurons that are
#   frequently and recently accessed. Runs between temporal decay and tag
#   filtering in the light search pipeline.
# Rationale: Neurons that are accessed more often and more recently are more
#   "salient" — they represent actively-used knowledge. This signal is
#   orthogonal to creation-time temporal decay: a neuron created 6 months ago
#   but accessed yesterday is highly salient. The salience weight is
#   multiplicative on final_score, with zero-access neurons getting weight 1.0
#   (neutral — no penalty for never being accessed).
# Responsibility:
#   - Batch-fetch access_count and last_accessed_at from neurons table
#   - Compute frequency boost from access_count (log-scaled)
#   - Compute recency-of-access boost from last_accessed_at (exponential decay)
#   - Combine into salience_weight >= 1.0 (always a boost, never a penalty)
#   - Attach salience_weight to each candidate dict
# Organization:
#   1. Imports
#   2. Constants (default scales, half-life)
#   3. apply_salience_scoring() — main entry point
#   4. _compute_frequency_boost() — log-scaled access count boost
#   5. _compute_recency_boost() — exponential decay on last access time
# =============================================================================

from __future__ import annotations

import math
import sqlite3
import time
from typing import Any, Dict, List, Optional


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

# Scale factor for frequency boost. Controls how much access_count matters.
# With default 0.1, a neuron accessed 10 times gets ~0.35 boost.
DEFAULT_FREQ_SCALE = 0.1

# Scale factor for recency-of-access boost. Controls the maximum boost from
# recent access. A neuron accessed just now gets this full value added.
DEFAULT_RECENCY_SCALE = 0.2

# Half-life for recency-of-access decay in days. At this many days since last
# access, the recency boost is halved. Default 7 days — access recency decays
# faster than creation-time temporal decay (30 days) because "recently used"
# is a sharper signal.
DEFAULT_ACCESS_HALF_LIFE_DAYS = 7


def apply_salience_scoring(
    conn: sqlite3.Connection,
    candidates: List[Dict[str, Any]],
    freq_scale: float = DEFAULT_FREQ_SCALE,
    recency_scale: float = DEFAULT_RECENCY_SCALE,
    access_half_life_days: float = DEFAULT_ACCESS_HALF_LIFE_DAYS,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Apply salience scoring based on access metrics to all candidates.

    Each candidate gets a salience_weight field. The weight is >= 1.0:
    zero-access neurons get exactly 1.0 (neutral), accessed neurons get
    a boost proportional to how often and how recently they were accessed.

    Logic flow:
    1. Batch-fetch access_count and last_accessed_at for all candidate neurons.
    2. For each candidate:
       a. Compute frequency boost from access_count (log-scaled).
       b. Compute recency boost from last_accessed_at (exponential decay).
       c. salience_weight = 1.0 + frequency_boost + recency_boost.
       d. Attach salience_weight to candidate dict.
    3. Return modified candidate list (same list, mutated in-place).

    Args:
        conn: SQLite connection (for access metric lookups).
        candidates: List of candidate dicts (must have neuron_id).
        freq_scale: Scale factor for frequency boost (default 0.1).
        recency_scale: Scale factor for recency boost (default 0.2).
        access_half_life_days: Half-life for recency decay (default 7 days).
        now: Optional current timestamp in seconds since epoch (for testing).

    Returns:
        Same candidate list with salience_weight added to each dict.
    """
    neuron_ids = [c["neuron_id"] for c in candidates]
    if not neuron_ids:
        return candidates

    now_ts = now if now is not None else time.time()

    # --- Batch-fetch access metrics ---
    placeholders = ",".join("?" * len(neuron_ids))
    rows = conn.execute(
        f"SELECT id, access_count, last_accessed_at FROM neurons WHERE id IN ({placeholders})",
        neuron_ids,
    ).fetchall()
    metrics_map = {row[0]: (row[1], row[2]) for row in rows}

    # --- Compute decay lambda for recency ---
    recency_lambda = math.log(2) / access_half_life_days

    # --- Apply salience to each candidate ---
    for candidate in candidates:
        nid = candidate["neuron_id"]
        metrics = metrics_map.get(nid)

        if metrics is None:
            candidate["salience_weight"] = 1.0
            continue

        access_count, last_accessed_at = metrics

        # Frequency boost: log-scaled access count
        freq_boost = _compute_frequency_boost(
            access_count if access_count else 0, freq_scale
        )

        # Recency boost: exponential decay on last access time
        recency_boost = _compute_recency_boost(
            last_accessed_at, now_ts, recency_lambda, recency_scale
        )

        # Combined weight: always >= 1.0 (boost only, never penalty)
        candidate["salience_weight"] = 1.0 + freq_boost + recency_boost

    return candidates


def _compute_frequency_boost(access_count: int, freq_scale: float) -> float:
    """Compute frequency boost from access count.

    Formula: boost = log2(1 + access_count) * freq_scale

    Properties:
    - access_count = 0 → boost = 0.0 (no penalty)
    - access_count = 1 → boost ≈ 0.1 (with default scale)
    - access_count = 10 → boost ≈ 0.35 (with default scale)
    - access_count = 100 → boost ≈ 0.67 (with default scale)
    - Logarithmic scaling prevents high-access neurons from dominating.

    Args:
        access_count: Number of times neuron was accessed.
        freq_scale: Scale factor (default 0.1).

    Returns:
        Frequency boost >= 0.
    """
    return math.log2(1 + access_count) * freq_scale


def _compute_recency_boost(
    last_accessed_at_ms: Optional[int],
    now_seconds: float,
    recency_lambda: float,
    recency_scale: float,
) -> float:
    """Compute recency-of-access boost from last_accessed_at timestamp.

    Formula: boost = e^(-lambda * days_since_access) * recency_scale

    Properties:
    - Never accessed (None) → boost = 0.0 (no penalty)
    - Accessed just now → boost = recency_scale (full boost)
    - Accessed at half-life → boost = recency_scale * 0.5
    - Accessed long ago → boost → 0 (fades to neutral)

    Args:
        last_accessed_at_ms: Last access timestamp in milliseconds (nullable).
        now_seconds: Current time in seconds since epoch.
        recency_lambda: Decay constant (ln(2) / half_life_days).
        recency_scale: Maximum recency boost value.

    Returns:
        Recency boost >= 0.
    """
    if last_accessed_at_ms is None:
        return 0.0

    last_accessed_s = last_accessed_at_ms / 1000.0
    age_seconds = max(0.0, now_seconds - last_accessed_s)
    age_days = age_seconds / 86400.0

    return math.exp(-recency_lambda * age_days) * recency_scale
