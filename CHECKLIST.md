# Task 52: Search Response Time Instrumentation & Reporting

## Checklist

- [ ] **v007 migration** — `search_latency` table (total_ms, retrieval_ms, scoring_ms, output_ms, result_count, recorded_at)
- [ ] **Timing instrumentation** — `light_search_pipeline_orchestrator.py` wraps retrieval/scoring/output stages with `time.perf_counter()`, records to `search_latency` table
- [ ] **Config** — `search.latency_threshold_ms` default (500ms p95 threshold)
- [ ] **`memory meta health`** — new verb: queries `search_latency`, computes p50/p95/p99, warns if p95 > threshold, suggests `memory neuron prune`
- [ ] **Tests pass** — `uv run pytest`
- [ ] Commit
- [ ] `minion task complete-phase --task-id 52 --agent redwiz`
