# Task 42 — Access Tracking Checklist

- [x] v004 migration: add `last_accessed_at` (INTEGER, nullable) and `access_count` (INTEGER DEFAULT 0) to neurons
- [x] Register v004 in migration registry (`__init__.py`)
- [x] Bump `EXPECTED_SCHEMA_VERSION` to 4 in `schema_version_reader.py`
- [x] `neuron_get_by_id.py`: bump `access_count` and set `last_accessed_at` on read
- [x] `search_result_hydration_and_envelope.py`: bump access tracking on search hits
- [x] Tests: migration adds columns, get increments counters, search hits update tracking
- [x] `uv run pytest` passes (1586 passed)
- [ ] Commit
- [ ] `minion task complete-phase --task-id 42 --agent fighter`
