# =============================================================================
# FILE: tests/cli/test_neuron_full_flag.py
# PURPOSE: Test --full flag on neuron get, list, search handlers.
#          Verifies: --full surfaces access_count, last_accessed_at, updated_at,
#          status; lean output unchanged; --full == --verbose.
# Rationale: Task 74 — read-only output change that surfaces fields already
#   present in DB but hidden by lean filter. Tests guard against regression
#   (lean must stay lean) and correct field exposure in full mode.
# Organization:
#   1. Fixtures
#   2. handle_get tests — --full exposes fields, lean unchanged, --full==--verbose
#   3. handle_list tests — same
# =============================================================================

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec required for full schema (vec0 table)"
)

# Fields that must appear in full/verbose mode but NOT in lean mode
_FULL_ONLY_FIELDS = {"access_count", "last_accessed_at"}
# Fields that must appear in BOTH lean and full modes
_LEAN_FIELDS = {"id", "content", "tags", "created_at", "source", "edges"}


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """In-memory SQLite with full migrated schema."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as apply_v001
    from memory_cli.db.migrations.v004_add_access_tracking import apply as apply_v004

    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply_v001(conn)
    conn.execute("COMMIT")
    conn.execute("BEGIN")
    apply_v004(conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


@pytest.fixture
def global_flags():
    """Minimal global_flags stub — no DB path override."""
    return SimpleNamespace(db=None, global_=False, store=None)


def _insert_neuron(conn, content="test content"):
    """Insert a neuron and return its raw integer ID."""
    now_ms = int(time.time() * 1000)
    cursor = conn.execute(
        """INSERT INTO neurons (content, created_at, updated_at, project, source, status)
           VALUES (?, ?, ?, ?, NULL, 'active')""",
        (content, now_ms, now_ms, "test-project"),
    )
    conn.commit()
    return cursor.lastrowid


def _make_connections(conn):
    """Return a [(conn, 'LOCAL')] list matching get_layered_connections output."""
    return [(conn, "LOCAL")]


# -----------------------------------------------------------------------------
# handle_get — --full flag
# -----------------------------------------------------------------------------

class TestHandleGetFullFlag:
    """Test --full flag on neuron get handler."""

    def test_full_flag_exposes_access_count(self, migrated_conn, global_flags):
        """--full output includes access_count."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_get

        nid = _insert_neuron(migrated_conn, content="full flag test")
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=_make_connections(migrated_conn),
        ):
            result = handle_get([str(nid), "--full"], global_flags)

        assert result.status == "ok"
        assert "access_count" in result.data

    def test_full_flag_exposes_last_accessed_at(self, migrated_conn, global_flags):
        """--full output includes last_accessed_at."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_get

        nid = _insert_neuron(migrated_conn, content="full flag test 2")
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=_make_connections(migrated_conn),
        ):
            result = handle_get([str(nid), "--full"], global_flags)

        assert result.status == "ok"
        assert "last_accessed_at" in result.data

    def test_full_flag_exposes_updated_at(self, migrated_conn, global_flags):
        """--full output includes updated_at."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_get

        nid = _insert_neuron(migrated_conn, content="full flag updated_at")
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=_make_connections(migrated_conn),
        ):
            result = handle_get([str(nid), "--full"], global_flags)

        assert result.status == "ok"
        assert "updated_at" in result.data

    def test_full_flag_exposes_status(self, migrated_conn, global_flags):
        """--full output includes status."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_get

        nid = _insert_neuron(migrated_conn, content="full flag status")
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=_make_connections(migrated_conn),
        ):
            result = handle_get([str(nid), "--full"], global_flags)

        assert result.status == "ok"
        assert "status" in result.data

    def test_lean_output_lacks_access_count(self, migrated_conn, global_flags):
        """Default (lean) output does NOT include access_count."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_get

        nid = _insert_neuron(migrated_conn, content="lean test")
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=_make_connections(migrated_conn),
        ):
            result = handle_get([str(nid)], global_flags)

        assert result.status == "ok"
        assert "access_count" not in result.data

    def test_lean_output_lacks_last_accessed_at(self, migrated_conn, global_flags):
        """Default (lean) output does NOT include last_accessed_at."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_get

        nid = _insert_neuron(migrated_conn, content="lean test 2")
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=_make_connections(migrated_conn),
        ):
            result = handle_get([str(nid)], global_flags)

        assert result.status == "ok"
        assert "last_accessed_at" not in result.data

    def test_lean_output_retains_lean_fields(self, migrated_conn, global_flags):
        """Default output retains all expected lean fields."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_get

        nid = _insert_neuron(migrated_conn, content="lean fields check")
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=_make_connections(migrated_conn),
        ):
            result = handle_get([str(nid)], global_flags)

        assert result.status == "ok"
        for field in ("id", "content", "tags", "created_at", "source"):
            assert field in result.data, f"lean field missing: {field}"

    def test_full_equals_verbose_for_get(self, migrated_conn, global_flags):
        """--full and --verbose produce identical output for get."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_get

        nid = _insert_neuron(migrated_conn, content="full vs verbose")
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=_make_connections(migrated_conn),
        ):
            r_full = handle_get([str(nid), "--full"], global_flags)
            r_verbose = handle_get([str(nid), "--verbose"], global_flags)

        assert r_full.status == r_verbose.status == "ok"
        # Keys must be identical
        assert set(r_full.data.keys()) == set(r_verbose.data.keys())


# -----------------------------------------------------------------------------
# handle_list — --full flag
# -----------------------------------------------------------------------------

class TestHandleListFullFlag:
    """Test --full flag on neuron list handler."""

    def test_full_flag_exposes_access_count_in_list(self, migrated_conn, global_flags):
        """--full list output includes access_count on each item."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_list

        _insert_neuron(migrated_conn, content="list full test")
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=_make_connections(migrated_conn),
        ):
            result = handle_list(["--full"], global_flags)

        assert result.status == "ok"
        assert len(result.data) >= 1
        assert "access_count" in result.data[0]

    def test_full_flag_exposes_last_accessed_at_in_list(self, migrated_conn, global_flags):
        """--full list output includes last_accessed_at on each item."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_list

        _insert_neuron(migrated_conn, content="list full test 2")
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=_make_connections(migrated_conn),
        ):
            result = handle_list(["--full"], global_flags)

        assert result.status == "ok"
        assert "last_accessed_at" in result.data[0]

    def test_lean_list_lacks_access_count(self, migrated_conn, global_flags):
        """Default list output does NOT include access_count."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_list

        _insert_neuron(migrated_conn, content="lean list test")
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=_make_connections(migrated_conn),
        ):
            result = handle_list([], global_flags)

        assert result.status == "ok"
        assert len(result.data) >= 1
        assert "access_count" not in result.data[0]

    def test_full_equals_verbose_for_list(self, migrated_conn, global_flags):
        """--full and --verbose produce identical key sets for list."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_list

        _insert_neuron(migrated_conn, content="list full vs verbose")
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=_make_connections(migrated_conn),
        ):
            r_full = handle_list(["--full"], global_flags)
            r_verbose = handle_list(["--verbose"], global_flags)

        assert r_full.status == r_verbose.status == "ok"
        assert len(r_full.data) == len(r_verbose.data)
        if r_full.data:
            assert set(r_full.data[0].keys()) == set(r_verbose.data[0].keys())
