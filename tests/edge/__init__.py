# =============================================================================
# Package: tests.edge
# Purpose: Test suite for edge CRUD & query — spec #7.
# Rationale: Each edge operation has its own test module to keep tests
#   focused and easy to run individually. Test modules mirror the source
#   module structure for navigability.
# Responsibility:
#   - test_edge_add.py — Edge creation: happy path, validation, duplicates, self-loops
#   - test_edge_remove.py — Edge deletion: existing, not found, neurons unaffected
#   - test_edge_list.py — Edge listing: direction filters, pagination, empty, snippets
#   - test_link_flag_atomic.py — Atomic neuron+edge: creation, rollback, validation
# Organization: One test file per source module, pytest conventions.
# =============================================================================
