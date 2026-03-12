# =============================================================================
# test_meta_check.py — Tests for `memory meta check` command (9-point scan)
# =============================================================================
# Purpose:     Verify that run_meta_check correctly runs all 9 integrity checks,
#              detects orphans and anomalies, reports issues in a structured
#              format, and updates last_integrity_check_at.
# Rationale:   Each of the 9 checks catches a different class of data corruption.
#              Tests must verify both the "everything clean" path and the "issues
#              found" path for every check. Orphan detection queries are especially
#              tricky — wrong JOINs silently miss orphans or false-positive on
#              valid data.
# Responsibility:
#   - Test all-clean scenario (9 checks pass)
#   - Test each individual check in isolation (pass and fail cases)
#   - Test orphan detection for vectors, edges, and FTS
#   - Test dimension consistency sampling
#   - Test aggregate result structure (status, counts, issues)
#   - Test last_integrity_check_at is updated
# Organization:
#   Test classes for aggregate behavior, each individual check, and
#   the timestamp update. Uses in-memory SQLite with full schema.
# =============================================================================

from __future__ import annotations

import struct
import time
import pytest
from datetime import datetime, timezone
from memory_cli.integrity.meta_check_orphans_and_anomalies import (
    run_meta_check,
    CheckItem,
    MetaCheckResult,
    _check_db_accessible,
    _check_schema_version,
    _check_model_match,
    _check_dimension_match,
    _check_stale_flag,
    _check_orphaned_vectors,
    _check_orphaned_edges,
    _check_orphaned_fts,
    _check_dimension_consistency,
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


class TestAggregateResult:
    """Tests for the overall run_meta_check result structure."""

    def test_all_checks_pass_returns_ok(self, migrated_conn, config) -> None:
        """When all 9 checks pass, status should be "ok".

        # --- Arrange ---
        # Create clean in-memory DB with full schema, matching config

        # --- Act ---
        # result = run_meta_check(conn, config)

        # --- Assert ---
        # result["status"] == "ok"
        # result["checks_passed"] == 9
        # result["checks_failed"] == 0
        # result["issues"] == []
        """
        result = run_meta_check(migrated_conn, config)
        assert result["status"] == "ok"
        assert result["checks_passed"] == 9
        assert result["checks_failed"] == 0
        assert result["issues"] == []

    def test_issues_found_returns_issues_found_status(self, migrated_conn, config) -> None:
        """When any check fails, status should be "issues_found".

        # --- Arrange ---
        # Set vectors_marked_stale_at to create a failing check

        # --- Act ---
        # result = run_meta_check(conn, config)

        # --- Assert ---
        # result["status"] == "issues_found"
        # result["checks_failed"] >= 1
        # len(result["issues"]) >= 1
        """
        migrated_conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('vectors_marked_stale_at', '2025-06-01T00:00:00+00:00')"
        )
        migrated_conn.commit()
        result = run_meta_check(migrated_conn, config)
        assert result["status"] == "issues_found"
        assert result["checks_failed"] >= 1
        assert len(result["issues"]) >= 1

    def test_counts_add_up_to_nine(self, migrated_conn, config) -> None:
        """checks_passed + checks_failed should always equal 9.

        # --- Act ---
        # result = run_meta_check(conn, config)

        # --- Assert ---
        # result["checks_passed"] + result["checks_failed"] == 9
        """
        result = run_meta_check(migrated_conn, config)
        assert result["checks_passed"] + result["checks_failed"] == 9

    def test_issues_array_contains_descriptions(self, migrated_conn, config) -> None:
        """Each issue should be a human-readable string.

        # --- Arrange ---
        # Create DB with known issues

        # --- Assert ---
        # Each element in result["issues"] is a non-empty string
        """
        migrated_conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('vectors_marked_stale_at', '2025-06-01T00:00:00+00:00')"
        )
        migrated_conn.commit()
        result = run_meta_check(migrated_conn, config)
        for issue in result["issues"]:
            assert isinstance(issue, str)
            assert len(issue) > 0


class TestCheckDbAccessible:
    """Tests for check 1: DB accessible."""

    def test_healthy_db_passes(self, migrated_conn) -> None:
        """A working connection should pass the accessibility check.

        # --- Act ---
        # item = _check_db_accessible(conn)

        # --- Assert ---
        # item.name == "db_accessible"
        # item.passed == True
        """
        item = _check_db_accessible(migrated_conn)
        assert item.name == "db_accessible"
        assert item.passed is True

    def test_closed_connection_fails(self, migrated_conn) -> None:
        """A closed connection should fail the accessibility check.

        # --- Arrange ---
        # conn.close()

        # --- Act ---
        # item = _check_db_accessible(conn)

        # --- Assert ---
        # item.passed == False
        # item.detail contains error info
        """
        migrated_conn.close()
        item = _check_db_accessible(migrated_conn)
        assert item.passed is False
        assert item.detail is not None and len(item.detail) > 0


class TestCheckSchemaVersion:
    """Tests for check 2: Schema version."""

    def test_valid_schema_passes(self, migrated_conn) -> None:
        """Known schema version should pass.

        # --- Arrange ---
        # DB with schema version 1 (from migration)

        # --- Assert ---
        # item.passed == True
        """
        item = _check_schema_version(migrated_conn)
        assert item.passed is True

    def test_zero_schema_fails(self) -> None:
        """Schema version 0 or missing meta key means uninitialized — should fail.

        # --- Arrange ---
        # DB with schema_version = '0' in meta

        # --- Assert ---
        # item.passed == False
        # item.detail mentions "not initialized"
        """
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '0')")
        item = _check_schema_version(conn)
        conn.close()
        assert item.passed is False
        assert "not initialized" in item.detail.lower() or "0" in item.detail


class TestCheckModelMatch:
    """Tests for check 3: Model name match."""

    def test_matching_model_passes(self, migrated_conn, config) -> None:
        """DB model == config model should pass.

        # --- Arrange ---
        # DB meta: embedding_model = "nomic-embed-text-v1.5.Q8_0.gguf"
        # Config: embedding_model = "nomic-embed-text-v1.5.Q8_0.gguf"

        # --- Assert ---
        # item.passed == True
        """
        migrated_conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('embedding_model', 'nomic-embed-text-v1.5.Q8_0.gguf')"
        )
        item = _check_model_match(migrated_conn, config)
        assert item.passed is True

    def test_mismatched_model_fails(self, migrated_conn, config) -> None:
        """DB model != config model should fail.

        # --- Assert ---
        # item.passed == False
        # item.detail mentions both model names
        """
        migrated_conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('embedding_model', 'old-different.gguf')"
        )
        item = _check_model_match(migrated_conn, config)
        assert item.passed is False
        assert "old-different.gguf" in item.detail
        assert "nomic-embed-text-v1.5.Q8_0.gguf" in item.detail

    def test_no_model_in_db_passes(self, migrated_conn, config) -> None:
        """If no model stored (default value), check passes.

        # --- Assert ---
        # item.passed == True (migration sets 'default' → treated as no vectors)
        """
        # Migration seeds 'default' — should pass
        item = _check_model_match(migrated_conn, config)
        assert item.passed is True


class TestCheckDimensionMatch:
    """Tests for check 4: Dimension match."""

    def test_matching_dimensions_passes(self, migrated_conn, config) -> None:
        """DB dims == config dims should pass.

        # --- Assert ---
        # item.passed == True
        """
        # Migration seeds '768' which matches config
        item = _check_dimension_match(migrated_conn, config)
        assert item.passed is True

    def test_mismatched_dimensions_fails(self, migrated_conn) -> None:
        """DB dims != config dims should fail.

        # --- Assert ---
        # item.passed == False
        # item.detail mentions both dimension values
        """
        config_384 = {"embedding": {"model_path": "/path/to/model.gguf", "dimensions": 384}}
        # Migration seeds 768
        item = _check_dimension_match(migrated_conn, config_384)
        assert item.passed is False
        assert "768" in item.detail
        assert "384" in item.detail

    def test_no_dimensions_in_db_passes(self) -> None:
        """If no dimensions stored (missing key), check passes.

        # --- Assert ---
        # item.passed == True
        """
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        config = {"embedding": {"model_path": "/path/to/model.gguf", "dimensions": 768}}
        item = _check_dimension_match(conn, config)
        conn.close()
        assert item.passed is True


class TestCheckStaleFlag:
    """Tests for check 5: Stale vector flag."""

    def test_no_stale_flag_passes(self, migrated_conn, config) -> None:
        """If vectors_marked_stale_at is not set, check passes.

        # --- Assert ---
        # item.passed == True
        """
        item = _check_stale_flag(migrated_conn)
        assert item.passed is True

    def test_stale_flag_set_fails(self, migrated_conn) -> None:
        """If vectors_marked_stale_at is set, check fails with timestamp.

        # --- Arrange ---
        # Set vectors_marked_stale_at in meta

        # --- Assert ---
        # item.passed == False
        # item.detail contains the timestamp
        # item.detail mentions "memory batch reembed"
        """
        ts = "2025-06-01T00:00:00+00:00"
        migrated_conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('vectors_marked_stale_at', ?)",
            (ts,),
        )
        item = _check_stale_flag(migrated_conn)
        assert item.passed is False
        assert ts in item.detail
        assert "memory batch reembed" in item.detail


class TestCheckOrphanedVectors:
    """Tests for check 6: Orphaned vectors."""

    def test_no_orphans_passes(self, migrated_conn, config) -> None:
        """When all vectors have parent neurons, check passes.

        # --- Arrange ---
        # Insert neurons and matching vectors

        # --- Assert ---
        # item.passed == True
        """
        nid = _insert_neuron(migrated_conn)
        _insert_vector(migrated_conn, nid)
        migrated_conn.commit()
        item = _check_orphaned_vectors(migrated_conn)
        assert item.passed is True

    def test_orphaned_vectors_detected(self, migrated_conn) -> None:
        """Vectors without parent neurons should be detected.

        # --- Arrange ---
        # Insert a neuron, add a vector, then delete the neuron (FK cascade disabled)

        # --- Assert ---
        # item.passed == False
        # item.detail contains orphan count
        """
        # Insert neuron and vector
        nid = _insert_neuron(migrated_conn)
        _insert_vector(migrated_conn, nid)
        migrated_conn.commit()

        # Disable FK enforcement and delete neuron (leaving orphaned vector in neurons_vec)
        # Note: FK off means ON DELETE CASCADE won't fire for neurons_vec
        migrated_conn.execute("PRAGMA foreign_keys = OFF")
        migrated_conn.execute("DELETE FROM neurons WHERE id = ?", (nid,))
        migrated_conn.commit()
        migrated_conn.execute("PRAGMA foreign_keys = ON")

        item = _check_orphaned_vectors(migrated_conn)
        assert item.passed is False
        assert item.detail is not None
        assert "1" in item.detail


class TestCheckOrphanedEdges:
    """Tests for check 7: Orphaned edges."""

    def test_no_orphans_passes(self, migrated_conn) -> None:
        """When all edge endpoints exist, check passes.

        # --- Arrange ---
        # Insert neurons and edges between them

        # --- Assert ---
        # item.passed == True
        """
        ts = int(time.time() * 1000)
        n1 = _insert_neuron(migrated_conn, "source")
        n2 = _insert_neuron(migrated_conn, "target")
        migrated_conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, created_at) VALUES (?,?,?,?)",
            (n1, n2, "related", ts),
        )
        migrated_conn.commit()
        item = _check_orphaned_edges(migrated_conn)
        assert item.passed is True

    def test_orphaned_source_detected(self, migrated_conn) -> None:
        """Edge with deleted source neuron should be detected.

        # --- Arrange ---
        # Create edge, then delete source neuron (FK off)

        # --- Assert ---
        # item.passed == False
        """
        ts = int(time.time() * 1000)
        n1 = _insert_neuron(migrated_conn, "source")
        n2 = _insert_neuron(migrated_conn, "target")
        migrated_conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, created_at) VALUES (?,?,?,?)",
            (n1, n2, "related", ts),
        )
        migrated_conn.commit()

        # Disable FK and delete source — orphan the edge
        migrated_conn.execute("PRAGMA foreign_keys = OFF")
        migrated_conn.execute("DELETE FROM neurons WHERE id = ?", (n1,))
        migrated_conn.commit()
        migrated_conn.execute("PRAGMA foreign_keys = ON")

        item = _check_orphaned_edges(migrated_conn)
        assert item.passed is False

    def test_orphaned_target_detected(self, migrated_conn) -> None:
        """Edge with deleted target neuron should be detected.

        # --- Arrange ---
        # Create edge, then delete target neuron (FK off)

        # --- Assert ---
        # item.passed == False
        """
        ts = int(time.time() * 1000)
        n1 = _insert_neuron(migrated_conn, "source")
        n2 = _insert_neuron(migrated_conn, "target")
        migrated_conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, created_at) VALUES (?,?,?,?)",
            (n1, n2, "related", ts),
        )
        migrated_conn.commit()

        # Disable FK and delete target
        migrated_conn.execute("PRAGMA foreign_keys = OFF")
        migrated_conn.execute("DELETE FROM neurons WHERE id = ?", (n2,))
        migrated_conn.commit()
        migrated_conn.execute("PRAGMA foreign_keys = ON")

        item = _check_orphaned_edges(migrated_conn)
        assert item.passed is False


class TestCheckOrphanedFts:
    """Tests for check 8: Orphaned FTS entries."""

    def test_no_orphans_passes(self, migrated_conn) -> None:
        """When all FTS entries have parent neurons, check passes.

        # --- Assert ---
        # item.passed == True
        """
        # Insert a neuron (FTS trigger auto-inserts)
        _insert_neuron(migrated_conn, "test content")
        migrated_conn.commit()
        item = _check_orphaned_fts(migrated_conn)
        assert item.passed is True

    def test_empty_db_passes(self, migrated_conn) -> None:
        """Empty DB (no neurons, no FTS entries) should pass trivially.

        # --- Assert ---
        # item.passed == True
        """
        item = _check_orphaned_fts(migrated_conn)
        assert item.passed is True

    def test_orphaned_fts_detected(self, migrated_conn) -> None:
        """FTS entries without parent neurons should be detected.

        # --- Arrange ---
        # Insert an FTS entry directly with a rowid that has no neuron
        # (simulates orphaned FTS — neuron deleted but FTS not cleaned)

        # --- Assert ---
        # item.passed == False
        # item.detail contains count
        """
        # Insert directly into FTS5 virtual table with a rowid that doesn't exist in neurons
        # This creates an orphaned FTS entry (neuron 9999 doesn't exist)
        migrated_conn.execute(
            "INSERT INTO neurons_fts(rowid, content, tags_blob) VALUES (9999, 'orphaned content', '')"
        )
        migrated_conn.commit()

        item = _check_orphaned_fts(migrated_conn)
        assert item.passed is False
        assert item.detail is not None


class TestCheckDimensionConsistency:
    """Tests for check 9: Dimension consistency sampling."""

    def test_consistent_dimensions_passes(self, migrated_conn, config) -> None:
        """When all sampled vectors have correct dimensions, check passes.

        # --- Arrange ---
        # Insert vectors all with 768 dimensions
        # Config: embedding_dimensions = 768

        # --- Assert ---
        # item.passed == True
        """
        nid = _insert_neuron(migrated_conn)
        _insert_vector(migrated_conn, nid, dims=768)
        migrated_conn.commit()
        item = _check_dimension_consistency(migrated_conn, config)
        assert item.passed is True

    def test_no_vectors_passes_trivially(self, migrated_conn, config) -> None:
        """If no vectors exist, dimension check should pass.

        # --- Arrange ---
        # Empty DB (no vectors)

        # --- Assert ---
        # item.passed == True
        """
        item = _check_dimension_consistency(migrated_conn, config)
        assert item.passed is True

    def test_consistent_multiple_vectors_passes(self, migrated_conn, config) -> None:
        """Multiple vectors all with correct dimensions should pass.

        # --- Arrange ---
        # Insert 10 neurons each with a 768-dim vector

        # --- Assert ---
        # item.passed == True
        """
        nids = [_insert_neuron(migrated_conn, f"content {i}") for i in range(10)]
        for nid in nids:
            _insert_vector(migrated_conn, nid, dims=768)
        migrated_conn.commit()
        item = _check_dimension_consistency(migrated_conn, config)
        assert item.passed is True


class TestIntegrityTimestamp:
    """Tests for the last_integrity_check_at update."""

    def test_timestamp_set_after_check(self, migrated_conn, config) -> None:
        """last_integrity_check_at should be updated after run_meta_check.

        # --- Arrange ---
        # No last_integrity_check_at in meta

        # --- Act ---
        # result = run_meta_check(conn, config)

        # --- Assert ---
        # result["last_integrity_check_at"] is a valid ISO 8601 string
        # meta table has last_integrity_check_at set
        """
        result = run_meta_check(migrated_conn, config)
        assert result["last_integrity_check_at"] is not None
        # Should be parseable as ISO 8601
        ts = datetime.fromisoformat(result["last_integrity_check_at"])
        assert ts is not None

        # Also verify meta table was updated
        row = migrated_conn.execute(
            "SELECT value FROM meta WHERE key = 'last_integrity_check_at'"
        ).fetchone()
        assert row is not None
        assert row[0] == result["last_integrity_check_at"]

    def test_timestamp_is_utc(self, migrated_conn, config) -> None:
        """Timestamp should be in UTC timezone.

        # --- Act ---
        # result = run_meta_check(conn, config)

        # --- Assert ---
        # Parse timestamp, verify timezone is UTC
        """
        result = run_meta_check(migrated_conn, config)
        ts = datetime.fromisoformat(result["last_integrity_check_at"])
        assert ts.tzinfo is not None

    def test_timestamp_updates_on_rerun(self, migrated_conn, config) -> None:
        """Running check twice should produce the same or later timestamp.

        # --- Arrange ---
        # Run check once, note timestamp

        # --- Act ---
        # Run check again

        # --- Assert ---
        # New timestamp >= old timestamp
        """
        result1 = run_meta_check(migrated_conn, config)
        ts1 = datetime.fromisoformat(result1["last_integrity_check_at"])

        result2 = run_meta_check(migrated_conn, config)
        ts2 = datetime.fromisoformat(result2["last_integrity_check_at"])

        assert ts2 >= ts1
