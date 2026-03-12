# =============================================================================
# schema_version_reader.py — Read and compare schema versions
# =============================================================================
# Purpose:     Read the current schema version from the meta table, compare it
#              against the expected version, and determine what action is needed:
#              proceed (versions match), migrate (current < expected), or abort
#              (current > expected, meaning a newer CLI wrote the DB).
# Rationale:   Schema versioning prevents silent corruption when the DB was
#              created by a different CLI version. The meta table is the single
#              source of truth. If the meta table doesn't exist yet, that means
#              version 0 (empty database, needs full migration).
# Responsibility:
#   - Query the meta table for the 'schema_version' key
#   - Handle the case where the meta table does not exist (version 0)
#   - Compare current vs expected and return an action enum/string
#   - Never modify the database — read-only queries only
# Organization:
#   Public functions:
#     read_schema_version(conn) -> int
#     compare_schema_version(conn, expected) -> SchemaAction
#   SchemaAction enum: PROCEED, MIGRATE, ABORT
# =============================================================================

from __future__ import annotations

import enum
import sqlite3


class SchemaAction(enum.Enum):
    """Result of comparing current schema version against expected version."""
    PROCEED = "proceed"   # current == expected, DB is ready
    MIGRATE = "migrate"   # current < expected, migrations needed
    ABORT = "abort"       # current > expected, DB is from a newer CLI


# --- Expected schema version constant ---
# This is the version that this CLI release expects.
# Bump this when adding new migrations.
EXPECTED_SCHEMA_VERSION: int = 1


def read_schema_version(conn: sqlite3.Connection) -> int:
    """Read the current schema version from the meta table.

    Args:
        conn: An open sqlite3.Connection.

    Returns:
        The integer schema version. Returns 0 if the meta table does not exist
        (brand new database).

    Raises:
        sqlite3.Error: On unexpected database errors (not table-missing).
    """
    # --- Step 1: Check if the meta table exists ---
    # Query sqlite_master for table name 'meta'
    # If not found: return 0 (no schema has ever been applied)
    meta_check = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    if meta_check is None:
        return 0

    # --- Step 2: Read the schema_version key ---
    # SELECT value FROM meta WHERE key = 'schema_version'
    # If no row: return 0 (meta table exists but no version — shouldn't happen,
    #   but handle defensively)
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        return 0

    # --- Step 3: Parse and return ---
    # Cast value to int
    # If cast fails: raise ValueError with descriptive message
    try:
        return int(row[0])
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"schema_version in meta table is not a valid integer: {row[0]!r}"
        ) from exc


def compare_schema_version(
    conn: sqlite3.Connection,
    expected: int = EXPECTED_SCHEMA_VERSION,
) -> SchemaAction:
    """Compare the current DB schema version against the expected version.

    Args:
        conn: An open sqlite3.Connection.
        expected: The schema version this CLI release requires.

    Returns:
        SchemaAction indicating what the caller should do.
    """
    # --- Step 1: Read current version ---
    # current = read_schema_version(conn)
    current = read_schema_version(conn)

    # --- Step 2: Compare ---
    # if current == expected: return SchemaAction.PROCEED
    # if current < expected: return SchemaAction.MIGRATE
    # if current > expected: return SchemaAction.ABORT
    #   (DB was written by a newer CLI — cannot safely downgrade)
    if current == expected:
        return SchemaAction.PROCEED
    if current < expected:
        return SchemaAction.MIGRATE
    # current > expected: DB is from a newer CLI
    return SchemaAction.ABORT
