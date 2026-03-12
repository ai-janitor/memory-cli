# =============================================================================
# Package: tests.neuron
# Purpose: Test suite for neuron CRUD & storage — spec #6.
# Rationale: Each neuron operation has its own test module to keep tests
#   focused and easy to run individually. Test modules mirror the source
#   module structure for navigability.
# Responsibility:
#   - test_neuron_add.py — Full add pipeline tests
#   - test_neuron_get.py — Get-by-ID tests
#   - test_neuron_list.py — Filtered listing tests
#   - test_neuron_update.py — Mutation tests
#   - test_neuron_archive_restore.py — Lifecycle transition tests
#   - test_auto_tag_capture.py — Auto-tag generation tests
#   - test_project_detection.py — Project detection tests
# Organization: One test file per source module, pytest conventions.
# =============================================================================
