# MEM-FIX-0002 — capture vector_unavailable_reason in search meta

Mode: maintain-operate BUGFIX (additive field, no behavior change). Backlog: memory-cli #68.

**SEQUENCING CONSTRAINT:** same file as MEM-FIX-0001 (lines 282-284). MEM-FIX-0001 touches
`_run_retrieval_stage` at lines 282-284; this fix touches lines 287-289. Both are in
`light_search_pipeline_orchestrator.py`. Implement MEM-FIX-0002 AFTER MEM-FIX-0001 is merged.
Merge order: 0001 first → rebase 0002 branch on top → no conflicts (distinct line ranges).

---

## 1. REPRO — red test

### Command

```bash
cd /Users/hung/projects/memory-cli
uv run python - <<'EOF'
import sqlite3
from unittest.mock import patch
from memory_cli.search.light_search_pipeline_orchestrator import light_search, SearchOptions
from memory_cli.db.connection_setup_wal_fk_busy import open_connection
from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as v001
from memory_cli.db.migrations.v004_add_access_tracking import apply as v004
import json

conn = open_connection(":memory:")
load_and_verify_extensions(conn)
conn.execute("BEGIN"); v001(conn); conn.execute("COMMIT")
conn.execute("BEGIN"); v004(conn); conn.execute("COMMIT")

with patch(
    "memory_cli.search.light_search_pipeline_orchestrator.get_model",
    side_effect=FileNotFoundError("Embedding model not found: /path/to/missing.gguf"),
):
    env = light_search(conn, SearchOptions(query="test"))

# Show what meta carries today
import json
print("vector_unavailable:", env.vector_unavailable)
print("vector_unavailable_reason attr exists:", hasattr(env, "vector_unavailable_reason"))
EOF
```

### Current (red) output

```
vector_unavailable: True
vector_unavailable_reason attr exists: False
```

`meta` exposed to the CLI caller (`neuron_noun_handler.py:447`) includes `vector_unavailable: true`
with NO reason field. Root cause is invisible.

### Expected (green) output

```
vector_unavailable: True
vector_unavailable_reason: "FileNotFoundError: Embedding model not found: /path/to/missing.gguf"
```

---

## 2. BLAST-RADIUS

### All sites that read `vector_unavailable` or construct/consume the search envelope

| File | Line(s) | What it does | Breaking? |
|------|---------|--------------|-----------|
| `src/memory_cli/search/light_search_pipeline_orchestrator.py` | 89, 139, 249, 289, 295, 384, 410 | defines `PipelineState.vector_unavailable`, `SearchResultEnvelope.vector_unavailable`; sets/reads flag | **CHANGE HERE** (additive field only) |
| `src/memory_cli/search/search_result_hydration_and_envelope.py` | 279, 335 | `build_envelope()` param + output `metadata.vector_unavailable` | needs `vector_unavailable_reason` param added |
| `src/memory_cli/search/explain_scoring_breakdown.py` | 29, 54, 121 | propagates `vector_unavailable` bool into per-result breakdown | no change needed (bool still flows) |
| `src/memory_cli/cli/noun_handlers/neuron_noun_handler.py` | 424, 434-435, 447 | collects `vector_unavailable` across layered stores, emits to `meta` dict | needs to also collect + forward reason |
| `tests/search/test_light_search_pipeline.py` | 237, 246 | asserts `envelope.vector_unavailable is True` | non-breaking (field is not removed) |
| `tests/search/test_search_result_hydration.py` | 305-308 | asserts `metadata["vector_unavailable"] is True` | non-breaking |
| `tests/search/test_explain_breakdown.py` | 193-210 | asserts `breakdown["vector_unavailable"]` bool | non-breaking |
| `tests/search/heavy/test_heavy_search_orchestrator.py` | 82, 97 | `vector_unavailable: bool = False` in mock dataclass | non-breaking |

### Strict-schema assertions that would break

None found. All test assertions use `is True` / `is False` on the **existing bool** — they do not assert that no OTHER fields exist. Adding `vector_unavailable_reason` is purely additive.

### Must-not-regress behaviors

1. `envelope.vector_unavailable is True` when model missing (existing tests)
2. BM25-only fallback still returns results (existing tests)
3. `metadata["vector_unavailable"]` still present in JSON envelope (existing test)
4. `explain` breakdowns still carry `vector_unavailable` bool (existing tests)
5. `exit_code == 1` on no results, `== 2` on DB error (existing tests)
6. When embedding succeeds: `vector_unavailable is False`, `vector_unavailable_reason` is `None` (new regression)

---

## 3. SPEC — exact change

### 3a. `PipelineState` dataclass — add reason field

**File:** `src/memory_cli/search/light_search_pipeline_orchestrator.py`
**Lines:** 81-122 (class body)

Add after line 89 (`vector_unavailable: bool = False`):

```python
vector_unavailable_reason: Optional[str] = None
```

### 3b. `_run_retrieval_stage` — capture exception

**File:** `src/memory_cli/search/light_search_pipeline_orchestrator.py`
**Lines:** 287-289 (the bare except)

Change from:
```python
    except Exception:
        # Embedding unavailable — BM25-only fallback
        state.vector_unavailable = True
```

Change to:
```python
    except Exception as exc:
        # Embedding unavailable — BM25-only fallback
        state.vector_unavailable = True
        state.vector_unavailable_reason = f"{type(exc).__name__}: {exc}"
```

### 3c. `SearchResultEnvelope` dataclass — add reason field

**File:** `src/memory_cli/search/light_search_pipeline_orchestrator.py`
**Lines:** 129-141 (class body)

Add after line 139 (`vector_unavailable: bool = False`):

```python
vector_unavailable_reason: Optional[str] = None
```

### 3d. Propagate reason to envelope — two call sites

**File:** `src/memory_cli/search/light_search_pipeline_orchestrator.py`

**Site 1** — `_run_output_stage` return (line ~410):
```python
return SearchResultEnvelope(
    results=state.results,
    total_before_pagination=total,
    limit=options.limit,
    offset=options.offset,
    vector_unavailable=state.vector_unavailable,
    vector_unavailable_reason=state.vector_unavailable_reason,   # ADD
    exit_code=0 if state.results else 1,
)
```

**Site 2** — outer except fallback (line ~244):
```python
return SearchResultEnvelope(
    results=[],
    total_before_pagination=0,
    limit=options.limit,
    offset=options.offset,
    vector_unavailable=state.vector_unavailable,
    vector_unavailable_reason=state.vector_unavailable_reason,   # ADD
    exit_code=2,
)
```

### 3e. `build_envelope()` — thread reason into metadata JSON

**File:** `src/memory_cli/search/search_result_hydration_and_envelope.py`
**Line ~279:** add param

```python
def build_envelope(
    results: List[Dict[str, Any]],
    total_before_pagination: int,
    limit: int,
    offset: int,
    vector_unavailable: bool = False,
    vector_unavailable_reason: Optional[str] = None,   # ADD
) -> Dict[str, Any]:
```

In the return dict (line ~335), under `"metadata"`:
```python
"metadata": {
    "vector_unavailable": vector_unavailable,
    "vector_unavailable_reason": vector_unavailable_reason,   # ADD
    "result_count": len(results),
},
```

Also update the two `build_envelope(...)` call sites in `_run_output_stage` (line ~384):
```python
envelope_dict = build_envelope(
    state.results,
    total,
    options.limit,
    options.offset,
    vector_unavailable=state.vector_unavailable,
    vector_unavailable_reason=state.vector_unavailable_reason,   # ADD
)
```

### 3f. `neuron_noun_handler.py` — forward reason to CLI meta

**File:** `src/memory_cli/cli/noun_handlers/neuron_noun_handler.py`
**Line ~424:** add alongside `vector_unavailable = False`:

```python
vector_unavailable = False
vector_unavailable_reason: Optional[str] = None   # ADD
```

**Line ~434:** in the loop body, update reason when unavailable:
```python
if envelope.vector_unavailable:
    vector_unavailable = True
    if envelope.vector_unavailable_reason and vector_unavailable_reason is None:
        vector_unavailable_reason = envelope.vector_unavailable_reason   # ADD (first reason wins)
```

**Line ~447:** in the returned `meta` dict:
```python
meta={
    "query": query,
    "total": total,
    "vector_unavailable": vector_unavailable,
    "vector_unavailable_reason": vector_unavailable_reason,   # ADD
},
```

### 3g. New regression test location

**File:** `tests/search/test_light_search_pipeline.py`
**Class:** `TestLightSearchBM25OnlyFallback` (already exists — append new test)

```python
def test_bm25_only_sets_vector_unavailable_reason(self, search_db):
    """Verify envelope carries the exception class+message in vector_unavailable_reason
    when the embedding model is missing (FileNotFoundError).

    RED before fix: envelope has no vector_unavailable_reason attr (or it is None).
    GREEN after fix: envelope.vector_unavailable_reason == "FileNotFoundError: Model not available"
    """
    conn, nids = search_db
    options = SearchOptions(query="python", fan_out_depth=0)
    with patch(
        "memory_cli.search.light_search_pipeline_orchestrator.get_model",
        side_effect=FileNotFoundError("Model not available"),
    ):
        envelope = light_search(conn, options)
    assert envelope.vector_unavailable is True
    assert envelope.vector_unavailable_reason == "FileNotFoundError: Model not available"
```

Add a second test for the happy-path (reason is None when vectors work):

```python
def test_reason_none_when_vectors_available(self, search_db):
    """Verify vector_unavailable_reason is None when embedding succeeds."""
    conn, nids = search_db
    options = SearchOptions(query="python", fan_out_depth=0)
    # No patch — let embedding fail naturally (model likely absent in CI);
    # but if vector_unavailable is False the reason must be None.
    envelope = light_search(conn, options)
    if not envelope.vector_unavailable:
        assert envelope.vector_unavailable_reason is None
```

Also add a test to `tests/search/test_search_result_hydration.py`, class `TestEnvelopeStructure`:

```python
def test_metadata_has_vector_unavailable_reason(self):
    """Verify metadata carries reason string when provided."""
    env = build_envelope([], 0, 20, 0,
                         vector_unavailable=True,
                         vector_unavailable_reason="FileNotFoundError: missing.gguf")
    assert env["metadata"]["vector_unavailable_reason"] == "FileNotFoundError: missing.gguf"

def test_metadata_reason_none_when_not_set(self):
    """Verify metadata reason is None when not provided."""
    env = build_envelope([], 0, 20, 0, vector_unavailable=False)
    assert env["metadata"]["vector_unavailable_reason"] is None
```

### 3h. Suite command + baseline

```bash
cd /Users/hung/projects/memory-cli && uv run pytest tests/ -q --tb=short
```

Baseline: **1826 passed** (run 2026-06-10). After fix: expect 1826 + new tests (≥4) all green.

---

## 4. ASSUMPTIONS [?]

- **[?] Reason string format:** `f"{type(exc).__name__}: {exc}"` — matches the live-log example
  (`"FileNotFoundError: Embedding model not found: /path/to/file"`). No truncation. (assumed)
- **[?] Truncation:** no max-length enforced. Exception messages in practice are short (~100 chars).
  If a future exception has a huge message, the first sentence is still diagnostic. (assumed — add
  truncation in a follow-up if needed)
- **[?] First-reason-wins for layered stores:** `neuron_noun_handler` loops over multiple store
  connections; only the first non-None reason is captured. All stores share the same model config
  path, so reasons will be identical anyway. (assumed)
- **[?] `Optional[str]` import:** `Optional` already imported in orchestrator (line 31); also
  needed in `neuron_noun_handler.py` — verify import exists before adding annotation, or use
  `str | None` (Python 3.10+ syntax — check pyproject.toml `requires-python`). (assumed — use
  `Optional[str]` to match existing style)
- **[?] `build_envelope` call sites:** the spec identifies two call sites in `_run_output_stage`
  (line ~384) and the outer `SearchResultEnvelope(...)` at line ~410. A third call at line ~249
  is the error-path `SearchResultEnvelope(...)` (not `build_envelope`). All three are covered
  in 3d above. (verified by grep)
