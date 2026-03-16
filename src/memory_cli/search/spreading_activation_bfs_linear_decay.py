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
from collections import deque
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

    fan_out = _bfs_activate(conn, seeds, fan_out_depth, decay_rate)

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
) -> Dict[int, Dict[str, Any]]:
    """Core BFS loop with linear decay and visited tracking.

    Logic flow:
    1. Initialize BFS queue with all seed neuron IDs at depth=0.
    2. Initialize visited set: {neuron_id: max_activation_seen}.
       - Seeds start in visited with activation=1.0.
    3. BFS loop (while queue not empty):
       a. Dequeue (neuron_id, current_depth, current_activation).
       b. If current_depth >= max_depth → skip (don't explore further).
       c. Get neighbors via _get_neighbors(conn, neuron_id).
       d. For each neighbor (neighbor_id, edge_weight, edge_reason):
          i.   Compute new_activation = _compute_activation(
                   current_activation, current_depth, decay_rate, edge_weight)
          ii.  If new_activation <= 0 → skip (decayed to nothing).
          iii. If neighbor_id in visited AND visited[neighbor_id] >= new_activation
               → skip (already reached with equal or higher activation).
          iv.  Update visited[neighbor_id] = new_activation.
          v.   Enqueue (neighbor_id, current_depth + 1, new_activation).
          vi.  Record neighbor with activation metadata.
    4. Return all discovered non-seed neurons with their max activation.

    Args:
        conn: SQLite connection.
        seeds: Seed neurons dict keyed by neuron_id.
        max_depth: Maximum BFS depth.
        decay_rate: Linear decay rate per hop.

    Returns:
        Dict of discovered fan-out neurons keyed by neuron_id.
    """
    # --- Initialize BFS ---
    # queue = deque()
    # visited: Dict[int, float] = {}
    # discovered: Dict[int, Dict[str, Any]] = {}

    # for nid in seeds:
    #     queue.append((nid, 0, 1.0))
    #     visited[nid] = 1.0
    queue = deque()
    visited: Dict[int, float] = {}
    discovered: Dict[int, Dict[str, Any]] = {}

    for nid in seeds:
        queue.append((nid, 0, 1.0))
        visited[nid] = 1.0

    # --- BFS loop ---
    # while queue:
    #     current_id, depth, activation = queue.popleft()
    #
    #     if depth >= max_depth:
    #         continue
    #
    #     neighbors = _get_neighbors(conn, current_id)
    #     for neighbor_id, edge_weight, edge_reason, edge_confidence in neighbors:
    #         new_activation = _compute_activation(
    #             activation, depth, decay_rate, edge_weight, edge_confidence
    #         )
    #         if new_activation <= 0:
    #             continue
    #         if neighbor_id in visited and visited[neighbor_id] >= new_activation:
    #             continue
    #
    #         visited[neighbor_id] = new_activation
    #         queue.append((neighbor_id, depth + 1, new_activation))
    #
    #         # Only record non-seed discoveries
    #         if neighbor_id not in seeds:
    #             discovered[neighbor_id] = {
    #                 "neuron_id": neighbor_id,
    #                 "activation_score": new_activation,
    #                 "match_type": "fan_out",
    #                 "hop_distance": depth + 1,
    #                 "edge_reason": edge_reason,
    #                 "rrf_score": 0.0,  # fan-out neurons have no direct RRF score
    #             }

    # return discovered
    while queue:
        current_id, depth, activation = queue.popleft()

        if depth >= max_depth:
            continue

        neighbors = _get_neighbors(conn, current_id)
        for neighbor_id, edge_weight, edge_reason, edge_confidence in neighbors:
            new_activation = _compute_activation(
                activation, depth, decay_rate, edge_weight, edge_confidence
            )
            if new_activation <= 0:
                continue
            if neighbor_id in visited and visited[neighbor_id] >= new_activation:
                continue

            visited[neighbor_id] = new_activation
            queue.append((neighbor_id, depth + 1, new_activation))

            # Only record non-seed discoveries
            if neighbor_id not in seeds:
                discovered[neighbor_id] = {
                    "neuron_id": neighbor_id,
                    "activation_score": new_activation,
                    "match_type": "fan_out",
                    "hop_distance": depth + 1,
                    "edge_reason": edge_reason,
                    "rrf_score": 0.0,  # fan-out neurons have no direct RRF score
                }

    return discovered


def _get_neighbors(
    conn: sqlite3.Connection,
    neuron_id: int,
) -> List[tuple]:
    """Query edges for bidirectional neighbors of a neuron.

    Bidirectional means we traverse edges regardless of direction:
    - Edges WHERE source_id = neuron_id → target_id is a neighbor.
    - Edges WHERE target_id = neuron_id → source_id is a neighbor.

    Returns (neighbor_id, weight, reason, confidence) tuples. The confidence
    field enables provenance-weighted spreading activation — extracted edges
    (confidence < 1.0) decay activation faster than authored edges (1.0).

    Args:
        conn: SQLite connection.
        neuron_id: The neuron to find neighbors for.

    Returns:
        List of (neighbor_id, weight, reason, confidence) tuples.
    """
    # --- Detect if confidence column exists (provenance v004 migration) ---
    has_confidence = _has_confidence_column(conn)

    if has_confidence:
        conf_expr = "confidence"
    else:
        conf_expr = "1.0"

    # --- Outgoing edges ---
    outgoing = conn.execute(
        f"SELECT target_id, weight, reason, {conf_expr} FROM {EDGES_TABLE} "
        f"WHERE source_id = ?",
        (neuron_id,),
    ).fetchall()

    # --- Incoming edges ---
    incoming = conn.execute(
        f"SELECT source_id, weight, reason, {conf_expr} FROM {EDGES_TABLE} "
        f"WHERE target_id = ?",
        (neuron_id,),
    ).fetchall()

    # --- Combine ---
    # Returns (neighbor_id, weight, reason, confidence) tuples.
    return [(row[0], row[1], row[2], row[3]) for row in outgoing + incoming]


# Cache for column existence check per connection id
_confidence_column_cache: Dict[int, bool] = {}


def _has_confidence_column(conn: sqlite3.Connection) -> bool:
    """Check if the edges table has a confidence column (v004 migration).

    Result is cached per connection to avoid repeated PRAGMA queries.
    """
    conn_id = id(conn)
    if conn_id not in _confidence_column_cache:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(edges)").fetchall()}
        _confidence_column_cache[conn_id] = "confidence" in cols
    return _confidence_column_cache[conn_id]


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
