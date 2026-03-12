# =============================================================================
# memory_cli.db — Database layer package
# =============================================================================
# Purpose:     Public API surface for all database operations: connection,
#              extension loading, schema versioning, and migration execution.
# Rationale:   Single import point so callers never reach into submodules.
#              Every CLI invocation flows through: connect -> load extensions
#              -> check/run migrations -> return ready connection.
# Responsibility:
#   - Re-export the primary entry point (get_connection or similar)
#   - Re-export schema version utilities for introspection
#   - Hide internal wiring (migration steps, pragma details)
# Organization:
#   connection_setup_wal_fk_busy.py  — low-level connection + pragmas
#   extension_loader_sqlite_vec.py   — sqlite-vec + FTS5 checks
#   schema_version_reader.py         — read/compare schema version
#   migration_runner_single_transaction.py — orchestrate migrations
#   migrations/                      — individual migration scripts
# =============================================================================

# --- Public API exports (to be populated during implementation) ---
# from .connection_setup_wal_fk_busy import open_connection
# from .schema_version_reader import read_schema_version
# from .migration_runner_single_transaction import run_pending_migrations

__all__: list[str] = [
    # "open_connection",
    # "read_schema_version",
    # "run_pending_migrations",
]
