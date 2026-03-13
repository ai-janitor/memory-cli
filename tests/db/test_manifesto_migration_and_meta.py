# =============================================================================
# test_manifesto_migration_and_meta.py — Tests for manifesto as store metadata
# =============================================================================
# Purpose:     Verify feature #27: manifesto stored in meta table, seeded on
#              init, accessible via meta manifesto verb, updatable via set.
# Rationale:   The manifesto guides AI agents on storage priorities. It must be
#              present in every store (both new and migrated), independently
#              customizable per store, and accessible via CLI.
# Responsibility:
#   - Test v003 migration adds manifesto to existing stores
#   - Test manifesto is seeded during init bootstrap
#   - Test meta manifesto show returns the manifesto text
#   - Test meta manifesto set updates the manifesto
#   - Test meta manifesto set --file reads from file
# Organization:
#   Test classes grouped by feature area.
#   Fixtures create migrated in-memory DBs at various schema levels.
# =============================================================================

from __future__ import annotations

import pytest
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from memory_cli.db.connection_setup_wal_fk_busy import open_connection
from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as apply_v001
from memory_cli.db.migrations.v002_add_store_fingerprint import apply as apply_v002
from memory_cli.db.migrations.v003_add_manifesto_to_meta import apply as apply_v003, DEFAULT_MANIFESTO
from memory_cli.db.schema_version_reader import read_schema_version
from memory_cli.db.migration_runner_single_transaction import run_pending_migrations

# --- Module-level guard: all tests in this file require sqlite_vec ---
sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec package required for migration tests (vec0 virtual table)",
)


# --- Fixtures ---

@pytest.fixture
def v2_conn():
    """Create an in-memory DB at schema version 2 (before manifesto)."""
    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply_v001(conn)
    conn.execute("COMMIT")
    conn.execute("BEGIN")
    apply_v002(conn)
    conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
    conn.execute("COMMIT")
    yield conn
    conn.close()


@pytest.fixture
def v3_conn():
    """Create an in-memory DB at schema version 3 (with manifesto)."""
    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply_v001(conn)
    conn.execute("COMMIT")
    conn.execute("BEGIN")
    apply_v002(conn)
    conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
    conn.execute("COMMIT")
    conn.execute("BEGIN")
    apply_v003(conn)
    conn.execute("UPDATE meta SET value = '3' WHERE key = 'schema_version'")
    conn.execute("COMMIT")
    yield conn
    conn.close()


# =============================================================================
# Migration v003 tests
# =============================================================================

class TestV003Migration:
    """Test that v003 migration correctly adds manifesto to existing stores."""

    def test_migration_adds_manifesto_key(self, v2_conn):
        """After v003, meta table has a 'manifesto' key."""
        v2_conn.execute("BEGIN")
        apply_v003(v2_conn)
        v2_conn.execute("COMMIT")
        row = v2_conn.execute(
            "SELECT value FROM meta WHERE key = 'manifesto'"
        ).fetchone()
        assert row is not None

    def test_migration_seeds_default_manifesto_text(self, v2_conn):
        """After v003, manifesto value matches DEFAULT_MANIFESTO."""
        v2_conn.execute("BEGIN")
        apply_v003(v2_conn)
        v2_conn.execute("COMMIT")
        row = v2_conn.execute(
            "SELECT value FROM meta WHERE key = 'manifesto'"
        ).fetchone()
        assert row[0] == DEFAULT_MANIFESTO

    def test_migration_is_idempotent(self, v2_conn):
        """Running v003 twice does not error or change the manifesto."""
        v2_conn.execute("BEGIN")
        apply_v003(v2_conn)
        v2_conn.execute("COMMIT")
        # Run again — should not raise
        v2_conn.execute("BEGIN")
        apply_v003(v2_conn)
        v2_conn.execute("COMMIT")
        row = v2_conn.execute(
            "SELECT value FROM meta WHERE key = 'manifesto'"
        ).fetchone()
        assert row[0] == DEFAULT_MANIFESTO

    def test_migration_preserves_custom_manifesto(self, v2_conn):
        """If manifesto was already set (e.g., by init), migration does not overwrite."""
        custom = "My custom manifesto"
        v2_conn.execute(
            "INSERT INTO meta (key, value) VALUES ('manifesto', ?)", (custom,)
        )
        v2_conn.commit()
        v2_conn.execute("BEGIN")
        apply_v003(v2_conn)
        v2_conn.execute("COMMIT")
        row = v2_conn.execute(
            "SELECT value FROM meta WHERE key = 'manifesto'"
        ).fetchone()
        assert row[0] == custom

    def test_runner_migrates_v2_to_v3(self, v2_conn):
        """The migration runner can migrate from v2 to v3."""
        current = read_schema_version(v2_conn)
        assert current == 2
        result = run_pending_migrations(v2_conn, 2, 3)
        assert result is True
        assert read_schema_version(v2_conn) == 3
        row = v2_conn.execute(
            "SELECT value FROM meta WHERE key = 'manifesto'"
        ).fetchone()
        assert row is not None
        assert row[0] == DEFAULT_MANIFESTO

    def test_runner_migrates_v0_to_v3(self):
        """The migration runner can migrate from v0 to v3 (full fresh setup)."""
        conn = open_connection(":memory:")
        load_and_verify_extensions(conn)
        result = run_pending_migrations(conn, 0, 3)
        assert result is True
        assert read_schema_version(conn) == 3
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'manifesto'"
        ).fetchone()
        assert row is not None
        assert row[0] == DEFAULT_MANIFESTO
        conn.close()


# =============================================================================
# Manifesto CLI handler tests
# =============================================================================

class TestManifestoShow:
    """Test `memory meta manifesto` — show the current manifesto."""

    def test_show_returns_default_manifesto(self, v3_conn):
        """Showing manifesto returns the default text."""
        from memory_cli.cli.noun_handlers.meta_noun_handler import handle_manifesto
        with mock.patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_config",
            return_value=(v3_conn, mock.MagicMock()),
        ):
            result = handle_manifesto([], mock.MagicMock())
        assert result.status == "ok"
        assert result.data["manifesto"] == DEFAULT_MANIFESTO

    def test_show_returns_not_found_when_missing(self, v2_conn):
        """Showing manifesto on a store without one returns not_found."""
        from memory_cli.cli.noun_handlers.meta_noun_handler import handle_manifesto
        with mock.patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_config",
            return_value=(v2_conn, mock.MagicMock()),
        ):
            result = handle_manifesto([], mock.MagicMock())
        assert result.status == "not_found"


class TestManifestoSet:
    """Test `memory meta manifesto set` — update the manifesto."""

    def test_set_positional_text(self, v3_conn):
        """Setting manifesto with positional text updates the value."""
        from memory_cli.cli.noun_handlers.meta_noun_handler import handle_manifesto
        new_text = "Store only decisions and corrections."
        with mock.patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_config",
            return_value=(v3_conn, mock.MagicMock()),
        ):
            result = handle_manifesto(["set", new_text], mock.MagicMock())
        assert result.status == "ok"
        assert result.data["updated"] is True
        assert result.data["manifesto"] == new_text
        # Verify in DB
        row = v3_conn.execute(
            "SELECT value FROM meta WHERE key = 'manifesto'"
        ).fetchone()
        assert row[0] == new_text

    def test_set_from_file(self, v3_conn):
        """Setting manifesto from --file reads the file content."""
        from memory_cli.cli.noun_handlers.meta_noun_handler import handle_manifesto
        file_content = "Manifesto loaded from file.\nMultiline content."
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(file_content)
            file_path = f.name
        try:
            with mock.patch(
                "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_config",
                return_value=(v3_conn, mock.MagicMock()),
            ):
                result = handle_manifesto(["set", "--file", file_path], mock.MagicMock())
            assert result.status == "ok"
            assert result.data["manifesto"] == file_content
        finally:
            Path(file_path).unlink()

    def test_set_file_not_found(self, v3_conn):
        """Setting manifesto from non-existent file returns error."""
        from memory_cli.cli.noun_handlers.meta_noun_handler import handle_manifesto
        with mock.patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_config",
            return_value=(v3_conn, mock.MagicMock()),
        ):
            result = handle_manifesto(
                ["set", "--file", "/nonexistent/path.txt"], mock.MagicMock()
            )
        assert result.status == "error"
        assert "not found" in result.error.lower()

    def test_set_no_text_returns_usage_error(self, v3_conn):
        """Calling set without text or --file returns usage error."""
        from memory_cli.cli.noun_handlers.meta_noun_handler import handle_manifesto
        with mock.patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_config",
            return_value=(v3_conn, mock.MagicMock()),
        ):
            result = handle_manifesto(["set"], mock.MagicMock())
        assert result.status == "error"

    def test_set_file_missing_path_returns_error(self, v3_conn):
        """Calling set --file without path returns error."""
        from memory_cli.cli.noun_handlers.meta_noun_handler import handle_manifesto
        with mock.patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_config",
            return_value=(v3_conn, mock.MagicMock()),
        ):
            result = handle_manifesto(["set", "--file"], mock.MagicMock())
        assert result.status == "error"

    def test_unknown_subcommand_returns_error(self, v3_conn):
        """Unknown manifesto subcommand returns error."""
        from memory_cli.cli.noun_handlers.meta_noun_handler import handle_manifesto
        with mock.patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_config",
            return_value=(v3_conn, mock.MagicMock()),
        ):
            result = handle_manifesto(["delete"], mock.MagicMock())
        assert result.status == "error"


class TestManifestoRegistration:
    """Test that manifesto verb is registered in the meta noun."""

    def test_manifesto_in_verb_map(self):
        """The 'manifesto' verb is registered in meta noun verb map."""
        from memory_cli.cli.noun_handlers.meta_noun_handler import _VERB_MAP
        assert "manifesto" in _VERB_MAP

    def test_manifesto_in_verb_descriptions(self):
        """The 'manifesto' verb has a description."""
        from memory_cli.cli.noun_handlers.meta_noun_handler import _VERB_DESCRIPTIONS
        assert "manifesto" in _VERB_DESCRIPTIONS


# =============================================================================
# DEFAULT_MANIFESTO content tests
# =============================================================================

class TestDefaultManifestoContent:
    """Verify the default manifesto contains expected sections."""

    def test_contains_when_to_store(self):
        assert "WHEN TO STORE" in DEFAULT_MANIFESTO

    def test_contains_how_to_store(self):
        assert "HOW TO STORE" in DEFAULT_MANIFESTO

    def test_contains_provenance(self):
        assert "PROVENANCE" in DEFAULT_MANIFESTO

    def test_contains_before_acting(self):
        assert "BEFORE ACTING" in DEFAULT_MANIFESTO

    def test_contains_user_rule_search(self):
        assert "user-rule" in DEFAULT_MANIFESTO

    def test_contains_evolution_note(self):
        assert "This manifesto evolves" in DEFAULT_MANIFESTO

    def test_is_a_guide_not_rules(self):
        assert "not a rule book" in DEFAULT_MANIFESTO
