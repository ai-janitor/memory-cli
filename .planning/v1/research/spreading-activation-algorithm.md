# Spreading Activation Algorithm Design

## Recommendation: Application-side BFS, not SQL recursive CTEs

### Why not recursive CTEs
- SQLite UNION in CTEs can't properly deduplicate nodes reached via different paths
- No way to maintain a proper visited set inside the CTE
- SQLite recursive CTEs cannot do aggregates (MAX) during recursion
- The `path NOT LIKE` hack is O(n) string scan per row

### Algorithm (Python BFS with linear decay)

```python
def spread_activation(db, seed_ids, decay_rate=0.25, max_depth=1):
    activated = {}  # neuron_id -> best_activation_score
    visited = set()
    queue = deque()

    for nid in seed_ids:
        activated[nid] = 1.0
        queue.append((nid, 0))
        visited.add(nid)

    while queue:
        node_id, depth = queue.popleft()
        if depth >= max_depth:
            continue

        next_activation = max(0.0, 1.0 - (depth + 1) * decay_rate)
        if next_activation <= 0:
            continue

        # Batch: get all neighbors for current node
        neighbors = db.execute(
            "SELECT target_id FROM edges WHERE source_id = ?",
            (node_id,)
        ).fetchall()

        for (neighbor_id,) in neighbors:
            if neighbor_id in visited:
                activated[neighbor_id] = max(
                    activated.get(neighbor_id, 0), next_activation
                )
                continue
            visited.add(neighbor_id)
            activated[neighbor_id] = next_activation
            queue.append((neighbor_id, depth + 1))

    return activated
```

### Decay Function
Linear: `activation = max(0, 1.0 - hop * decay_rate)` with default decay_rate=0.25
- Hop 0: 1.00 (seed)
- Hop 1: 0.75
- Hop 2: 0.50
- Hop 3: 0.25
- Hop 4: 0.00 (natural cutoff)

### Score Combination
Use **max** for re-visited nodes. Closest meaningful connection wins.

### Performance
- Depth 1 (default): S+1 queries for S seed nodes. Trivial even at 100K nodes.
- Depth 3: Use batch queries per depth level to keep SQL round-trips to max_depth + 1.
- Index requirements: `CREATE INDEX idx_edges_source ON edges(source_id)` (essential)

### Optimization: Batch neighbor queries
```python
placeholders = ','.join('?' * len(current_level))
neighbors = db.execute(
    f"SELECT source_id, target_id FROM edges WHERE source_id IN ({placeholders})",
    current_level
).fetchall()
```

### Edge Schema Needs
- `source_id, target_id, reason, weight (default 1.0), created_at`
- Index on source_id, index on target_id
- Weight column lets edges modulate activation: activation * edge_weight

### Bidirectional Traversal
Store edges in both directions OR query `WHERE source_id = ? OR target_id = ?` (both columns indexed).

### Optional Enhancements
- Activation threshold (e.g., 0.1) to drop noise at deep hops
- Fan-out limit per node (--max-neighbors) to prevent hub domination
- Edge weight modulation: `next_activation * edge_weight`
