# =============================================================================
# migration_runner_single_transaction.py — Run migrations in a single transaction
# =============================================================================
# Purpose:     Execute pending schema migrations in sequence within a single
#              database transaction. If any migration step fails, the entire
#              batch is rolled back, leaving the DB in its previous state.
# Rationale:   Single-transaction migration ensures atomicity — the DB is never
#              left in a half-migrated state. This is critical because a partial
#              schema could corrupt data or crash subsequent operations. On
#              failure, the CLI exits with code 2 so the user knows the DB
#              needs attention.
# Responsibility:
#   - Determine which migrations need to run (from current_version+1 to expected)
#   - Execute each migration's apply() function in order within one transaction
#   - Update the meta table's schema_version after all migrations succeed
#   - Update last_migrated_at timestamp in meta
#   - On any failure: rollback the entire transaction, log the error
#   - Return success/failure status for the caller to decide exit code
# Organization:
#   Public function:
#     run_pending_migrations(conn, current_version, target_version) -> bool
#   Internal:
#     _get_migration_steps(from_version, to_version) -> list of callables
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import Callable


# --- Type alias for migration functions ---
# Each migration is a callable that takes a connection and executes DDL
MigrationFn = Callable[[sqlite3.Connection], None]


def run_pending_migrations(
    conn: sqlite3.Connection,
    current_version: int,
    target_version: int,
) -> bool:
    """Run all migrations from current_version+1 through target_version.

    All migrations execute within a single transaction. If any migration
    fails, the entire batch is rolled back.

    Args:
        conn: An open sqlite3.Connection with extensions already loaded.
        current_version: The schema version currently in the DB (0 for new DB).
        target_version: The schema version to migrate to.

    Returns:
        True if all migrations succeeded, False if any failed (rolled back).

    Raises:
        SystemExit: With code 2 on migration failure (after rollback).
    """
    # --- Step 1: Determine which migrations to run ---
    # steps = _get_migration_steps(current_version, target_version)
    # If no steps needed: return True immediately

    # --- Step 2: Begin explicit transaction ---
    # Use conn.execute("BEGIN IMMEDIATE") to acquire a write lock early
    # This prevents SQLITE_BUSY during the migration itself

    # --- Step 3: Execute each migration step in order ---
    # try:
    #   for version, apply_fn in steps:
    #     apply_fn(conn)
    #     # Each apply_fn executes DDL statements (CREATE TABLE, etc.)
    #     # They must NOT commit or begin their own transactions

    # --- Step 4: Update schema version in meta table ---
    #   UPDATE meta SET value = str(target_version) WHERE key = 'schema_version'
    #   UPDATE meta SET value = current_timestamp_ms WHERE key = 'last_migrated_at'
    #   conn.execute("COMMIT")
    #   return True

    # --- Step 5: Handle failure — rollback everything ---
    # except Exception as e:
    #   conn.execute("ROLLBACK")
    #   Log the error with details about which migration step failed
    #   return False
    #   (Caller will sys.exit(2))
    pass


def _get_migration_steps(
    from_version: int,
    to_version: int,
) -> list[tuple[int, MigrationFn]]:
    """Look up migration functions for the range (from_version, to_version].

    Args:
        from_version: Starting version (exclusive).
        to_version: Ending version (inclusive).

    Returns:
        List of (version_number, apply_function) tuples in execution order.

    Raises:
        ValueError: If a required migration is missing from the registry.
    """
    # --- Step 1: Import the migration registry ---
    # from .migrations import MIGRATION_REGISTRY

    # --- Step 2: Collect steps in order ---
    # For each version in range(from_version + 1, to_version + 1):
    #   Look up the migration function in MIGRATION_REGISTRY
    #   If not found: raise ValueError (gap in migration chain)
    #   Append (version, fn) to the result list

    # --- Step 3: Return ordered list ---
    pass
