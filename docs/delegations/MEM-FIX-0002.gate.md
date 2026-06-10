# GATE — MEM-FIX-0002 verify — 2026-06-10

<!-- Additive: capture vector_unavailable_reason (exc class+message) through PipelineState -> envelope -> CLI meta -> JSON. -->

## unit
cmd: uv run pytest (4 new tests) test_light_search_pipeline.py::TestLightSearchBM25OnlyFallback::{test_bm25_only_sets_vector_unavailable_reason,test_reason_none_when_vectors_available} + test_search_result_hydration.py::TestEnvelopeStructure::{test_metadata_has_vector_unavailable_reason,test_metadata_reason_none_when_not_set}
result: 4 passed
```
$ uv run pytest \
  "tests/search/test_light_search_pipeline.py::TestLightSearchBM25OnlyFallback::test_bm25_only_sets_vector_unavailable_reason" \
  "tests/search/test_light_search_pipeline.py::TestLightSearchBM25OnlyFallback::test_reason_none_when_vectors_available" \
  "tests/search/test_search_result_hydration.py::TestEnvelopeStructure::test_metadata_has_vector_unavailable_reason" \
  "tests/search/test_search_result_hydration.py::TestEnvelopeStructure::test_metadata_reason_none_when_not_set" \
  -q --tb=short
4 passed, 2 warnings in 1.26s
```

## e2e
test: (A) real `memory neuron search --global` with central model REMOVED -> CLI meta JSON must carry reason string; (B) real light_search over real migrated in-memory DB with get_model patched to raise FileNotFoundError, then real build_envelope JSON seam asserting null-vs-string
wired-real: real `memory` CLI binary + real sqlite stores + real migrations for (A); real open_connection + real sqlite-vec ext + real v001/v004 migrations + real light_search pipeline + real build_envelope for (B) — only the model loader (a hard external .gguf dep) is patched to force the FileNotFoundError branch under test
result: 2 passed (A: CLI meta reason string captured; B: exact class+msg + JSON str/None seam)
```
=== A) real CLI: --global search, central model temporarily removed ===
{
  "query": "billing",
  "total": 1,
  "vector_unavailable": true,
  "vector_unavailable_reason": "FileNotFoundError: No embedding model found. Run: memory model download"
}

=== B) reason format + JSON seam ===
TRUE-case reason: 'FileNotFoundError: Embedding model not found: /path/to/missing.gguf'
  is exact class+msg: True
JSON true  reason type: str -> FileNotFoundError: x
JSON false reason: None (must be None/null)
```

## adversarial
- reason is f"{type(exc).__name__}: {exc}" exactly (true-case): patched get_model raise FileNotFoundError("Embedding model not found: /path/to/missing.gguf") -> env.vector_unavailable_reason == "FileNotFoundError: Embedding model not found: /path/to/missing.gguf" (== True)
- JSON reason is null (not "" or "None" or absent) when vectors available: build_envelope([],0,20,0,vector_unavailable=False)['metadata']['vector_unavailable_reason'] -> None (Python None -> JSON null); and str (not bool/obj) when true -> type str
- CLI meta forwards reason end-to-end (real stack, not just dataclass): real `memory neuron search --global` with no model anywhere -> meta.vector_unavailable_reason == "FileNotFoundError: No embedding model found..." (proves PipelineState->envelope->handler->Result.meta wiring all live)

## flags
- DEVIATION-1 (spec §3e "two build_envelope call sites in _run_output_stage" don't exist; orchestrator builds SearchResultEnvelope directly): accept — doer's grep correct. build_envelope is only called from tests; function signature + metadata dict were updated and are covered by the two hydration tests. No live behavior gap — orchestrator's direct SearchResultEnvelope path carries reason (verified in e2e A).
- DEVIATION-2 (baseline 1841 vs spec 1826): accept — combined-tree count; clean-HEAD baseline I independently measured = 1826. Additive field, zero pre-existing tests broken.

## verifier
agent: opus-4-8-1m-gate-verifier
tokens: 0

## VERDICT: accept
rework-task: n/a

## RULING: accept on opus-4-8-1m-gate-verifier — reason propagates exc class+message verbatim through to live CLI JSON meta; null when healthy, string when unavailable; purely additive, suite green.
