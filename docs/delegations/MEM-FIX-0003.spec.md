# MEM-FIX-0003 — Central model resolution (`~/.memory/models/` wins, per-store deprecated)

Mode: maintain-operate FEATURE. Backlog: memory-cli #66.
Overlaps shared files with MEM-FIX-0001/0002 (search pipeline orchestrator); sequence after those or coordinate on `light_search_pipeline_orchestrator.py`.

---

## 1. Acceptance test (RED now)

**Scenario:** fresh local store, no `models/` dir, config written by `memory init` (bakes
`embedding.model_path = <store>/models/default.gguf`), global `~/.memory/models/default.gguf`
exists — vector search must embed (not fall through to BM25-only).

**Failing-now evidence** (from `/Users/hung/emails/docs/memory-cleanup/log-vector-search.md`):

```
# from ~/emails (local store, empty models/):
$ memory neuron search "billing" | jq '.meta'
{
  "vector_unavailable": true,   # ← FAIL — should be false
  "total": 0
}

# root cause trace:
#   config.json → "model_path": "/Users/hung/emails/.memory/models/default.gguf"
#   file absent → model_loader_lazy_singleton.py:75 → FileNotFoundError
#   orchestrator:287-289 → bare except → state.vector_unavailable = True
#   BM25-only for ~3 months, 0/39 local neurons embedded

# global works fine (model present):
$ cd ~ && memory neuron search "billing" | jq '.meta'
{ "vector_unavailable": false, "total": 653 }
```

**The red test to write** (`tests/embedding/test_central_model_resolution.py`):

```python
def test_central_fallback_when_local_model_absent(tmp_path, monkeypatch):
    """Local store config has NO model_path override (or points to absent file).
    Central ~/.memory/models/default.gguf exists.
    Loader must resolve to central and return a model (not raise FileNotFoundError).
    """
    from memory_cli.embedding.model_loader_lazy_singleton import get_model, reset_model
    from memory_cli.config.config_schema_and_defaults import EmbeddingConfig
    from dataclasses import dataclass
    import pathlib

    reset_model()

    # Central model exists
    central_dir = tmp_path / ".memory" / "models"
    central_dir.mkdir(parents=True)
    central_model = central_dir / "default.gguf"
    central_model.write_bytes(b"fake-central-model")
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)

    # Local config has absent/unset model_path (what `memory init` bakes in today)
    @dataclass
    class _Emb:
        model_path: str = str(tmp_path / "emails" / ".memory" / "models" / "default.gguf")  # absent
        n_ctx: int = 2048
        n_batch: int = 512

    @dataclass
    class _Cfg:
        embedding: _Emb = None
        def __post_init__(self): self.embedding = _Emb()

    from unittest.mock import MagicMock, patch
    mock_llama = MagicMock()
    with patch.dict("sys.modules", {"llama_cpp": MagicMock(Llama=MagicMock(return_value=mock_llama))}):
        result = get_model(_Cfg())  # must NOT raise

    assert result is mock_llama  # resolved to central, loaded fine
    reset_model()
```

This test is **RED today** — `get_model` raises `FileNotFoundError` before checking central.

---

## 2. Blast radius

### Files that read `model_path` or own model loading

| File | Role | Touch? |
|------|------|--------|
| `src/memory_cli/embedding/model_loader_lazy_singleton.py:65-75` | Reads `config.embedding.model_path`, raises FileNotFoundError if absent | **YES — owns the fix** |
| `src/memory_cli/config/config_schema_and_defaults.py:97-100` | VALIDATION_RULES marks `embedding.model_path` as `required: True` | **YES — loosen to optional** |
| `src/memory_cli/config/config_schema_and_defaults.py:155` | `EmbeddingConfig.model_path: str` (non-Optional) | **YES — make Optional[str]** |
| `src/memory_cli/config/init_create_global_or_project_store.py:336` | `_write_default_config` bakes `<store>/models/default.gguf` into config.json | **YES — write `null` instead** |
| `src/memory_cli/cli/noun_handlers/model_noun_handler.py:78-96` | `_auto_symlink_to_local` — creates symlink after global download | **YES — delete this function** (central resolution makes it dead code) |
| `src/memory_cli/search/light_search_pipeline_orchestrator.py:287-289` | Swallows model load exception (bare `except`) | **Shared with MEM-FIX-0001/0002** — add `vector_unavailable_reason` (backlog #68) |
| `src/memory_cli/integrity/startup_drift_check_model_and_dims.py` | References model path for drift checks | Audit only — verify central path used |
| `src/memory_cli/integrity/first_vector_write_seed_metadata.py` | References model path | Audit only |

### Must-not-regress

- **Global store behavior:** `~/.memory/config.json` today sets `model_path = ~/.memory/models/default.gguf`. After change: explicit path in config still wins (resolution order step 1). Global store unaffected.
- **Explicit override:** if any store has a valid `model_path` in config pointing to an existing file → use it, no fallback. Operator escape hatch preserved.
- **`memory model download` flow:** `handle_download` still downloads to `~/.memory/models/default.gguf` by default. `--local` flag + `_auto_symlink_to_local` become dead code once central resolution lands — remove both to avoid confusion.
- **`model download --force`:** still re-downloads global; no behavior change.

---

## 3. Spec

### Resolution order (new behavior)

Implemented in `model_loader_lazy_singleton.get_model()`, step 2.5 (between "read config" and "validate path"):

```
1. config.embedding.model_path is set AND file exists → USE IT (explicit wins)
2. config.embedding.model_path is set AND file ABSENT → FALL THROUGH to step 3
   [? see assumption A1 — warn vs silent]
3. ~/.memory/models/default.gguf exists → USE IT (central default)
4. None of the above → raise FileNotFoundError("No embedding model found. Run: memory model download")
```

### File that owns the fix

`model_loader_lazy_singleton.py` — insert fallback between step 2 (read config) and step 3 (validate). Config layer remains passive (returns whatever is in config.json, including `None`).

### Config changes required

`config_schema_and_defaults.py`:
- `EmbeddingConfig.model_path`: `str` → `Optional[str]` (default `None`)
- `CONFIG_DEFAULTS["embedding"]["model_path"]`: already `None` — leave
- `VALIDATION_RULES["embedding.model_path"]`: remove `"required": True` (or change to `required: False`) — `None` is now valid; loader handles fallback

`init_create_global_or_project_store.py` (`_write_default_config`):
- Line 336: change `str(store_path / "models" / "default.gguf")` → `None`
- This makes new stores write `"model_path": null` in config.json → central fallback fires

### Existing stores with baked local paths

**[? A1]** Existing local `config.json` files already have `model_path = <store>/models/default.gguf`. Most of those files are absent (the root cause). With the new resolution order (step 2 above), these stores auto-fall-through to central. No migration needed. Behavior is:

- path set + file absent → fall through → central
- path set + file present (e.g. emails after manual symlink) → use it (explicit still wins)

This is the ASSUMPTION — see A1.

### `_auto_symlink_to_local` (model_noun_handler.py:155-182)

Delete. Central resolution makes per-store models dead code. Removes the whole class of "model download but no symlink → local still broken."

### Test location

`tests/embedding/test_central_model_resolution.py` — new file.

### Suite command + baseline count

```bash
cd /Users/hung/projects/memory-cli && uv run pytest tests/ -q --tb=no
```

Baseline (run 2026-06-10):
```
1826 passed, 824 warnings in 36.62s
```

New test file adds ~4 cases:
- `test_central_fallback_when_local_model_absent` (the red acceptance test above)
- `test_explicit_model_path_wins_when_file_exists`
- `test_explicit_path_absent_falls_through_to_central`
- `test_no_model_anywhere_raises_file_not_found`

---

## 4. Assumptions [?]

- **A1** — existing stores with baked local `model_path` (absent file) silently fall through to central without warning. (assumed — alternative: emit a warning line to stderr. Decide before implementation.)
- **A2** — `None` model_path in `EmbeddingConfig` is valid post-change; no other code dereferences `config.embedding.model_path` without a None-check. (assumed — blast radius table above covers known readers; implementer must grep for any missed callsites.)
- **A3** — `memory model download --local` flag + `_auto_symlink_to_local` become dead code and are deleted, not deprecated behind a flag. (assumed — confirm with Hung if `--local` has any surviving use case.)
- **A4** — central path is always `Path.home() / ".memory" / "models" / "default.gguf"`. No config key controls it. (assumed — it's a convention, not configurable. If a custom global store path is ever supported, revisit.)
- **A5** — `startup_drift_check_model_and_dims.py` and `first_vector_write_seed_metadata.py` receive the already-resolved model path (after loader runs) — not the raw config value. If they read config directly, they need the same fallback. Implementer must verify. (not verified in this spec — read-only constraint.)

---

## Sequence note (MEM-FIX-0001/0002)

`light_search_pipeline_orchestrator.py` is touched by MEM-FIX-0001 (bare `load_config()` ignores `--global`, backlog #67) and MEM-FIX-0002 (bare except, backlog #68). MEM-FIX-0003 does NOT touch the orchestrator. Sequence is independent — but if MEM-FIX-0001/0002 land first, the orchestrator's bare except is replaced, surfacing model resolution errors more visibly. Either order is safe; MEM-FIX-0003 first is fine.
