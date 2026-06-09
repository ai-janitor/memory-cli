# MEM-FEAT-0001 — recursive tree/lineage verb (`memory neuron tree`)

Mode: maintain-operate FEATURE (additive verb on existing layers). Backlog: memory-cli #64.

## The red test (acceptance — already written, currently RED)
`tests/traversal/test_tree_lineage.py` — 5 cases, fails now with
`ModuleNotFoundError: memory_cli.traversal.tree_recursive_lineage`. Make them GREEN:
- `test_tree_down_nests_descendants` — root → children → grandchild nested; each node has `depth`
- `test_tree_depth_bound` — `depth=1` stops at immediate children (grandchild not expanded)
- `test_tree_edge_type_filter` — only edges whose `reason == edge_type` are followed
- `test_tree_up_nests_ancestors` — `direction="up"` walks toward parents
- `test_tree_cycle_safe` — a back-edge must terminate (visited set), no RecursionError

## Contract (the function the test imports)
`src/memory_cli/traversal/tree_recursive_lineage.py`:
```python
def tree_lineage(conn, root_id, direction="down", depth=10, edge_type=None) -> dict
```
Returns nested: `{"id": int, "content": str, "depth": int, "children": [ <same shape> ]}`.
- `direction`: `"down"` = follow edges where node is the **source** (descendants);
  `"up"` = where node is the **target** (ancestors); `"both"` = union (de-duped).
  (Edge convention: `neuron add --parent P` makes edge source=P, target=child, reason=child_of.)
- `depth`: max levels below root. `depth=1` = root + one level. `depth=0` = root only.
- `edge_type`: if set, only follow edges with `reason == edge_type`; if None, follow all.
- cycle-safe: maintain a `visited` set of neuron ids; never expand a node twice.

## Design constraints (reuse, don't reinvent)
- **Recurse the existing single-hop primitive** `traversal/goto_follow_edges_single_hop.py:goto_follow_edges(conn, neuron_id, direction)` (direction values `outgoing`/`incoming`/`both`) for each hop — map tree `down→outgoing`, `up→incoming`, `both→both`. Filter its `results[].edge.reason` by `edge_type`. Each result exposes `result["neuron"]["id"]` + `["content"]` to recurse on. (If goto's pagination default limit truncates children, pass a high/unbounded limit — see assumption A4.)
- Use `neuron_get`/goto hydration for `content`; do not hand-roll SQL if a primitive exists.
- Export `tree_lineage` from `src/memory_cli/traversal/__init__.py`.

## CLI verb wiring (`memory neuron tree <id>`)
`src/memory_cli/cli/noun_handlers/neuron_noun_handler.py`:
- add `handle_tree(args, global_flags)` → parse positional id + `--direction --depth --type`,
  call `tree_lineage`, return `Result(status="ok", data=<tree>, meta={...})`.
- register in `_VERB_MAP`, `_VERB_DESCRIPTIONS`, `_FLAG_DEFS` (mirror `goto`'s intended flags;
  see `goto_follow_edges` docstring `CLI: memory neuron goto ...`).
- LookupError on missing root → map to the same exit-1 convention other verbs use.

## Blast radius (must-not-regress)
ADDITIVE only — new module + new verb + one export line. Does NOT modify `edge_list`,
`neuron_get`, `goto_follow_edges`, or the dispatch core. Regression anchor:
- baseline: full suite **GREEN 1821 passed** (captured 2026-06-09 via `make test`).
- must stay green, esp: `tests/traversal/`, `tests/neuron/`, `tests/edge/`, dispatch/help tests.
- post-suite count MUST be `>= 1821 + new tests` (the 5 acceptance + any unit tests you add).

## §05 Requirements ledger (append-only)
- REQ-1 [H] recursive descendants/ancestors as a nested tree from one call.
- REQ-2 [H] depth-bounded (default 10).
- REQ-3 [H] edge-type filter (optional).
- REQ-4 [H] cycle-safe (visited set).
- REQ-5 [H] CLI verb `memory neuron tree <id>` returning the house `Result` envelope.
- INV-1 (upheld) no schema change; additive only.
- INV-2 (upheld) traversal is read-only, no embeddings/LLM (per traversal/__init__ doctrine).

## §05 Assumption sweep — ratify or doer must return as [?]
- A1 [?] core lives in `traversal/` (beside goto/timeline), NOT `neuron/`. (chosen: matches the layer)
- A2 [?] function name `tree_lineage`, module `tree_recursive_lineage.py` (the test imports these — fixed).
- A3 [?] default `direction="down"`, `depth=10`, `edge_type=None`.
- A4 [?] when recursing goto per hop, pass a large limit (e.g. 10_000) so children aren't paginated-out — confirm goto accepts it; if not, fetch all via edge layer.
- A5 [?] `both` direction de-dupes by neuron id across up+down at the same node.
- A6 [?] CLI flag is `--type` for edge_type (consistent with `edge list --type`).
- Doer: return ANY additional baked-in constant/default as a new [?] row.

## Done = 
red test GREEN · full suite GREEN (count ≥ baseline+new) · verb callable `memory neuron tree <id>` ·
every code-baked default has a [?]/ratified row · CHANGELOG row appended.
