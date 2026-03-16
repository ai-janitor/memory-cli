# Task 46 — Provenance Tracking for Authored vs Extracted Edges

## Goal
Add provenance metadata to edges distinguishing **authored** (agent-created, confidence=1.0)
from **extracted** (model-inferred, confidence < 1.0). Spreading activation decays faster
through low-confidence edges.

## Checklist

- [ ] **v004 migration**: Add `provenance TEXT NOT NULL DEFAULT 'authored'` and
      `confidence REAL NOT NULL DEFAULT 1.0` columns to edges table
- [ ] **edge_add**: Accept optional `provenance` and `confidence` params;
      defaults: provenance="authored", confidence=1.0. Validate confidence in (0.0, 1.0].
- [ ] **spreading activation**: Multiply activation by `edge.confidence` in addition
      to `edge.weight`. `_get_neighbors()` returns confidence; `_compute_activation()`
      factors it in.
- [ ] **edge_list**: Include provenance and confidence in returned edge dicts
- [ ] **edge_update**: Allow updating provenance and confidence
- [ ] **edge_splice**: New edges inherit provenance="authored", confidence=1.0 (splicing is an authored action)
- [ ] **link_flag**: New edges get provenance="authored", confidence=1.0
- [ ] **CLI handler**: Add `--provenance` and `--confidence` flags to `edge add` and `edge update`
- [ ] **Tests**: Provenance stored/returned, confidence weighting in spreading activation,
      extracted edges decay faster than authored
- [ ] **Full test suite passes**: `uv run pytest`
