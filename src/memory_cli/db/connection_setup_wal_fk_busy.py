# =============================================================================
# connection_setup_wal_fk_busy.py — Open DB connection with required pragmas
# =============================================================================
# Purpose:     Create a sqlite3.Connection with WAL journal mode, foreign keys
#              enabled, and a 5-second busy timeout. Every CLI invocation calls
#              this before any other DB operation.
# Rationale:   WAL allows concurrent readers + single writer (critical for CLI
#              tools that may overlap). FK enforcement catches broken references
#              at write time. Busy timeout prevents immediate SQLITE_BUSY errors
#              when another process holds the lock.
# Responsibility:
#   - Open or create the SQLite database file at the given path
#   - Set PRAGMA journal_mode = WAL (warn but do not fail if it returns
#     something other than "wal" — e.g. on read-only filesystems)
#   - Set PRAGMA foreign_keys = ON (must succeed — raise on failure)
#   - Set PRAGMA busy_timeout = 5000 (must succeed)
#   - Return the configured sqlite3.Connection
# Organization:
#   Single public function: open_connection(db_path) -> sqlite3.Connection
#   Internal helpers for each pragma step if needed.
# =============================================================================

from __future__ import annotations

import sqlite3
import warnings
from pathlib import Path


def open_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection and configure WAL, FK, and busy_timeout pragmas.

    Args:
        db_path: Filesystem path to the SQLite database file. Will be created
                 if it does not exist. Use ":memory:" for in-memory databases
                 (WAL will not apply but that is acceptable for tests).

    Returns:
        A fully configured sqlite3.Connection ready for extension loading
        and schema initialization.

    Raises:
        sqlite3.Error: If the connection cannot be opened or critical pragmas
                       (foreign_keys, busy_timeout) fail to apply.
    """
    # --- Step 1: Open the raw connection ---
    # sqlite3.connect with check_same_thread=False for potential multi-thread use
    # Row factory set to sqlite3.Row for dict-like access
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # --- Step 2: Set WAL journal mode ---
    # Execute: PRAGMA journal_mode = WAL
    # Read the result row — it returns the actual mode as a string
    # If result != "wal":
    #   Issue warnings.warn() with a descriptive message (non-fatal)
    #   Do NOT raise — WAL failure is degraded but functional
    row = conn.execute("PRAGMA journal_mode = WAL").fetchone()
    actual_mode = row[0] if row else None
    if actual_mode != "wal":
        warnings.warn(
            f"PRAGMA journal_mode = WAL returned '{actual_mode}' instead of 'wal'. "
            "Concurrent write performance may be degraded (e.g. read-only filesystem or in-memory DB).",
            RuntimeWarning,
            stacklevel=2,
        )

    # --- Step 3: Enable foreign key enforcement ---
    # Execute: PRAGMA foreign_keys = ON
    # Verify by reading: PRAGMA foreign_keys — should return 1
    # If not 1: raise sqlite3.OperationalError (this is fatal — schema depends on FK)
    conn.execute("PRAGMA foreign_keys = ON")
    fk_row = conn.execute("PRAGMA foreign_keys").fetchone()
    if fk_row is None or fk_row[0] != 1:
        raise sqlite3.OperationalError(
            "PRAGMA foreign_keys = ON did not take effect. "
            f"Got: {fk_row[0] if fk_row else None}. "
            "Schema integrity depends on FK enforcement."
        )

    # --- Step 4: Set busy timeout ---
    # Execute: PRAGMA busy_timeout = 5000
    # This prevents immediate SQLITE_BUSY when another connection holds a lock
    # 5000ms = 5 seconds of retry before giving up
    conn.execute("PRAGMA busy_timeout = 5000")

    # --- Step 5: Return the configured connection ---
    return conn
