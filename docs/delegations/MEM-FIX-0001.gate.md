# GATE — MEM-FIX-0001 verify — 2026-06-10

<!-- _run_retrieval_stage bare load_config() ignored --global. Fix threads resolved config into light_search. -->

## unit
cmd: uv run pytest tests/search/test_light_search_pipeline.py::TestLightSearchBM25OnlyFallback::test_global_config_used_when_passed_explicitly + tests/cli/test_layered_search_local_and_global.py -k test_search_merges_local_and_global
result: 2 passed (1 + 1)
```
$ uv run pytest "tests/search/test_light_search_pipeline.py::TestLightSearchBM25OnlyFallback::test_global_config_used_when_passed_explicitly" -q --tb=short
.                                                                        [100%]
1 passed, 1 warning in 0.11s

$ uv run pytest -k "test_search_merges_local_and_global" tests/cli/test_layered_search_local_and_global.py -q --tb=short
.                                                                        [100%]
1 passed, 17 deselected, 1 warning in 0.16s
```

## e2e
test: real `memory neuron search "billing" --global --json` from a project dir whose LOCAL config.json has model_path=/nonexistent/path/bad.gguf; temp HOME=$TMP global store (init'd by real CLI, model_path=null) with real 146MB gguf symlinked into ~/.memory/models/default.gguf
wired-real: real `memory` CLI binary, real sqlite stores (temp project + temp global), real sqlite-vec extension, REAL embedding model loaded (146MB nomic gguf), real migrations — NO mocks at the config-resolution / retrieval seam
result: 1 passed (search returned vector_unavailable:false, total:1 — global config used, central model embedded)
```
=== A) search --global FROM proj dir (FIX: must use GLOBAL config -> vector_unavailable false) ===
{
  "query": "billing",
  "total": 1,
  "vector_unavailable": false,
  "vector_unavailable_reason": null
}
```

## adversarial
- load_config NOT reached when config passed (runtime): patch memory_cli.config.load_config side_effect=AssertionError + patch get_model; light_search(conn,opts,config=sentinel) -> load_config called: False ; get_model received sentinel: True
- bare load_config() STILL used when config=None (fallback intact): patch load_config side_effect=FileNotFoundError; light_search(conn,opts) w/ default config=None -> load_config invoked on None path: True
- get_layered_connections_with_config exists + threads config (grep): grep -n get_layered_connections_with_config src/.../db_connection_from_global_flags.py -> defined L118, returns List[Tuple[conn,MemoryConfig,str]]; neuron_noun_handler L431 unpacks (conn,config,scope) and passes config=config to light_search

## flags
- DEVIATION-1 (return-type not changed; added get_layered_connections_with_config instead): accept — doer correctly disproved the spec's [?] "only one caller" assumption via grep (8+ callers of get_layered_connections); the additive new function is the lower-risk path and leaves all existing callers green. Verified no-break: full suite 1841 passed.
- DEVIATION-2 (load_config kept lazy, not module-level; test patches memory_cli.config.load_config): accept — patching the canonical source is an equivalent (stronger) guarantee; adversarial runtime check confirms the conditional fallback fires exactly when config is None and not otherwise.
- DEVIATION-3 (baseline 1831 vs spec 1826): accept — reconciled. Clean-HEAD baseline I measured = 1826; the +5 came from sibling untracked specs in the combined tree. Net +1 from 0001's new test holds.

## verifier
agent: opus-4-8-1m-gate-verifier
tokens: 0

## VERDICT: accept
rework-task: n/a

## RULING: accept on opus-4-8-1m-gate-verifier — fix verified at real CLI seam (global config honored, real model embedded); both anti-fake runtime invariants hold; suite green.
