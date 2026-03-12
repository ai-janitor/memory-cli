# =============================================================================
# test_extension_loader.py — Tests for sqlite-vec and FTS5 extension loading
# =============================================================================
# Purpose:     Verify that sqlite-vec loads correctly, vec0 tables can be
#              created, FTS5 is available, and error handling works when
#              extensions are missing or fail to load.
# Rationale:   Extension loading is the most fragile part of the DB init
#              sequence — binary compatibility, missing packages, and disabled
#              extension loading can all cause silent failures. Tests must
#              verify actual functionality, not just that the call didn't crash.
# Responsibility:
#   - Test successful sqlite-vec loading and vec0 table creation
#   - Test FTS5 availability verification
#   - Test error handling when sqlite-vec package is missing (mocked)
#   - Test error handling when extension loading is disabled (mocked)
#   - Test the combined load_and_verify_extensions() function
# Organization:
#   Pytest functions grouped by extension type.
#   Uses monkeypatch/mock for error path testing.
# =============================================================================

from __future__ import annotations

# import pytest
# import sqlite3
# from unittest import mock
# from memory_cli.db.connection_setup_wal_fk_busy import open_connection
# from memory_cli.db.extension_loader_sqlite_vec import (
#     load_sqlite_vec,
#     verify_fts5,
#     load_and_verify_extensions,
# )


class TestSqliteVecLoading:
    """Tests for sqlite-vec extension loading."""

    def test_sqlite_vec_loads_successfully(self) -> None:
        """sqlite-vec should load without error on a fresh connection.

        # --- Arrange ---
        # conn = open_connection(':memory:')

        # --- Act ---
        # load_sqlite_vec(conn)

        # --- Assert ---
        # No exception raised
        # Verify by creating a trivial vec0 table
        """
        pass

    def test_vec0_table_creation_after_load(self) -> None:
        """After loading sqlite-vec, vec0 virtual tables should be creatable.

        # --- Arrange ---
        # conn = open_connection(':memory:')
        # load_sqlite_vec(conn)

        # --- Act ---
        # conn.execute('CREATE VIRTUAL TABLE test_vec USING vec0(
        #   id INTEGER PRIMARY KEY, emb float[4])')

        # --- Assert ---
        # Table exists in sqlite_master
        # INSERT and SELECT work on the vec0 table
        """
        pass

    def test_error_when_sqlite_vec_package_missing(self) -> None:
        """Should raise RuntimeError if sqlite_vec package is not installed.

        # --- Arrange ---
        # conn = open_connection(':memory:')
        # Mock import of sqlite_vec to raise ImportError

        # --- Act / Assert ---
        # load_sqlite_vec(conn) should raise RuntimeError
        # Error message should mention installing sqlite-vec
        """
        pass

    def test_extension_loading_disabled(self) -> None:
        """Should handle the case where enable_load_extension() is not available.

        # --- Arrange ---
        # Some Python builds disable extension loading entirely
        # Mock conn.enable_load_extension to raise AttributeError

        # --- Act / Assert ---
        # load_sqlite_vec(conn) should raise RuntimeError with clear message
        """
        pass


class TestFTS5Verification:
    """Tests for FTS5 availability check."""

    def test_fts5_available(self) -> None:
        """FTS5 should be available in standard Python SQLite builds.

        # --- Arrange ---
        # conn = open_connection(':memory:')

        # --- Act ---
        # verify_fts5(conn)

        # --- Assert ---
        # No exception raised
        """
        pass

    def test_fts5_table_creation(self) -> None:
        """FTS5 tables should be creatable after verification.

        # --- Arrange ---
        # conn = open_connection(':memory:')
        # verify_fts5(conn)

        # --- Act ---
        # conn.execute("CREATE VIRTUAL TABLE test_fts USING fts5(content)")
        # conn.execute("INSERT INTO test_fts VALUES ('hello world')")
        # result = conn.execute(
        #   "SELECT * FROM test_fts WHERE test_fts MATCH 'hello'").fetchall()

        # --- Assert ---
        # result should have 1 row
        """
        pass

    def test_error_when_fts5_unavailable(self) -> None:
        """Should raise RuntimeError if FTS5 is not compiled in.

        # --- Arrange ---
        # Mock conn.execute to raise OperationalError for FTS5 CREATE
        # (simulates a Python build without FTS5)

        # --- Act / Assert ---
        # verify_fts5(conn) should raise RuntimeError
        # Error message should mention FTS5 not being available
        """
        pass


class TestCombinedLoader:
    """Tests for the combined load_and_verify_extensions() function."""

    def test_both_extensions_loaded(self) -> None:
        """load_and_verify_extensions should load sqlite-vec and verify FTS5.

        # --- Arrange ---
        # conn = open_connection(':memory:')

        # --- Act ---
        # load_and_verify_extensions(conn)

        # --- Assert ---
        # Both vec0 and FTS5 should be usable on the connection
        """
        pass

    def test_stops_on_first_failure(self) -> None:
        """If sqlite-vec fails, should not attempt FTS5 verification.

        # --- Arrange ---
        # Mock load_sqlite_vec to raise RuntimeError

        # --- Act / Assert ---
        # load_and_verify_extensions should raise RuntimeError
        # verify_fts5 should not have been called
        """
        pass
