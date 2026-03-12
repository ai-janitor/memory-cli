# =============================================================================
# Package: tests.export_import
# Purpose: Test suite for the export/import subsystem — verifying portable
#   JSON export, 18-point import validation, transactional writes, and
#   conflict resolution modes.
# Rationale: Export/import is a high-risk surface — data loss or corruption
#   on import is unrecoverable. Exhaustive testing of validation checks,
#   edge cases (empty exports, vector mismatches, ID conflicts), and
#   transaction rollback ensures reliability.
# Organization:
#   test_export_neurons.py — Export with/without filters, vectors, edge filtering
#   test_export_envelope.py — Envelope structure, field types, count integrity
#   test_import_validation.py — All 18 checks, error collection, dry-run
#   test_import_write.py — Transactional write, rollback, tag/attr creation
#   test_conflict_handler.py — skip, overwrite, error modes, edge handling
# =============================================================================
