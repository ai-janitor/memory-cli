# Task 44: Salience Scoring Pass — Access Metrics

## Checklist

- [ ] Create `src/memory_cli/search/salience_scoring_access_metrics.py`
  - Batch-fetch `access_count` and `last_accessed_at` from neurons table
  - Compute frequency boost: `log2(1 + access_count) * freq_scale`
  - Compute recency-of-access boost: exponential decay on `last_accessed_at`
  - Combined salience_weight = `1.0 + frequency_boost + recency_boost`
  - Zero-access neurons get salience_weight = 1.0 (neutral, no penalty)
  - Attach `salience_weight` to each candidate dict

- [ ] Modify `src/memory_cli/search/final_score_combine_and_rank.py`
  - Multiply final_score by `salience_weight` (default 1.0 if missing)
  - Apply to all match types: direct_match, fan_out, tag_affinity

- [ ] Modify `src/memory_cli/search/light_search_pipeline_orchestrator.py`
  - Import salience scoring module
  - Add salience pass between temporal decay (stage 6) and tag filtering (stage 7)
  - Add `salience_boosted` field to PipelineState

- [ ] Run `uv run pytest` — all tests pass
- [ ] Commit
- [ ] `minion task complete-phase --task-id 44 --agent fighter`
