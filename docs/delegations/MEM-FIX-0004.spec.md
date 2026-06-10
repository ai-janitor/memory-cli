# MEM-FIX-0004 — child_of edge direction: store inconsistency + migration spec

**Backlog item:** minion bug #69
**Date:** 2026-06-10
**Status:** REAL BUG (data inconsistency) — verdict below

---

## Verdict

`--parent` implementation is CORRECT per docs. The bug is a **legacy data inconsistency in the local emails store** — pre-R64/task-65 neurons were wired child→hub, the post-R64 convention (and docs) specifies hub→child. The 2026-06-10 cleanup agent misread the local store's legacy direction as the convention and filed the wrong report.

---

## 1. Canonical convention (docs + code)

**Source:** `docs/claude-code-integration.md` line 114:
> `memory edge add <HUB> <CHILD> --type child_of` (hub → child)

**Source:** `src/memory_cli/cli/noun_handlers/neuron_noun_handler.py` line 100–105:
```python
# If --parent provided, create edge parent→child (parent owns the relationship).
# [R64/task-65] Direction fix: edge goes from parent to new child, not child to parent.
edge_add(edge_conn, parent_id, new_id, reason=edge_type)
```

**Source:** `tests/cli/test_neuron_add_parent_flag.py` line 91–135 (R64/task-65): asserts `source_id=parent, target_id=child`.

**Source:** `src/memory_cli/traversal/tree_recursive_lineage.py`: `direction="down"` = outgoing edges = hub→child traversal.

**Canonical:** `hub → child` (hub is source, child is target). `tree --direction down` from hub finds children.

---

## 2. Repro (TEMP store, confirmed correct behavior)

```bash
memory init              # /tmp/.memory/memory.db
memory neuron add "HUB test hub" --tags hub        # id=1
memory neuron add "CHILD test child" --parent 1    # id=2
```

Result on LOCAL-2:
```json
"edges": [{"direction": "in", "source": 1, "reason": "child_of"}]
```
Edge stored: `source_id=1(hub), target_id=2(child)` — hub→child. ✓

`memory neuron tree 1 --direction down` → finds child at depth 1. ✓

---

## 3. Blast radius

### 3a. Code paths creating child_of edges

| Path | File | Direction | Status |
|------|------|-----------|--------|
| `--parent` handler | `neuron_noun_handler.py:105` | hub→child ✓ | Correct per R64 |
| `memory edge add <src> <tgt>` | `edge_noun_handler.py:85` | caller-controlled | Correct; docs say `<HUB> <CHILD>` |
| `batch load` graph YAML | `ingestion/consolidation_orchestrator.py` | TBD (see §3c) | Needs check |

### 3b. Traversal assumptions

| Command | Direction | Finds children when |
|---------|-----------|---------------------|
| `tree --direction down` | outgoing | hub→child (canonical) |
| `tree --direction up` | incoming | child→hub (legacy local) |
| `gate show` / neighborhood | both | tolerant — finds either |
| `neuron get` edges field | both | shows both, labelled in/out |

**`gate show` is tolerant** — uses UNION ALL both directions, so hub-listing works regardless of edge direction.

**`tree --direction down` BREAKS on legacy child→hub edges** (returns 0 children from hub).

### 3c. Existing stores — CONFIRMED INCONSISTENCY

**Global store (`~/.memory/`):**
- `GLOBAL-262` PEOPLE HUB: outgoing child_of edges to children → hub→child ✓
- Created post-R64 or by `--parent` handler

**Local store (`emails/.memory/`):**
- `LOCAL-24` BILLING HUB: ALL edges are `direction: "in", source: <child>` → child→hub ✗
- `LOCAL-43` JOB APPLICATIONS HUB: ALL edges are `direction: "in", source: <child>` → child→hub ✗
- `LOCAL-49`, `LOCAL-54` hubs: mixed (LOCAL-52 is outgoing to 49 = child→hub; LOCAL-49 has outgoing to 43 = child→hub)
- Pre-date R64 fix; wired by agents using `edge add <child> <hub>` before the direction fix

**LOCAL-52..55** (added 2026-06-10 by cleanup agent): the agent ran `edge add <child> <hub>` thinking it was "fixing" backwards edges — but actually RE-CREATED the legacy pattern (child→hub), contradicting both docs and `--parent`.

---

## 4. Required changes

### 4a. Data migration — local store (`emails/.memory/`)

All hub→children edges in local store must be flipped from child→hub to hub→child.

**Affected hubs + their children:**

| Hub | Children (source=child in current child→hub edges) |
|-----|-----------------------------------------------------|
| LOCAL-24 | 26, 27, 28, 29, 30, 31, 34 |
| LOCAL-43 | 14, 21, 32, 33, 51, 53 (and any others) |
| LOCAL-49 | 52 (and others with outgoing to 49) |
| LOCAL-54 | 55 (and others) |

**Migration SQL per affected edge:**
```sql
-- For each child→hub edge that should be hub→child:
DELETE FROM edges WHERE source_id = <child> AND target_id = <hub> AND reason = 'child_of';
INSERT INTO edges (source_id, target_id, reason, weight, created_at) 
  VALUES (<hub>, <child>, 'child_of', 1.0, <now>);
```

Or via CLI:
```bash
memory edge remove <child> <hub> --db emails/.memory/memory.db
memory edge add <hub> <child> child_of --db emails/.memory/memory.db
```

**Enumerate all affected edges first:**
```bash
memory neuron list --tag hub  # get all hub IDs
# for each hub, check edges direction:
memory neuron get <hub-id> | jq '[.data.edges[] | select(.direction=="in" and .reason=="child_of")]'
```

### 4b. No code change needed

`--parent` handler (`neuron_noun_handler.py:105`) is correct. No source modification.

`tree_recursive_lineage.py`, `goto_follow_edges_single_hop.py` — no change.

### 4c. Documentation clarification (low priority)

`docs/claude-code-integration.md` line 114 already states the correct convention. No change needed. The CLAUDE.md convention table in `emails/CLAUDE.md` does not document edge direction — no change needed.

---

## 5. Test location + baseline

**Existing tests covering this area:**
- `tests/cli/test_neuron_add_parent_flag.py` — full R64/task-65 coverage
- `tests/traversal/test_tree_lineage.py` — tree traversal with hub→child convention

**Suite baseline:**
```
1826 passed, 824 warnings in 11.35s
```
(Run: `cd /Users/hung/projects/memory-cli && uv run pytest tests/ -q --tb=no`)

No new tests required — this is a data migration, not a code fix. Existing tests already enforce the correct convention and would catch a regression.

---

## 6. Assumptions [?]

- (assumed) `LOCAL-49` hub children count not fully enumerated — ran `neuron get 49` which showed 2 edges; full child count may be higher. Run `neuron tree 49 --direction up` to enumerate legacy children before migration.
- (assumed) No other local hubs beyond 24, 43, 49, 54. Verify with `memory neuron list --tag hub`.
- (assumed) Global store hubs are consistently hub→child — spot-checked GLOBAL-262 only.
- (not verified) `batch load` YAML ingestion edge direction — `consolidation_orchestrator.py` not audited. If it uses `edge add`, caller's argument order determines direction. Low risk for this fix.
