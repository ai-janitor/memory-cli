# MEM-FIX-0002 Result

## CHANGES (file:line)

1. `src/memory_cli/search/light_search_pipeline_orchestrator.py`
   - `PipelineState`: added `vector_unavailable_reason: Optional[str] = None` after `vector_unavailable`
   - `SearchResultEnvelope`: added `vector_unavailable_reason: Optional[str] = None` after `vector_unavailable`
   - `_run_retrieval_stage` except block: `except Exception as exc` + `state.vector_unavailable_reason = f"{type(exc).__name__}: {exc}"`
   - Outer except fallback `SearchResultEnvelope(...)`: added `vector_unavailable_reason=state.vector_unavailable_reason`
   - `_run_output_stage` return `SearchResultEnvelope(...)`: added `vector_unavailable_reason=state.vector_unavailable_reason`

2. `src/memory_cli/search/search_result_hydration_and_envelope.py`
   - Added `Optional` to typing imports
   - `build_envelope()`: added `vector_unavailable_reason: Optional[str] = None` param
   - `metadata` dict: added `"vector_unavailable_reason": vector_unavailable_reason`

3. `src/memory_cli/cli/noun_handlers/neuron_noun_handler.py`
   - Added `Optional` to typing imports
   - `handle_search()`: added `vector_unavailable_reason: Optional[str] = None` init
   - Loop body: capture first non-None reason when `envelope.vector_unavailable`
   - Returned `meta` dict: added `"vector_unavailable_reason": vector_unavailable_reason`

4. `tests/search/test_light_search_pipeline.py`
   - Appended `test_bm25_only_sets_vector_unavailable_reason` to `TestLightSearchBM25OnlyFallback`
   - Appended `test_reason_none_when_vectors_available` to `TestLightSearchBM25OnlyFallback`

5. `tests/search/test_search_result_hydration.py`
   - Appended `test_metadata_has_vector_unavailable_reason` to `TestEnvelopeStructure`
   - Appended `test_metadata_reason_none_when_not_set` to `TestEnvelopeStructure`

## RED TRANSCRIPT

```
FAILED tests/search/test_light_search_pipeline.py::TestLightSearchBM25OnlyFallback::test_bm25_only_sets_vector_unavailable_reason
FAILED tests/search/test_light_search_pipeline.py::TestLightSearchBM25OnlyFallback::test_reason_none_when_vectors_available
FAILED tests/search/test_search_result_hydration.py::TestEnvelopeStructure::test_metadata_has_vector_unavailable_reason
FAILED tests/search/test_search_result_hydration.py::TestEnvelopeStructure::test_metadata_reason_none_when_not_set
4 failed, 2 warnings in 1.36s
```

## GREEN TRANSCRIPT

```
4 passed, 2 warnings in 4.95s
```

## FULL-SUITE TAIL

```
1841 passed, 833 warnings in 11.51s
```

## DEVIATIONS FROM SPEC

1. **`build_envelope` call sites in orchestrator**: spec §3e says "update the two `build_envelope(...)` call sites in `_run_output_stage`". No such call sites exist — the orchestrator instantiates `SearchResultEnvelope` directly (already covered by §3d). The `build_envelope` function is only called from tests. No action needed beyond updating the function signature + metadata dict. Confirmed by grep.

2. **Baseline clarification**: spec states baseline = 1826. MEM-FIX-0001 result reported 1831. Actual combined tree pre-fix = 1831 (net +10 after 0002 = 1841). Requirement ≥1835 satisfied.

## SKILL-FEEDBACK

Spec §3e "Also update the two `build_envelope(...)` call sites in `_run_output_stage`" is stale/wrong — the orchestrator never calls `build_envelope()` (it constructs `SearchResultEnvelope` directly). Spec should verify call sites with grep before listing them. Would save a false-positive confusion pass.
