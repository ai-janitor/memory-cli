# =============================================================================
# Package: tests.registries
# Purpose: Test suite for the tag and attribute key registries.
# Rationale: Registry operations are foundational — every neuron add, search,
#   and filter depends on correct tag/attr resolution. These tests verify CRUD,
#   normalization, idempotency, referential integrity checks, lookup dispatch,
#   and tag filtering primitives.
# Organization:
#   test_tag_registry.py — Tag CRUD, normalization, idempotency, in-use block
#   test_attr_registry.py — Attr CRUD, same pattern as tags
#   test_registry_lookup.py — Lookup by name vs ID, auto-create vs not-found
#   test_tag_filter_and_or.py — AND/OR filtering, resolution, empty filter
# =============================================================================
