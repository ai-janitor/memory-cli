# Task 74 Checklist — --full flag + surface access metrics

- [x] 1. `neuron_get_by_id.py`: add `last_accessed_at, access_count` to SELECT
- [x] 2. `neuron_noun_handler.py` handle_get: add `--full` alias for `--verbose`
- [x] 3. `neuron_noun_handler.py` handle_list: add `--full` alias for `--verbose`
- [x] 4. `neuron_noun_handler.py` handle_search: add `--full` alias for `--verbose`
- [x] 5. `neuron_noun_handler.py` _FLAG_DEFS: update `--verbose` desc + add `--full` entries
- [x] 6. `search_result_hydration_and_envelope.py`: add `access_count, last_accessed_at` to batch SELECT + result dict
- [x] 7. Tests: get --full exposes 4 fields; lean unchanged; --full == --verbose
- [x] 8. `uv run pytest` green — 1821 passed
