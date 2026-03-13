# =============================================================================
# Module: test_edge_add_cli_positional_reason.py
# Purpose: Test that handle_add() in edge_noun_handler correctly accepts
#   an optional 3rd positional argument as the edge reason/type.
# Rationale: Bug #26 — `memory edge add A B enables` silently dropped
#   the "enables" positional and defaulted to "related_to". This test
#   verifies the fix: unflagged 3rd positional is used as reason when
#   --type is not provided. --type flag still takes precedence.
# Responsibility:
#   - Test 3rd positional used as reason
#   - Test --type flag still works
#   - Test --type flag takes precedence over positional
#   - Test default "related_to" when neither provided
# Organization: Single test class, uses monkeypatching to isolate arg parsing
# =============================================================================

from __future__ import annotations

import pytest

# --- Module-level guard: all tests in this file require sqlite_vec ---
sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec required for full schema (vec0 table)"
)


@pytest.fixture
def migrated_conn():
    """In-memory SQLite with full migrated schema including neurons_vec."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply

    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply(conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


def _create_test_neuron(conn, content="test content", project="test-project"):
    import time
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) VALUES (?, ?, ?, ?, 'active')",
        (content, now_ms, now_ms, project)
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


class TestEdgeAddPositionalReason:
    """Test that handle_add() correctly parses the optional 3rd positional as reason."""

    def test_positional_reason_used_when_no_type_flag(self, migrated_conn, monkeypatch):
        """memory edge add A B enables -> reason='enables'

        Bug #26: the 3rd positional was silently dropped, defaulting to 'related_to'.
        After fix, it should be used as the reason.
        """
        from memory_cli.cli.noun_handlers import edge_noun_handler

        src = _create_test_neuron(migrated_conn, "source")
        tgt = _create_test_neuron(migrated_conn, "target")

        # Monkeypatch get_connection_and_scope to return our test connection
        monkeypatch.setattr(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            lambda gf: [(migrated_conn, "LOCAL")],
        )

        result = edge_noun_handler.handle_add(
            [str(src), str(tgt), "enables"], type("Flags", (), {"config": None, "db": None})()
        )

        assert result.status == "ok", f"Expected ok, got {result.status}: {getattr(result, 'error', '')}"
        assert result.data["reason"] == "enables"

    def test_type_flag_still_works(self, migrated_conn, monkeypatch):
        """memory edge add A B --type enables -> reason='enables'"""
        from memory_cli.cli.noun_handlers import edge_noun_handler

        src = _create_test_neuron(migrated_conn, "source2")
        tgt = _create_test_neuron(migrated_conn, "target2")

        monkeypatch.setattr(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            lambda gf: [(migrated_conn, "LOCAL")],
        )

        result = edge_noun_handler.handle_add(
            [str(src), str(tgt), "--type", "enables"], type("Flags", (), {"config": None, "db": None})()
        )

        assert result.status == "ok"
        assert result.data["reason"] == "enables"

    def test_type_flag_takes_precedence_over_positional(self, migrated_conn, monkeypatch):
        """memory edge add A B enables --type overrides -> reason='overrides'"""
        from memory_cli.cli.noun_handlers import edge_noun_handler

        src = _create_test_neuron(migrated_conn, "source3")
        tgt = _create_test_neuron(migrated_conn, "target3")

        monkeypatch.setattr(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            lambda gf: [(migrated_conn, "LOCAL")],
        )

        result = edge_noun_handler.handle_add(
            [str(src), str(tgt), "enables", "--type", "overrides"], type("Flags", (), {"config": None, "db": None})()
        )

        assert result.status == "ok"
        assert result.data["reason"] == "overrides"

    def test_default_reason_when_no_positional_no_flag(self, migrated_conn, monkeypatch):
        """memory edge add A B -> reason='related_to' (default)"""
        from memory_cli.cli.noun_handlers import edge_noun_handler

        src = _create_test_neuron(migrated_conn, "source4")
        tgt = _create_test_neuron(migrated_conn, "target4")

        monkeypatch.setattr(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            lambda gf: [(migrated_conn, "LOCAL")],
        )

        result = edge_noun_handler.handle_add(
            [str(src), str(tgt)], type("Flags", (), {"config": None, "db": None})()
        )

        assert result.status == "ok"
        assert result.data["reason"] == "related_to"
