# GATE — MEM-FIX-0003 verify — 2026-06-10

<!-- Central model resolution: ~/.memory/models/default.gguf wins when per-store path absent; init writes null; --local removed. -->

## unit
cmd: uv run pytest tests/embedding/test_central_model_resolution.py tests/embedding/test_model_loader.py tests/config/test_init_global_and_project.py
result: 42 passed
```
$ uv run pytest tests/embedding/test_central_model_resolution.py tests/embedding/test_model_loader.py tests/config/test_init_global_and_project.py -q --tb=short
..........................................                               [100%]
42 passed in 0.95s
```

## e2e
test: real `memory init` (project + global) -> assert written config.json embedding.model_path == null; real `memory neuron search --global` resolves central ~/.memory/models/default.gguf and embeds (vector_unavailable:false); explicit-absent local path falls through to central
wired-real: real `memory` CLI binary, real sqlite stores (temp HOME), real config writer (init_create_global_or_project_store), real model loader resolving + loading the REAL 146MB gguf, real migrations — NO mocks
result: 2 passed (init writes null; central fallback embeds for real)
```
=== real `memory init --global` config model_path (expect null per 0003) ===
None
=== real `memory init` (project) config model_path (expect null) ===
None
=== search --global from project dir whose LOCAL model_path=/nonexistent: central resolved + embedded ===
{
  "query": "billing",
  "total": 1,
  "vector_unavailable": false,
  "vector_unavailable_reason": null
}
```

## adversarial
- --local flag truly gone from help + source: uv run memory model download (help) shows only --force; grep -n "\-\-local|use_local|_auto_symlink_to_local" model_noun_handler.py -> no matches (CLEAN); _FLAG_DEFS['download'] == [{'name':'--force',...}] only
- central path resolution is the load-bearing change (not config side-effect): with central gguf present + LOCAL model_path=/nonexistent, --global search -> vector_unavailable:false (resolved central); remove central gguf -> same search -> vector_unavailable:true + reason "FileNotFoundError: No embedding model found" (proves loader step 2->3->4 order live)
- explicit path still wins when file exists: tests/embedding/test_central_model_resolution.py::test_explicit_model_path_wins_when_file_exists PASSED (escape hatch preserved); EmbeddingConfig.model_path now Optional[str]=None, VALIDATION_RULES required:False -> grep config_schema_and_defaults.py confirms both

## flags
- DEVIATION-D1 (EmbeddingConfig field reorder so model_path is last — dataclass default ordering): accept — mechanically required for a defaulted field; all callers use kwargs (verified suite green); no positional-construction breakage.
- DEVIATION-D2 (A5: meta_stats / meta_check read config["embedding"]["model_path"] directly; doer did NOT patch them, declared the `memory meta stats` crash-on-None gap): accept-as-handed-off — this exact gap is the origin of MEM-FIX-0005, which DOES fix both files (verified in 0005 gate, real `memory meta stats` -> config_model_name:'none', no crash). With 0005 in the same combined tree the gap is closed; flagged correctly.
- DEVIATION-D3 (out-of-fence test_global_config_used_when_passed_explicitly added by parallel 0001 doer): accept — not 0003's fence; that test passes in the combined tree (verified in 0001 gate). No action.

## verifier
agent: opus-4-8-1m-gate-verifier
tokens: 0

## VERDICT: accept
rework-task: n/a

## RULING: accept on opus-4-8-1m-gate-verifier — init writes null, central model resolves + embeds for real, explicit path still wins, --local fully removed; D2 gap closed by 0005 in same tree; suite green.
