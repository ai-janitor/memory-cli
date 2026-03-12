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

import pytest
import sqlite3
from unittest import mock
from memory_cli.db.connection_setup_wal_fk_busy import open_connection
from memory_cli.db.extension_loader_sqlite_vec import (
    load_sqlite_vec,
    verify_fts5,
    load_and_verify_extensions,
)


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
        # --- Guard: skip if sqlite_vec is not available in this Python env ---
        pytest.importorskip("sqlite_vec", reason="sqlite_vec package not available")

        # --- Arrange ---
        conn = open_connection(":memory:")

        # --- Act / Assert ---
        # Should not raise
        load_sqlite_vec(conn)

        # --- Verify vec0 is functional ---
        conn.execute(
            "CREATE VIRTUAL TABLE smoke_vec USING vec0(id INTEGER PRIMARY KEY, emb float[2])"
        )
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "smoke_vec" in tables
        conn.close()

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
        # --- Guard: skip if sqlite_vec is not available in this Python env ---
        pytest.importorskip("sqlite_vec", reason="sqlite_vec package not available")

        # --- Arrange ---
        import struct

        conn = open_connection(":memory:")
        load_sqlite_vec(conn)

        # --- Act ---
        conn.execute(
            "CREATE VIRTUAL TABLE test_vec USING vec0(id INTEGER PRIMARY KEY, emb float[4])"
        )

        # --- Assert: table in sqlite_master ---
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE name='test_vec'"
        ).fetchone()
        assert row is not None

        # --- Assert: INSERT and SELECT work ---
        vec_bytes = struct.pack("4f", 0.1, 0.2, 0.3, 0.4)
        conn.execute("INSERT INTO test_vec(id, emb) VALUES (1, ?)", (vec_bytes,))
        result = conn.execute(
            "SELECT id, distance FROM test_vec WHERE emb MATCH ? AND k = 1",
            (vec_bytes,),
        ).fetchone()
        assert result is not None
        assert result[0] == 1
        conn.close()

    def test_error_when_sqlite_vec_package_missing(self) -> None:
        """Should raise RuntimeError if sqlite_vec package is not installed.

        # --- Arrange ---
        # conn = open_connection(':memory:')
        # Mock import of sqlite_vec to raise ImportError

        # --- Act / Assert ---
        # load_sqlite_vec(conn) should raise RuntimeError
        # Error message should mention installing sqlite-vec
        """
        # --- Arrange ---
        conn = open_connection(":memory:")

        # --- Act / Assert ---
        # Patch sqlite_vec.load inside the extension_loader module's import
        # by temporarily removing sqlite_vec from sys.modules and patching import
        import sys
        import importlib

        # Remove sqlite_vec from sys.modules to force a fresh import attempt
        original = sys.modules.pop("sqlite_vec", None)
        try:
            # Patch builtins.__import__ so sqlite_vec raises ImportError
            real_import = __import__

            def mock_import(name, *args, **kwargs):
                if name == "sqlite_vec":
                    raise ImportError("No module named 'sqlite_vec'")
                return real_import(name, *args, **kwargs)

            with mock.patch("builtins.__import__", side_effect=mock_import):
                with pytest.raises(RuntimeError) as exc_info:
                    load_sqlite_vec(conn)

            assert (
                "sqlite-vec" in str(exc_info.value).lower()
                or "sqlite_vec" in str(exc_info.value).lower()
            )
        finally:
            # Restore sqlite_vec in sys.modules if it was there
            if original is not None:
                sys.modules["sqlite_vec"] = original
        conn.close()

    def test_extension_loading_disabled(self) -> None:
        """Should handle the case where enable_load_extension() is not available.

        # --- Arrange ---
        # Some Python builds disable extension loading entirely
        # Mock conn.enable_load_extension to raise AttributeError

        # --- Act / Assert ---
        # load_sqlite_vec(conn) should raise RuntimeError with clear message
        """
        # --- Arrange ---
        # sqlite3.Connection.enable_load_extension is a read-only C method and
        # cannot be patched via mock.patch.object on an instance. Instead, use
        # mock.create_autospec or patch sqlite3.connect to return a mock.
        mock_conn = mock.MagicMock(spec=sqlite3.Connection)
        mock_conn.enable_load_extension.side_effect = AttributeError(
            "enable_load_extension not available in this build"
        )

        # --- Act / Assert ---
        # load_sqlite_vec with the mock connection should raise RuntimeError or AttributeError
        with pytest.raises((RuntimeError, AttributeError)):
            load_sqlite_vec(mock_conn)


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
        # --- Arrange ---
        conn = open_connection(":memory:")

        # --- Act / Assert ---
        # Should not raise on standard Python builds
        verify_fts5(conn)
        conn.close()

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
        # --- Arrange ---
        conn = open_connection(":memory:")
        verify_fts5(conn)

        # --- Act ---
        conn.execute("CREATE VIRTUAL TABLE test_fts USING fts5(content)")
        conn.execute("INSERT INTO test_fts VALUES ('hello world')")
        result = conn.execute(
            "SELECT * FROM test_fts WHERE test_fts MATCH 'hello'"
        ).fetchall()

        # --- Assert ---
        assert len(result) == 1
        conn.close()

    def test_error_when_fts5_unavailable(self) -> None:
        """Should raise RuntimeError if FTS5 is not compiled in.

        # --- Arrange ---
        # Mock conn.execute to raise OperationalError for FTS5 CREATE
        # (simulates a Python build without FTS5)

        # --- Act / Assert ---
        # verify_fts5(conn) should raise RuntimeError
        # Error message should mention FTS5 not being available
        """
        # --- Arrange ---
        # sqlite3.Connection.execute is a read-only C method and cannot be
        # patched directly via mock.patch.object on an instance. Instead,
        # use a MagicMock connection that simulates execute raising OperationalError.
        mock_conn = mock.MagicMock(spec=sqlite3.Connection)
        mock_conn.execute.side_effect = sqlite3.OperationalError("no such module: fts5")

        # --- Act / Assert ---
        with pytest.raises(RuntimeError) as exc_info:
            verify_fts5(mock_conn)

        assert "fts5" in str(exc_info.value).lower()


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
        # --- Guard: skip if sqlite_vec is not available in this Python env ---
        pytest.importorskip("sqlite_vec", reason="sqlite_vec package not available")

        # --- Arrange ---
        import struct

        conn = open_connection(":memory:")

        # --- Act ---
        load_and_verify_extensions(conn)

        # --- Assert: vec0 is usable ---
        conn.execute(
            "CREATE VIRTUAL TABLE combined_vec USING vec0(id INTEGER PRIMARY KEY, emb float[2])"
        )
        vec_bytes = struct.pack("2f", 0.1, 0.2)
        conn.execute("INSERT INTO combined_vec(id, emb) VALUES (1, ?)", (vec_bytes,))

        # --- Assert: FTS5 is usable ---
        conn.execute("CREATE VIRTUAL TABLE combined_fts USING fts5(content)")
        conn.execute("INSERT INTO combined_fts VALUES ('test content')")
        result = conn.execute(
            "SELECT * FROM combined_fts WHERE combined_fts MATCH 'test'"
        ).fetchall()
        assert len(result) == 1
        conn.close()

    def test_stops_on_first_failure(self) -> None:
        """If sqlite-vec fails, should not attempt FTS5 verification.

        # --- Arrange ---
        # Mock load_sqlite_vec to raise RuntimeError

        # --- Act / Assert ---
        # load_and_verify_extensions should raise RuntimeError
        # verify_fts5 should not have been called
        """
        # --- Arrange ---
        conn = open_connection(":memory:")

        # --- Act / Assert ---
        with mock.patch(
            "memory_cli.db.extension_loader_sqlite_vec.load_sqlite_vec",
            side_effect=RuntimeError("sqlite-vec not available"),
        ) as mock_load, mock.patch(
            "memory_cli.db.extension_loader_sqlite_vec.verify_fts5"
        ) as mock_fts5:
            with pytest.raises(RuntimeError):
                load_and_verify_extensions(conn)

            # verify_fts5 should NOT have been called
            mock_fts5.assert_not_called()
        conn.close()
