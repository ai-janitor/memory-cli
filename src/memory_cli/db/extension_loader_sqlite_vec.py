# =============================================================================
# extension_loader_sqlite_vec.py — Load sqlite-vec extension, verify FTS5
# =============================================================================
# Purpose:     Load the sqlite-vec extension into an open connection so that
#              vec0 virtual tables are available. Also verify that FTS5 is
#              compiled into the Python sqlite3 module (it usually is, but
#              we check to fail fast with a clear message).
# Rationale:   sqlite-vec provides vector similarity search via vec0 virtual
#              tables. It MUST be loaded before any schema initialization
#              because the v001 migration creates a vec0 table. FTS5 is used
#              for full-text search on neuron content + tags.
# Responsibility:
#   - Enable extension loading on the connection
#   - Load sqlite-vec using sqlite_vec.load(conn) from the sqlite-vec package
#   - Verify vec0 is available by attempting a trivial query
#   - Verify FTS5 is available by attempting a trivial FTS5 create
#   - Raise clear errors if either is missing
# Organization:
#   Public functions:
#     load_sqlite_vec(conn) -> None
#     verify_fts5(conn) -> None
#     load_and_verify_extensions(conn) -> None  (calls both)
# =============================================================================

from __future__ import annotations

import sqlite3


def load_sqlite_vec(conn: sqlite3.Connection) -> None:
    """Load the sqlite-vec extension into the given connection.

    Args:
        conn: An open sqlite3.Connection (pragmas already set).

    Raises:
        RuntimeError: If sqlite-vec is not installed or fails to load.
        sqlite3.OperationalError: If extension loading is disabled or fails.
    """
    # --- Step 1: Enable extension loading ---
    # conn.enable_load_extension(True)
    # This is required before any loadable extension can be used

    # --- Step 2: Import sqlite_vec and call its load() helper ---
    # try:
    #   import sqlite_vec
    #   sqlite_vec.load(conn)
    # except ImportError:
    #   raise RuntimeError with message about installing sqlite-vec package
    # except sqlite3.OperationalError as e:
    #   raise RuntimeError wrapping the original error with context

    # --- Step 3: Disable extension loading (security hardening) ---
    # conn.enable_load_extension(False)
    # Extensions are loaded once at startup; no reason to leave this open

    # --- Step 4: Verify vec0 is usable ---
    # Execute a trivial operation to confirm vec0 works:
    #   CREATE VIRTUAL TABLE IF NOT EXISTS _vec_test USING vec0(test_col float[2])
    #   DROP TABLE _vec_test
    # If this fails, the extension did not load correctly
    pass


def verify_fts5(conn: sqlite3.Connection) -> None:
    """Verify that FTS5 is available in the current SQLite build.

    FTS5 is compiled into Python's bundled SQLite by default, but some
    custom builds may omit it. We check early to provide a clear error.

    Args:
        conn: An open sqlite3.Connection.

    Raises:
        RuntimeError: If FTS5 is not available.
    """
    # --- Step 1: Attempt to create a trivial FTS5 table ---
    # try:
    #   CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_test USING fts5(test_col)
    #   DROP TABLE _fts5_test
    # except sqlite3.OperationalError:
    #   raise RuntimeError with message about FTS5 not being available

    # --- Note: FTS5 is NOT an extension — it's a compile-time option ---
    # No extension loading needed for FTS5
    pass


def load_and_verify_extensions(conn: sqlite3.Connection) -> None:
    """Load sqlite-vec and verify FTS5 availability. Call this once after
    connection setup and before schema initialization.

    Args:
        conn: An open sqlite3.Connection with pragmas already configured.

    Raises:
        RuntimeError: If sqlite-vec or FTS5 is not available.
    """
    # --- Step 1: Load sqlite-vec (must happen before schema init) ---
    # load_sqlite_vec(conn)

    # --- Step 2: Verify FTS5 (must be available for neurons_fts table) ---
    # verify_fts5(conn)
    pass
