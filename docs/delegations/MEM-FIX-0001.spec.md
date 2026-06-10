# MEM-FIX-0001 — `_run_retrieval_stage` bare `load_config()` ignores `--global`

Mode: maintain-operate BUG FIX. Backlog: memory-cli #67.

---

## 1. REPRO — deterministic red test

**Setup** (fresh temp store, no symlinks, no emails/.memory involved):

```bash
# 1. Create isolated temp project with a LOCAL store pointing at a missing model
TMPDIR=$(mktemp -d)
mkdir -p "$TMPDIR/proj/.memory/models"
cat > "$TMPDIR/proj/.memory/config.json" <<'EOF'
{
  "db_path": "/tmp/__throwaway_repro_local.db",
  "embedding": {
    "model_path": "/nonexistent/path/bad.gguf",
    "dimensions": 768
  }
}
EOF

# 2. Run --global search FROM that project dir
cd "$TMPDIR/proj"
memory neuron search "billing" --global --json | jq '.meta'
```

**Observed** (current behavior):
```json
{
  "vector_unavailable": true,
  "total": 0
}
```
`FileNotFoundError: Embedding model not found: /nonexistent/path/bad.gguf` is swallowed;
ancestor walk picks the LOCAL config despite `--global`.

**Expected**:
```json
{
  "vector_unavailable": false,
  "total": <N>
}
```
`~/.memory/config.json` is used; global model `~/.memory/models/default.gguf` (146 MB, verified present) loads fine.

**Path-checked evidence**:
- Bug line: `src/memory_cli/search/light_search_pipeline_orchestrator.py:282-284` (verified — `from memory_cli.config import load_config` / `config = load_config()` with no args)
- `load_config()` calls `resolve_config_path()` which does ancestor walk from `Path.cwd()` → finds LOCAL `.memory/config.json` first (`config_path_resolution_ancestor_walk.py:96-98`)
- Canonical `--global` resolution in `db_connection_from_global_flags.py:47-50`: when `global_only=True`, forces `config_override = str(_global_config_path())` BEFORE calling `load_config(config_override=...)`

---

## 2. BLAST-RADIUS

### All `load_config()` consumers in `src/`

| File | Lines | Role | Bug here? |
|------|-------|------|-----------|
| `search/light_search_pipeline_orchestrator.py` | 282-284 | embedding config in retrieval stage | **YES — this fix** |
| `neuron/neuron_add_with_autotags_and_embed.py` | 342-345 | embed on `neuron add` | Same pattern; called from add-verb which already has a resolved connection — bug exists but only fires if neuron_add is called from a project dir w/missing local model; out of scope for this ticket |
| `ingestion/haiku_extraction_entities_facts_rels.py` | 416-417 | Haiku API key env var name | Bare `load_config()` but no model path used; low severity, no --global impact |
| `cli/noun_handlers/db_connection_from_global_flags.py` | 50, 106 | connection setup | CORRECT — already passes `config_override` / honors `--global` |
| `config/config_loader_and_validator.py` | 62 | definition only | n/a |

### `_run_retrieval_stage` callers

| Call site | File | Line | Note |
|-----------|------|------|------|
| `light_search()` | `light_search_pipeline_orchestrator.py` | 219 | sole caller |

`light_search()` is called from:
- `neuron_noun_handler.py:428` — inside a `for conn, scope in connections` loop; `conn` already points at the right store (local or global), but `config` is never passed into `light_search`
- `heavy_search_orchestrator.py:135, 228, 335` — same pattern; delegates conn but no config forwarding
- `search/__init__.py:31` — re-export only

### Canonical store-resolution path (must-not-regress behaviors)

`db_connection_from_global_flags.get_connection_and_config()` → `get_layered_connections()`:
1. `--global` → `config_override = str(_global_config_path())` → `load_config(config_override=...)` → global config wins
2. Layered (default) → `resolve_all_config_paths()` → LOCAL first, then GLOBAL; each opened via `_open_config_path(config_path, ...)`
3. `--config`/`--db` explicit → single-connection path

Tests that must stay green:
- `tests/cli/test_layered_search_local_and_global.py` — layered store behavior
- `tests/search/test_light_search_pipeline.py` — all 10 pipeline stages
- `tests/config/` — all config resolution tests

---

## 3. SPEC — frozen fix

### What to change

**File:** `src/memory_cli/search/light_search_pipeline_orchestrator.py`

**Approach:** Pass the already-resolved `MemoryConfig` into `_run_retrieval_stage` from `light_search()`. The caller (`neuron_noun_handler.py`) already has a resolved `conn` from `get_layered_connections`; we need the matching `config` threaded through to the pipeline.

**Step 1 — `light_search` signature:** add `config` parameter.

Current (line 143):
```python
def light_search(conn: sqlite3.Connection, options: SearchOptions) -> SearchResultEnvelope:
```
New:
```python
def light_search(
    conn: sqlite3.Connection,
    options: SearchOptions,
    config: Optional["MemoryConfig"] = None,
) -> SearchResultEnvelope:
```
- `Optional` import already present. `MemoryConfig` is a string forward reference (avoids circular import; same pattern used elsewhere) OR import at top of file from `memory_cli.config`.

**Step 2 — thread config to retrieval stage.** In `light_search()` at line 219:
```python
# current
_run_retrieval_stage(conn, state, options)
# new
_run_retrieval_stage(conn, state, options, config=config)
```

**Step 3 — `_run_retrieval_stage` signature:** add `config` parameter.

Current (line 254-258):
```python
def _run_retrieval_stage(
    conn: sqlite3.Connection,
    state: PipelineState,
    options: SearchOptions,
) -> None:
```
New:
```python
def _run_retrieval_stage(
    conn: sqlite3.Connection,
    state: PipelineState,
    options: SearchOptions,
    config: Optional["MemoryConfig"] = None,
) -> None:
```

**Step 4 — use passed config, fall back to bare load only when not provided.**

Current (lines 282-284):
```python
from memory_cli.config import load_config
config = load_config()
model = get_model(config)
```
New:
```python
if config is None:
    from memory_cli.config import load_config
    config = load_config()
model = get_model(config)
```

**Step 5 — update `neuron_noun_handler.py` caller** (line ~421-428): use `get_connection_and_config` instead of (or in addition to) extracting `conn` from `get_layered_connections`; pass `config` into `light_search`.

Current pattern:
```python
connections = get_layered_connections(global_flags)
...
for conn, scope in connections:
    options = SearchOptions(query=query, limit=limit)
    envelope = light_search(conn, options)
```
New pattern: `get_layered_connections` needs to yield `(conn, config, scope)` OR we open connections separately. Simplest non-breaking fix: add a variant `get_layered_connections_with_config()` or change the tuple to 3-element `(conn, config, scope)`.

**Preferred (least disruption):** change `get_layered_connections` return type from `List[Tuple[conn, str]]` to `List[Tuple[conn, MemoryConfig, str]]`. Update `_open_config_path` to return `(conn, config, scope)`. Update all callers of `get_layered_connections` (only `neuron_noun_handler.py` uses the tuple form).

Files changed:
1. `src/memory_cli/search/light_search_pipeline_orchestrator.py` — lines 143, 219, 254-258, 282-284
2. `src/memory_cli/cli/noun_handlers/db_connection_from_global_flags.py` — `get_layered_connections`, `_open_config_path` return types + internals
3. `src/memory_cli/cli/noun_handlers/neuron_noun_handler.py` — unpack `config` from tuple, pass to `light_search`
4. `src/memory_cli/search/__init__.py` — update re-exported signature if needed

### New regression test

**File:** `tests/search/test_light_search_pipeline.py` (append to `TestLightSearchBM25OnlyFallback`)

**Test name:** `test_global_config_used_when_passed_explicitly`

**What it checks:**
1. Create two `MemoryConfig` objects: `bad_config` (model_path = nonexistent), `good_config` (model_path = present or mocked).
2. Call `light_search(conn, options, config=bad_config)` — patch `get_model` to raise `FileNotFoundError` when given `bad_config`, succeed when given `good_config`.
3. Call `light_search(conn, options, config=good_config)` — assert `vector_unavailable` is `False`.
4. Assert: when `config=bad_config` is passed, `vector_unavailable=True`; when `config=good_config`, `vector_unavailable=False`. Proves config is threaded, not re-resolved.

Alt simpler form (mock `load_config`): confirm `load_config` is NOT called when `config` is passed in.

```python
def test_global_config_used_when_passed_explicitly(self, search_db):
    """When config is passed to light_search, bare load_config() must NOT be called.

    Proves the retrieval stage uses the caller-resolved config, not ancestor-walk.
    """
    conn, nids = search_db
    options = SearchOptions(query="python", fan_out_depth=0)
    sentinel_config = object()  # not a real config — proves it's passed through

    call_log = []

    def mock_get_model(cfg):
        call_log.append(cfg)
        raise FileNotFoundError("no model in test")

    with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
               side_effect=mock_get_model), \
         patch("memory_cli.search.light_search_pipeline_orchestrator.load_config") as mock_lc:
        # When config provided, load_config must not be invoked
        # (mock_lc would raise if called, providing a secondary assertion)
        mock_lc.side_effect = AssertionError("load_config called despite config arg")
        envelope = light_search(conn, options, config=sentinel_config)

    assert envelope.vector_unavailable is True  # FileNotFoundError still sets flag
    assert call_log == [sentinel_config]         # get_model received the passed config
    assert not mock_lc.called                    # load_config never invoked
```

### Suite command + baseline

```bash
cd /Users/hung/projects/memory-cli && uv run pytest tests/ -q --tb=no
```

**Baseline (captured 2026-06-10):** `1826 passed, 824 warnings in 12.65s`

Post-fix suite count MUST be `>= 1827` (baseline + the new regression test, minimum).

---

## 4. ASSUMPTIONS [?]

- [?] `get_layered_connections` return-type change (add `config` to tuple) is the lowest-touch path — no new function, no signature duplication. Doer must verify no other caller of `get_layered_connections` unpacks the tuple and would break (grep: only `neuron_noun_handler.py:421` and no other site found at time of spec).
- [?] Heavy search orchestrator (`heavy_search_orchestrator.py:135, 228, 335`) calls `light_search(conn, options)` without config — leaving `config=None` default preserves current behavior (bare `load_config()` fallback). That's acceptable for this ticket; a follow-up ticket can thread config there too.
- [?] `neuron_add_with_autotags_and_embed.py:345` has the same bare `load_config()` pattern — out of scope for MEM-FIX-0001; filed separately (not a `--global` routing issue; neuron add always targets a specific store).
- [?] `Optional["MemoryConfig"]` used as forward ref to avoid a circular import at module level; if `MemoryConfig` is already imported at top of orchestrator file, use direct type instead.
- [?] The `load_config` import inside the try-block (line 282) was lazy for a reason (not stated in comments). Moving it to a conditional branch preserves the lazy pattern — no top-level import added.
