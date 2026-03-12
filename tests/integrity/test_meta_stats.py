# =============================================================================
# test_meta_stats.py — Tests for `memory meta stats` command
# =============================================================================
# Purpose:     Verify that gather_meta_stats returns all expected fields with
#              correct values for various DB states: empty, populated, stale,
#              drifted.
# Rationale:   Meta stats is the primary diagnostic tool for operators and
#              agents. If any field is missing, wrong type, or incorrect value,
#              downstream tooling (monitoring, alerting, agent decisions) will
#              make bad choices. Every field must be tested.
# Responsibility:
#   - Test all 17 fields are present in the returned dict
#   - Test correct values for an empty DB (freshly initialized)
#   - Test correct values for a populated DB (neurons, vectors, edges, tags)
#   - Test correct values when vectors are marked stale
#   - Test drift_detected flag when config doesn't match DB
#   - Test db_size_bytes and db_path resolution
# Organization:
#   Test classes for field presence, empty DB, populated DB, stale state,
#   and drift detection. Uses in-memory SQLite with schema applied.
# =============================================================================

from __future__ import annotations

import struct
import time
import pytest
from pathlib import Path
from memory_cli.integrity.meta_stats_db_summary import (
    gather_meta_stats,
    _read_meta,
    _read_schema_version,
    _count_rows,
    _count_vectors,
    _count_stale_vectors,
    _count_never_embedded,
)

EXPECTED_FIELDS = {
    "db_path", "db_size_bytes", "schema_version",
    "embedding_model_name", "embedding_dimensions",
    "config_model_name", "config_dimensions",
    "drift_detected", "vectors_stale", "vectors_stale_since",
    "neuron_count", "vector_count", "stale_vector_count",
    "never_embedded_count", "tag_count", "edge_count",
    "last_integrity_check_at",
}


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


@pytest.fixture
def config():
    return {
        "embedding": {
            "model_path": "/path/to/nomic-embed-text-v1.5.Q8_0.gguf",
            "dimensions": 768,
            "n_ctx": 2048,
        }
    }


def _insert_neuron(conn, content: str = "test content", project: str = "test") -> int:
    """Helper: insert a neuron and return its ID."""
    ts = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project) VALUES (?,?,?,?)",
        (content, ts, ts, project),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _insert_vector(conn, neuron_id: int, dims: int = 768) -> None:
    """Helper: insert a vector for a neuron."""
    vec = struct.pack(f"{dims}f", *([0.1] * dims))
    conn.execute(
        "INSERT OR REPLACE INTO neurons_vec (neuron_id, embedding) VALUES (?, ?)",
        (neuron_id, vec),
    )


class TestFieldPresence:
    """Tests that all expected fields are present in the output."""

    def test_all_17_fields_present(self, migrated_conn, config) -> None:
        """gather_meta_stats should return a dict with exactly 17 keys.

        # --- Arrange ---
        # Create in-memory DB with full schema
        # Minimal config dict

        # --- Act ---
        # stats = gather_meta_stats(conn, config, ":memory:")

        # --- Assert ---
        # All 17 keys present
        """
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert set(stats.keys()) == EXPECTED_FIELDS

    def test_fields_are_correct_types(self, migrated_conn, config) -> None:
        """Each field should have the expected Python type.

        # --- Arrange ---
        # Create populated DB

        # --- Act ---
        # stats = gather_meta_stats(conn, config, db_path)

        # --- Assert ---
        # Check types for all fields
        """
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert isinstance(stats["db_path"], str)
        assert isinstance(stats["db_size_bytes"], int)
        assert isinstance(stats["schema_version"], int)
        # embedding_model_name and embedding_dimensions are None when 'default'
        assert stats["embedding_model_name"] is None or isinstance(stats["embedding_model_name"], str)
        assert stats["embedding_dimensions"] is None or isinstance(stats["embedding_dimensions"], int)
        assert isinstance(stats["config_model_name"], str)
        assert isinstance(stats["config_dimensions"], int)
        assert isinstance(stats["drift_detected"], bool)
        assert isinstance(stats["vectors_stale"], bool)
        assert stats["vectors_stale_since"] is None or isinstance(stats["vectors_stale_since"], str)
        assert isinstance(stats["neuron_count"], int)
        assert isinstance(stats["vector_count"], int)
        assert isinstance(stats["stale_vector_count"], int)
        assert isinstance(stats["never_embedded_count"], int)
        assert isinstance(stats["tag_count"], int)
        assert isinstance(stats["edge_count"], int)
        assert stats["last_integrity_check_at"] is None or isinstance(stats["last_integrity_check_at"], str)


class TestEmptyDB:
    """Tests for stats from a freshly initialized, empty database."""

    def test_empty_db_zero_counts(self, migrated_conn, config) -> None:
        """All entity counts should be 0 for an empty DB.

        # --- Arrange ---
        # Create in-memory DB with schema applied but no data

        # --- Act ---
        # stats = gather_meta_stats(conn, config, ":memory:")

        # --- Assert ---
        # neuron_count == 0, vector_count == 0, etc.
        """
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert stats["neuron_count"] == 0
        assert stats["vector_count"] == 0
        assert stats["stale_vector_count"] == 0
        assert stats["never_embedded_count"] == 0
        assert stats["tag_count"] == 0
        assert stats["edge_count"] == 0

    def test_empty_db_no_embedding_metadata(self, migrated_conn, config) -> None:
        """Empty DB should have None for embedding metadata (migration seeds 'default').

        # --- Assert ---
        # embedding_model_name is None (because 'default' is treated as not-set)
        # embedding_dimensions is None or 768 depending on treatment
        """
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert stats["embedding_model_name"] is None

    def test_empty_db_no_drift(self, migrated_conn, config) -> None:
        """Empty DB has no real vectors, so drift_detected should be False.

        # --- Assert ---
        # drift_detected == False (embedding_model_name is None → no comparison)
        """
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert stats["drift_detected"] is False

    def test_empty_db_not_stale(self, migrated_conn, config) -> None:
        """Empty DB should have vectors_stale == False.

        # --- Assert ---
        # vectors_stale == False
        # vectors_stale_since is None
        """
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert stats["vectors_stale"] is False
        assert stats["vectors_stale_since"] is None


class TestPopulatedDB:
    """Tests for stats from a DB with actual content."""

    def test_neuron_count_accurate(self, migrated_conn, config) -> None:
        """neuron_count should match actual row count in neurons table.

        # --- Arrange ---
        # Insert 5 neurons

        # --- Act ---
        # stats = gather_meta_stats(conn, config, db_path)

        # --- Assert ---
        # stats["neuron_count"] == 5
        """
        for i in range(5):
            _insert_neuron(migrated_conn, f"content {i}")
        migrated_conn.commit()
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert stats["neuron_count"] == 5

    def test_vector_count_accurate(self, migrated_conn, config) -> None:
        """vector_count should match neurons that have vectors.

        # --- Arrange ---
        # Insert 5 neurons, 3 with vectors

        # --- Act ---
        # stats = gather_meta_stats(conn, config, db_path)

        # --- Assert ---
        # stats["vector_count"] == 3
        """
        nids = [_insert_neuron(migrated_conn, f"content {i}") for i in range(5)]
        for nid in nids[:3]:
            _insert_vector(migrated_conn, nid)
        migrated_conn.commit()
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert stats["vector_count"] == 3

    def test_never_embedded_count(self, migrated_conn, config) -> None:
        """never_embedded_count = neurons without vectors.

        # --- Arrange ---
        # Insert 5 neurons, 3 with vectors → 2 never embedded

        # --- Assert ---
        # stats["never_embedded_count"] == 2
        """
        nids = [_insert_neuron(migrated_conn, f"content {i}") for i in range(5)]
        for nid in nids[:3]:
            _insert_vector(migrated_conn, nid)
        migrated_conn.commit()
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert stats["never_embedded_count"] == 2

    def test_tag_and_edge_counts(self, migrated_conn, config) -> None:
        """Tag and edge counts should match actual row counts.

        # --- Arrange ---
        # Insert tags and edges

        # --- Assert ---
        # stats["tag_count"] and stats["edge_count"] match
        """
        ts = int(time.time() * 1000)
        # Insert tags
        migrated_conn.execute("INSERT INTO tags (name, created_at) VALUES ('alpha', ?)", (ts,))
        migrated_conn.execute("INSERT INTO tags (name, created_at) VALUES ('beta', ?)", (ts,))
        # Insert neurons for edges
        n1 = _insert_neuron(migrated_conn, "neuron 1")
        n2 = _insert_neuron(migrated_conn, "neuron 2")
        migrated_conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, created_at) VALUES (?,?,?,?)",
            (n1, n2, "related", ts),
        )
        migrated_conn.commit()
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert stats["tag_count"] == 2
        assert stats["edge_count"] == 1

    def test_config_values_from_config_dict(self, migrated_conn, config) -> None:
        """config_model_name and config_dimensions come from config, not DB.

        # --- Arrange ---
        # config = {"embedding": {"model_path": "/path/to/nomic-embed-text-v1.5.Q8_0.gguf", "dimensions": 768}}

        # --- Assert ---
        # stats["config_model_name"] == "nomic-embed-text-v1.5.Q8_0.gguf" (basename extracted)
        # stats["config_dimensions"] == 768
        """
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert stats["config_model_name"] == "nomic-embed-text-v1.5.Q8_0.gguf"
        assert stats["config_dimensions"] == 768


class TestStaleState:
    """Tests for stats when vectors are marked stale."""

    def test_stale_flag_true(self, migrated_conn, config) -> None:
        """vectors_stale should be True when vectors_marked_stale_at is set.

        # --- Arrange ---
        # Set vectors_marked_stale_at in meta

        # --- Assert ---
        # stats["vectors_stale"] == True
        """
        migrated_conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('vectors_marked_stale_at', '2025-06-01T00:00:00+00:00')"
        )
        migrated_conn.commit()
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert stats["vectors_stale"] is True

    def test_stale_since_timestamp(self, migrated_conn, config) -> None:
        """vectors_stale_since should contain the timestamp.

        # --- Arrange ---
        # Set vectors_marked_stale_at = "2025-06-01T00:00:00+00:00"

        # --- Assert ---
        # stats["vectors_stale_since"] == "2025-06-01T00:00:00+00:00"
        """
        migrated_conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('vectors_marked_stale_at', '2025-06-01T00:00:00+00:00')"
        )
        migrated_conn.commit()
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert stats["vectors_stale_since"] == "2025-06-01T00:00:00+00:00"

    def test_stale_vector_count_equals_total(self, migrated_conn, config) -> None:
        """When stale, stale_vector_count should equal total vector_count.

        # --- Arrange ---
        # DB with 5 vectors, vectors_marked_stale_at set

        # --- Assert ---
        # stats["stale_vector_count"] == stats["vector_count"] == 5
        """
        nids = [_insert_neuron(migrated_conn, f"content {i}") for i in range(5)]
        for nid in nids:
            _insert_vector(migrated_conn, nid)
        migrated_conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('vectors_marked_stale_at', '2025-06-01T00:00:00+00:00')"
        )
        migrated_conn.commit()
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert stats["vector_count"] == 5
        assert stats["stale_vector_count"] == 5


class TestDriftDetection:
    """Tests for the drift_detected flag in stats output."""

    def test_drift_detected_model_mismatch(self, migrated_conn, config) -> None:
        """drift_detected should be True when DB model != config model.

        # --- Arrange ---
        # DB meta: embedding_model = "old.gguf"
        # Config: embedding_model = "nomic-embed-text-v1.5.Q8_0.gguf"

        # --- Assert ---
        # stats["drift_detected"] == True
        """
        migrated_conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('embedding_model', 'old.gguf')"
        )
        migrated_conn.commit()
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert stats["drift_detected"] is True

    def test_drift_detected_dimension_mismatch(self, migrated_conn) -> None:
        """drift_detected should be True when DB dims != config dims.

        # --- Arrange ---
        # DB meta: embedding_dimensions = "768"
        # Config: embedding_dimensions = 384

        # --- Assert ---
        # stats["drift_detected"] == True
        """
        migrated_conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('embedding_model', 'nomic-embed-text-v1.5.Q8_0.gguf')"
        )
        migrated_conn.commit()
        config_diff_dims = {
            "embedding": {
                "model_path": "/path/to/nomic-embed-text-v1.5.Q8_0.gguf",
                "dimensions": 384,
            }
        }
        stats = gather_meta_stats(migrated_conn, config_diff_dims, ":memory:")
        assert stats["drift_detected"] is True

    def test_no_drift_when_matching(self, migrated_conn, config) -> None:
        """drift_detected should be False when DB matches config.

        # --- Arrange ---
        # DB and config both: model = "nomic-embed-text-v1.5.Q8_0.gguf", dims = 768

        # --- Assert ---
        # stats["drift_detected"] == False
        """
        migrated_conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('embedding_model', 'nomic-embed-text-v1.5.Q8_0.gguf')"
        )
        migrated_conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('embedding_dimensions', '768')"
        )
        migrated_conn.commit()
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert stats["drift_detected"] is False

    def test_no_drift_when_no_metadata(self, migrated_conn, config) -> None:
        """drift_detected should be False when no real embedding metadata exists.

        # --- Arrange ---
        # DB with migration default ('default') — no vectors written

        # --- Assert ---
        # stats["drift_detected"] == False
        """
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert stats["drift_detected"] is False


class TestDbPathAndSize:
    """Tests for db_path and db_size_bytes fields."""

    def test_db_path_is_string(self, migrated_conn, config) -> None:
        """db_path should be a string.

        # --- Assert ---
        # stats["db_path"] is a string
        """
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert isinstance(stats["db_path"], str)

    def test_db_size_bytes_for_file_db(self, tmp_path, config) -> None:
        """db_size_bytes should reflect actual file size for file-based DB.

        # --- Arrange ---
        # Create a file-based DB with some data

        # --- Assert ---
        # stats["db_size_bytes"] > 0
        """
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
        from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply

        db_file = tmp_path / "test.db"
        conn = open_connection(str(db_file))
        load_and_verify_extensions(conn)
        conn.execute("BEGIN")
        apply(conn)
        conn.execute("COMMIT")

        # Get size while connection is open (same state as stats call)
        stats = gather_meta_stats(conn, config, str(db_file))
        conn.close()

        # Verify size is positive and reasonable (> 0 means the file has content)
        assert stats["db_size_bytes"] > 0
        # The reported size should be close to the actual file size
        actual_size = Path(str(db_file)).stat().st_size
        # Allow for WAL mode size variance — stats size should be <= actual (file may grow after stat)
        assert stats["db_size_bytes"] <= actual_size

    def test_db_size_bytes_for_memory_db(self, migrated_conn, config) -> None:
        """db_size_bytes should be 0 for :memory: databases.

        # --- Assert ---
        # stats["db_size_bytes"] == 0
        """
        stats = gather_meta_stats(migrated_conn, config, ":memory:")
        assert stats["db_size_bytes"] == 0
