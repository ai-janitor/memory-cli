# =============================================================================
# Module: spreading_activation_bfs_linear_decay.py
# Purpose: BFS spreading activation — stage 5 of the light search pipeline.
#   Propagates activation energy from RRF seed neurons through the graph's
#   edges, discovering related neurons that weren't direct text/vector matches.
# Rationale: The memory graph encodes relationships (edges with weights and
#   reasons) that pure text/vector search misses. Spreading activation is
#   the classic way to exploit relational structure: seed nodes push energy
#   to neighbors, decaying with distance. Linear decay is chosen over
#   exponential for simplicity and interpretability — each hop costs a fixed
#   fraction of activation, making depth limits predictable.
# Responsibility:
#   - BFS traversal from RRF seed neurons (activation=1.0 for seeds)
#   - Linear decay: activation = max(0, 1 - (depth+1) * decay_rate)
#   - Edge weight modulation: activation * edge_weight at each hop
#   - Bidirectional edge traversal (both source→target and target→source)
#   - Visited set with max-score update (re-visit only if higher activation)
#   - Depth limit via --fan-out-depth (default 1, max 3)
#   - Return all activated neurons with activation scores and hop metadata
# Organization:
#   1. Imports
#   2. Constants (default decay rate, max depth)
#   3. spread() — main entry point
#   4. _bfs_activate() — core BFS loop with decay and visited tracking
#   5. _get_neighbors() — query edges for bidirectional neighbors
#   6. _compute_activation() — linear decay + edge weight modulation
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

# Default decay rate per hop. With decay_rate=0.3:
#   depth 0 (seed): activation = 1.0 (explicit, not from formula)
#   depth 1: activation = max(0, 1 - (1+1)*0.3) = 0.4
#   depth 2: activation = max(0, 1 - (2+1)*0.3) = 0.1
#   depth 3: activation = max(0, 1 - (3+1)*0.3) = 0.0 (fully decayed)
DEFAULT_DECAY_RATE = 0.3

# Maximum allowed fan-out depth. Hard cap to prevent graph explosion.
MAX_FAN_OUT_DEPTH = 3

# Default fan-out depth if not specified.
DEFAULT_FAN_OUT_DEPTH = 1

# Edge table name — must match schema migration.
EDGES_TABLE = "edges"


def spread(
    conn: sqlite3.Connection,
    rrf_candidates: List[Dict[str, Any]],
    fan_out_depth: int = DEFAULT_FAN_OUT_DEPTH,
    decay_rate: float = DEFAULT_DECAY_RATE,
) -> List[Dict[str, Any]]:
    """Perform BFS spreading activation from RRF seed neurons.

    Seeds (direct matches from RRF) start with activation=1.0. Activation
    propagates through edges with linear decay and edge weight modulation.
    Returns all neurons reached (seeds + fan-out discoveries).

    Logic flow:
    1. Validate fan_out_depth: clamp to [0, MAX_FAN_OUT_DEPTH].
       - depth=0 means no fan-out: return seeds as-is.
    2. Initialize seed neurons:
       - Each RRF candidate becomes a seed with activation=1.0.
       - match_type = "direct_match", hop_distance = 0.
       - Preserve all RRF metadata (rrf_score, bm25_*, vector_*).
    3. If fan_out_depth > 0:
       - Call _bfs_activate() for BFS traversal.
       - Discovered neurons get match_type = "fan_out".
    4. Merge seeds and fan-out results.
       - Seeds retain activation=1.0 even if re-reached via graph.
       - Fan-out neurons get their maximum observed activation.
    5. Return list of dicts:
       {"neuron_id": int, "activation_score": float, "match_type": str,
        "hop_distance": int, "edge_reason": str|None,
        ...preserved RRF metadata for seeds...}

    Args:
        conn: SQLite connection with edges table.
        rrf_candidates: Fused candidates from RRF stage (must have neuron_id, rrf_score).
        fan_out_depth: Max BFS depth (default 1, max 3).
        decay_rate: Linear decay per hop (default 0.3).

    Returns:
        All activated neurons (seeds + fan-out), with activation metadata.
    """
    # --- Validate depth ---
    # fan_out_depth = max(0, min(fan_out_depth, MAX_FAN_OUT_DEPTH))
    fan_out_depth = max(0, min(fan_out_depth, MAX_FAN_OUT_DEPTH))

    # --- Initialize seeds ---
    # seeds = {}
    # for candidate in rrf_candidates:
    #     nid = candidate["neuron_id"]
    #     seeds[nid] = {
    #         **candidate,
    #         "activation_score": 1.0,
    #         "match_type": "direct_match",
    #         "hop_distance": 0,
    #         "edge_reason": None,
    #     }
    seeds = {}
    for candidate in rrf_candidates:
        nid = candidate["neuron_id"]
        seeds[nid] = {
            **candidate,
            "activation_score": 1.0,
            "match_type": "direct_match",
            "hop_distance": 0,
            "edge_reason": None,
        }

    # --- BFS fan-out ---
    # if fan_out_depth == 0:
    #     return list(seeds.values())
    #
    # fan_out = _bfs_activate(conn, seeds, fan_out_depth, decay_rate)
    if fan_out_depth == 0:
        return list(seeds.values())

    # R7: resolve confidence column ONCE per search (not per node / not id(conn)).
    has_confidence = _has_confidence_column(conn)
    fan_out = _bfs_activate(
        conn, seeds, fan_out_depth, decay_rate, has_confidence=has_confidence,
    )

    # --- Merge seeds + fan-out ---
    # For fan-out neurons that are also seeds, seed activation wins.
    # result = dict(seeds)  # seeds take priority
    # for nid, entry in fan_out.items():
    #     if nid not in result:
    #         result[nid] = entry

    # return list(result.values())
    result = dict(seeds)  # seeds take priority
    for nid, entry in fan_out.items():
        if nid not in result:
            result[nid] = entry

    return list(result.values())


def _bfs_activate(
    conn: sqlite3.Connection,
    seeds: Dict[int, Dict[str, Any]],
    max_depth: int,
    decay_rate: float,
    has_confidence: bool = False,
) -> Dict[int, Dict[str, Any]]:
    """Core BFS with linear decay, max-activation-wins, level-batched edges (R7).

    R7: one edge query per BFS depth (O(depth)), not 2 SELECTs per node.
    Visited logic unchanged: re-open a node only when new_activation is strictly
    greater (:245 max-activation-wins). Confidence flag is threaded from
    spread() — never re-PRAGMA here.
    """
    # frontier: neuron_id -> activation at this depth (level-synchronous)
    frontier: Dict[int, float] = {nid: 1.0 for nid in seeds}
    visited: Dict[int, float] = {nid: 1.0 for nid in seeds}
    discovered: Dict[int, Dict[str, Any]] = {}

    for depth in range(max_depth):
        if not frontier:
            break
        # One batched bidirectional edge query for the whole frontier level.
        by_node = _get_neighbors_batch(
            conn, list(frontier.keys()), has_confidence=has_confidence,
        )
        next_frontier: Dict[int, float] = {}

        for current_id, activation in frontier.items():
            for neighbor_id, edge_weight, edge_reason, edge_confidence in by_node.get(
                current_id, ()
            ):
                new_activation = _compute_activation(
                    activation, depth, decay_rate, edge_weight, edge_confidence
                )
                if new_activation <= 0:
                    continue
                if neighbor_id in visited and visited[neighbor_id] >= new_activation:
                    continue

                visited[neighbor_id] = new_activation
                # Keep best activation for this neighbor at the next depth.
                prev = next_frontier.get(neighbor_id)
                if prev is None or new_activation > prev:
                    next_frontier[neighbor_id] = new_activation

                if neighbor_id not in seeds:
                    existing = discovered.get(neighbor_id)
                    if (
                        existing is None
                        or new_activation > existing["activation_score"]
                    ):
                        discovered[neighbor_id] = {
                            "neuron_id": neighbor_id,
                            "activation_score": new_activation,
                            "match_type": "fan_out",
                            "hop_distance": depth + 1,
                            "edge_reason": edge_reason,
                            "rrf_score": 0.0,
                        }

        frontier = next_frontier

    return discovered


def _get_neighbors(
    conn: sqlite3.Connection,
    neuron_id: int,
    has_confidence: bool | None = None,
) -> List[tuple]:
    """Query edges for bidirectional neighbors of a single neuron.

    Thin wrapper over `_get_neighbors_batch` for unit tests / single-node use.
    Prefer batch path inside BFS (R7).

    Returns (neighbor_id, weight, reason, confidence) tuples.
    """
    if has_confidence is None:
        # Unit-test / direct callers: one PRAGMA is fine; BFS never hits this.
        has_confidence = _has_confidence_column(conn)
    by_node = _get_neighbors_batch(conn, [neuron_id], has_confidence=has_confidence)
    return list(by_node.get(neuron_id, ()))


def _get_neighbors_batch(
    conn: sqlite3.Connection,
    neuron_ids: List[int],
    has_confidence: bool,
) -> Dict[int, List[tuple]]:
    """Bidirectional neighbors for many nodes in ONE edge query (R7).

    SELECT ... FROM edges WHERE source_id IN (...) OR target_id IN (...).
    Returns map: node_id -> [(neighbor_id, weight, reason, confidence), ...].
    """
    if not neuron_ids:
        return {}

    conf_expr = "confidence" if has_confidence else "1.0"
    placeholders = ",".join("?" * len(neuron_ids))
    # Two role columns so we can attribute each row to its frontier endpoint(s).
    sql = (
        f"SELECT source_id, target_id, weight, reason, {conf_expr} "
        f"FROM {EDGES_TABLE} "
        f"WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})"
    )
    params = list(neuron_ids) + list(neuron_ids)
    rows = conn.execute(sql, params).fetchall()

    frontier_set = set(neuron_ids)
    out: Dict[int, List[tuple]] = {nid: [] for nid in neuron_ids}
    for source_id, target_id, weight, reason, conf in rows:
        if source_id in frontier_set:
            out[source_id].append((target_id, weight, reason, conf))
        if target_id in frontier_set:
            # Bidirectional: when endpoint is target, neighbor is source.
            # Self-loop would double-add; rare and harmless for activation max.
            out[target_id].append((source_id, weight, reason, conf))
    return out


def _has_confidence_column(conn: sqlite3.Connection) -> bool:
    """Check if the edges table has a confidence column (v005 migration).

    R7: call ONCE per search from spread() and thread the bool into BFS —
    never from the per-level edge batch. Prefer meta.schema_version (≥5) so
    modern DBs need no PRAGMA table_info(edges); table_info only for pre-v5
    / partial schemas. No id(conn) module cache (GC id-reuse flake).
    """
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is not None and row[0] is not None and int(row[0]) >= 5:
            return True
    except (TypeError, ValueError, sqlite3.Error):
        pass
    cols = {row[1] for row in conn.execute("PRAGMA table_info(edges)").fetchall()}
    return "confidence" in cols


def _compute_activation(
    parent_activation: float,
    parent_depth: int,
    decay_rate: float,
    edge_weight: float,
    edge_confidence: float = 1.0,
) -> float:
    """Compute activation for a neighbor using linear decay + edge weight + confidence.

    Formula:
        base = max(0, 1 - (depth + 1) * decay_rate)
        activation = base * edge_weight * edge_confidence

    The confidence multiplier means extracted edges (confidence < 1.0) reduce
    propagated activation compared to authored edges (confidence = 1.0).

    Args:
        parent_activation: Activation of the parent node. Not directly used
            in linear decay (decay is depth-based), but preserved in signature
            for potential future cascading decay variants.
        parent_depth: Depth of the parent node in BFS (0 for seeds).
        decay_rate: Linear decay rate per hop.
        edge_weight: Weight of the connecting edge (0.0 to 1.0).
        edge_confidence: Provenance confidence of the edge (0.0 to 1.0].
            Authored edges = 1.0, extracted edges < 1.0.

    Returns:
        Activation score for the child node (0.0 if fully decayed).
    """
    child_depth = parent_depth + 1
    base_activation = max(0.0, 1.0 - (child_depth + 1) * decay_rate)
    return base_activation * edge_weight * edge_confidence
