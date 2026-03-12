# =============================================================================
# tests.db — Database layer test package
# =============================================================================
# Purpose:     Test suite for all database operations: connection setup,
#              extension loading, schema versioning, and migrations.
# Rationale:   DB layer is the foundation — if schema or connections break,
#              everything above fails. These tests run against in-memory SQLite
#              and temporary file DBs to validate the full init sequence.
# Organization:
#   test_connection_setup.py          — pragma tests
#   test_extension_loader.py          — sqlite-vec + FTS5 tests
#   test_schema_migration_v001.py     — full migration verification
# =============================================================================
