# Task 51 — LRU-based automatic archival command (`memory neuron prune`)

## Checklist

- [ ] **v004 migration**: Add `last_accessed_at INTEGER` and `access_count INTEGER DEFAULT 0` columns to `neurons` table
- [ ] **Prune logic module**: `src/memory_cli/neuron/neuron_prune_by_lru_age.py`
  - Query active neurons where `last_accessed_at` is NULL or older than threshold
  - Prioritize `access_count=0` neurons first, then by `last_accessed_at` ASC
  - Dry-run mode: return candidates without archiving
  - Archive via existing `neuron_archive()` — neurons remain restorable
  - Return report: count archived, total edge weight freed
- [ ] **CLI verb**: `handle_prune()` in `neuron_noun_handler.py`
  - Flags: `--days N` (default 30), `--dry-run`
  - Register verb in `_VERB_MAP`, `_VERB_DESCRIPTIONS`, `_FLAG_DEFS`
- [ ] **Package export**: Add `neuron_prune` to `neuron/__init__.py`
- [ ] **Tests**: `tests/neuron/test_neuron_prune_lru.py`
  - Prune archives neurons not accessed in N days
  - `access_count=0` + old neurons pruned first
  - Dry-run mode returns candidates without archiving
  - Pruned neurons are restorable via `neuron_restore()`
  - Report includes count and freed edge weight
  - Recently accessed neurons are NOT pruned
- [ ] **All tests pass**: `uv run pytest`
- [ ] **Commit**
- [ ] **Complete task phase**: `minion task complete-phase --task-id 51 --agent whitemage`
