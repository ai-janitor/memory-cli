# =============================================================================
# tests/integrity/__init__.py — Test suite for metadata & integrity subsystem
# =============================================================================
# Purpose:     Package marker for the integrity test suite. Tests cover
#              startup drift detection, model drift handling, dimension drift
#              blocking, first-vector metadata seeding, meta stats, and
#              meta check (9-point integrity scan).
# Rationale:   Integrity is the safety net for the entire vector subsystem.
#              Bugs here mean silent data corruption or false search results.
#              Every code path — especially edge cases like concurrent agents,
#              empty DBs, and mixed drift states — must be exercised.
# Organization:
#   - test_startup_drift_check.py — No drift, model drift, dimension drift,
#     both, no vectors yet
#   - test_model_drift_stale.py — Stale marking, warning text, vector op
#     blocking, idempotent marking
#   - test_dimension_drift.py — Hard block, error message, exit code 2
#   - test_first_vector_seed.py — First write seeds, subsequent writes don't
#     overwrite, concurrent safety
#   - test_meta_stats.py — All fields returned, empty DB, populated DB,
#     stale state
#   - test_meta_check.py — All 9 checks, orphan detection, dimension
#     sampling, issue reporting
# =============================================================================
