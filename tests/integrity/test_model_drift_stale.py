# =============================================================================
# test_model_drift_stale.py — Tests for model drift handling
# =============================================================================
# Purpose:     Verify that handle_model_drift correctly warns on stderr,
#              marks vectors as stale in the meta table, updates metadata to
#              the new config values, and that the vector-op blocking logic
#              correctly identifies which operations to block.
# Rationale:   Model drift handling has multiple side effects (stderr, DB write,
#              blocking decision). Each must be tested independently and in
#              combination. Idempotent marking is critical for concurrent agents
#              that may both detect drift on overlapping invocations.
# Responsibility:
#   - Test warning message content and destination (stderr)
#   - Test stale marking writes vectors_marked_stale_at to meta
#   - Test meta update changes embedding_model and embedding_dimensions
#   - Test is_vector_dependent_operation for known vector/non-vector ops
#   - Test idempotent marking (calling twice doesn't corrupt)
#   - Test that batch reembed is NOT blocked (it's the fix)
# Organization:
#   Separate test classes for warning output, stale marking, meta updates,
#   operation blocking, and idempotency. Uses in-memory SQLite with meta table.
# =============================================================================

from __future__ import annotations

import datetime
import pytest
from io import StringIO
from unittest.mock import patch
from memory_cli.integrity.model_drift_stale_vector_marking import (
    handle_model_drift,
    is_vector_dependent_operation,
    _upsert_meta,
    _format_drift_warning,
)


@pytest.fixture
def migrated_conn():
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


class TestDriftWarning:
    """Tests for the stderr warning emitted on model drift."""

    def test_warning_written_to_stderr(self, migrated_conn, capsys) -> None:
        """handle_model_drift should write a warning to stderr.

        # --- Arrange ---
        # Create in-memory DB with meta table
        # Capture stderr

        # --- Act ---
        # handle_model_drift(conn, "old-model.gguf", "new-model.gguf", 768)

        # --- Assert ---
        # stderr output contains "WARNING" or "Embedding model changed"
        """
        handle_model_drift(migrated_conn, "old-model.gguf", "new-model.gguf", 768)
        captured = capsys.readouterr()
        assert "WARNING" in captured.err or "Embedding model" in captured.err

    def test_warning_includes_old_and_new_model(self, migrated_conn, capsys) -> None:
        """Warning should show both the old and new model names.

        # --- Arrange ---
        # Capture stderr

        # --- Act ---
        # handle_model_drift(conn, "nomic-v1.gguf", "bge-small.gguf", 768)

        # --- Assert ---
        # stderr contains "nomic-v1.gguf"
        # stderr contains "bge-small.gguf"
        """
        handle_model_drift(migrated_conn, "nomic-v1.gguf", "bge-small.gguf", 768)
        captured = capsys.readouterr()
        assert "nomic-v1.gguf" in captured.err
        assert "bge-small.gguf" in captured.err

    def test_warning_includes_remediation(self, migrated_conn, capsys) -> None:
        """Warning should tell the user how to fix it.

        # --- Arrange ---
        # Capture stderr

        # --- Act ---
        # handle_model_drift(conn, "old.gguf", "new.gguf", 768)

        # --- Assert ---
        # stderr contains "memory batch reembed" (the fix command)
        """
        handle_model_drift(migrated_conn, "old.gguf", "new.gguf", 768)
        captured = capsys.readouterr()
        assert "memory batch reembed" in captured.err


class TestStaleMarking:
    """Tests for the vectors_marked_stale_at meta write."""

    def test_stale_timestamp_set(self, migrated_conn) -> None:
        """After drift handling, vectors_marked_stale_at should be set.

        # --- Arrange ---
        # Create in-memory DB with meta table (no stale marker)

        # --- Act ---
        # handle_model_drift(conn, "old.gguf", "new.gguf", 768)

        # --- Assert ---
        # SELECT value FROM meta WHERE key = 'vectors_marked_stale_at'
        # Should return a non-None ISO 8601 timestamp
        """
        handle_model_drift(migrated_conn, "old.gguf", "new.gguf", 768)
        row = migrated_conn.execute(
            "SELECT value FROM meta WHERE key = 'vectors_marked_stale_at'"
        ).fetchone()
        assert row is not None
        assert row[0] is not None and len(row[0]) > 0

    def test_stale_timestamp_is_utc_iso8601(self, migrated_conn) -> None:
        """Timestamp should be valid ISO 8601 UTC format.

        # --- Arrange / Act ---
        # handle_model_drift(...)

        # --- Assert ---
        # Parse the timestamp with datetime.fromisoformat()
        # Verify it is timezone-aware (UTC)
        """
        handle_model_drift(migrated_conn, "old.gguf", "new.gguf", 768)
        row = migrated_conn.execute(
            "SELECT value FROM meta WHERE key = 'vectors_marked_stale_at'"
        ).fetchone()
        ts = datetime.datetime.fromisoformat(row[0])
        assert ts.tzinfo is not None

    def test_idempotent_double_marking(self, migrated_conn) -> None:
        """Calling handle_model_drift twice should not corrupt the meta.

        # --- Arrange ---
        # Create DB, call handle_model_drift once

        # --- Act ---
        # Call handle_model_drift again with same or different models

        # --- Assert ---
        # vectors_marked_stale_at is still a valid timestamp
        # embedding_model reflects the LATEST model
        # Only one row per key in meta table
        """
        handle_model_drift(migrated_conn, "old.gguf", "mid.gguf", 768)
        first_ts_row = migrated_conn.execute(
            "SELECT value FROM meta WHERE key = 'vectors_marked_stale_at'"
        ).fetchone()
        first_ts = first_ts_row[0]

        handle_model_drift(migrated_conn, "mid.gguf", "new.gguf", 768)

        # timestamps should be preserved (first call sets it, second call should not overwrite)
        ts_row = migrated_conn.execute(
            "SELECT value FROM meta WHERE key = 'vectors_marked_stale_at'"
        ).fetchone()
        assert ts_row is not None
        assert ts_row[0] == first_ts  # preserved — not overwritten

        # embedding_model should reflect the LATEST model
        model_row = migrated_conn.execute(
            "SELECT value FROM meta WHERE key = 'embedding_model'"
        ).fetchone()
        assert model_row[0] == "new.gguf"

        # Only one row per key
        count = migrated_conn.execute(
            "SELECT COUNT(*) FROM meta WHERE key = 'embedding_model'"
        ).fetchone()[0]
        assert count == 1


class TestMetaUpdates:
    """Tests for updating embedding metadata to new config values."""

    def test_model_name_updated(self, migrated_conn) -> None:
        """embedding_model in meta should be updated to new model.

        # --- Arrange ---
        # Seed meta: embedding_model = "old.gguf"

        # --- Act ---
        # handle_model_drift(conn, "old.gguf", "new.gguf", 768)

        # --- Assert ---
        # meta embedding_model == "new.gguf"
        """
        handle_model_drift(migrated_conn, "old.gguf", "new.gguf", 768)
        row = migrated_conn.execute(
            "SELECT value FROM meta WHERE key = 'embedding_model'"
        ).fetchone()
        assert row[0] == "new.gguf"

    def test_dimensions_updated(self, migrated_conn) -> None:
        """embedding_dimensions in meta should be updated to new config dims.

        # --- Arrange ---
        # Seed meta: embedding_dimensions = "768"

        # --- Act ---
        # handle_model_drift(conn, "old.gguf", "new.gguf", 384)

        # --- Assert ---
        # meta embedding_dimensions == "384"
        """
        handle_model_drift(migrated_conn, "old.gguf", "new.gguf", 384)
        row = migrated_conn.execute(
            "SELECT value FROM meta WHERE key = 'embedding_dimensions'"
        ).fetchone()
        assert row[0] == "384"

    def test_changes_committed(self, tmp_path) -> None:
        """Meta changes should be committed, not left in an open transaction.

        # --- Arrange ---
        # Create DB

        # --- Act ---
        # handle_model_drift(conn, "old.gguf", "new.gguf", 768)
        # Open a SECOND connection to same DB

        # --- Assert ---
        # Second connection can read the updated meta values
        # (proves commit happened, not just in-transaction visibility)
        """
        import sqlite3
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
        from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply

        db_file = tmp_path / "test.db"
        conn = open_connection(str(db_file))
        load_and_verify_extensions(conn)
        conn.execute("BEGIN")
        apply(conn)
        conn.execute("COMMIT")

        handle_model_drift(conn, "old.gguf", "committed.gguf", 768)
        conn.close()

        # Open a second connection to verify commit
        conn2 = sqlite3.connect(str(db_file))
        row = conn2.execute(
            "SELECT value FROM meta WHERE key = 'embedding_model'"
        ).fetchone()
        conn2.close()
        assert row is not None
        assert row[0] == "committed.gguf"


class TestVectorOperationBlocking:
    """Tests for is_vector_dependent_operation."""

    def test_neuron_search_is_blocked(self) -> None:
        """neuron search depends on vectors and should be blocked.

        # --- Act / Assert ---
        # is_vector_dependent_operation("neuron", "search") == True
        """
        assert is_vector_dependent_operation("neuron", "search") is True

    def test_neuron_find_is_blocked(self) -> None:
        """neuron find (search alias) depends on vectors.

        # --- Act / Assert ---
        # is_vector_dependent_operation("neuron", "find") == True
        """
        assert is_vector_dependent_operation("neuron", "find") is True

    def test_neuron_add_is_not_blocked(self) -> None:
        """neuron add does not require vector search.

        # --- Act / Assert ---
        # is_vector_dependent_operation("neuron", "add") == False
        """
        assert is_vector_dependent_operation("neuron", "add") is False

    def test_edge_add_is_not_blocked(self) -> None:
        """Edge operations do not depend on vectors.

        # --- Act / Assert ---
        # is_vector_dependent_operation("edge", "add") == False
        """
        assert is_vector_dependent_operation("edge", "add") is False

    def test_meta_stats_is_not_blocked(self) -> None:
        """Meta commands do not depend on vectors.

        # --- Act / Assert ---
        # is_vector_dependent_operation("meta", "stats") == False
        """
        assert is_vector_dependent_operation("meta", "stats") is False

    def test_batch_reembed_is_not_blocked(self) -> None:
        """batch reembed should NOT be blocked — it is the fix for drift.

        # --- Act / Assert ---
        # is_vector_dependent_operation("batch", "reembed") == False
        """
        assert is_vector_dependent_operation("batch", "reembed") is False


class TestUpsertMeta:
    """Tests for the _upsert_meta helper."""

    def test_insert_new_key(self, migrated_conn) -> None:
        """_upsert_meta should insert a new key-value pair.

        # --- Arrange ---
        # (use migrated DB — key doesn't exist)

        # --- Act ---
        # _upsert_meta(conn, "new_key", "new_value")

        # --- Assert ---
        # SELECT value FROM meta WHERE key = 'new_key' → "new_value"
        """
        _upsert_meta(migrated_conn, "new_upsert_key", "new_value")
        row = migrated_conn.execute(
            "SELECT value FROM meta WHERE key = 'new_upsert_key'"
        ).fetchone()
        assert row is not None
        assert row[0] == "new_value"

    def test_update_existing_key(self, migrated_conn) -> None:
        """_upsert_meta should overwrite an existing key.

        # --- Arrange ---
        # Seed meta: ("my_key", "old_value")

        # --- Act ---
        # _upsert_meta(conn, "my_key", "new_value")

        # --- Assert ---
        # SELECT value FROM meta WHERE key = 'my_key' → "new_value"
        # Only one row with key = 'my_key'
        """
        migrated_conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('my_key', 'old_value')")
        _upsert_meta(migrated_conn, "my_key", "new_value")
        row = migrated_conn.execute(
            "SELECT value FROM meta WHERE key = 'my_key'"
        ).fetchone()
        assert row[0] == "new_value"
        count = migrated_conn.execute(
            "SELECT COUNT(*) FROM meta WHERE key = 'my_key'"
        ).fetchone()[0]
        assert count == 1
