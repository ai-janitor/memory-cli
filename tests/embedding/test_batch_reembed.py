# =============================================================================
# test_batch_reembed.py — Tests for full re-embed flow, progress, partial completion
# =============================================================================
# Purpose:     Verify the batch_reembed() orchestrator correctly discovers
#              candidates, processes them in batches, writes vectors, and
#              reports accurate progress — including partial completion scenarios.
# Rationale:   The batch re-embed is the most complex embedding operation,
#              coordinating detection, loading, embedding, and storage. It must
#              handle failures gracefully (partial completion, model missing)
#              without losing already-processed work.
# Responsibility:
#   - Test full happy-path: all candidates found, embedded, stored
#   - Test progress reporting: correct blank/stale/processed/failed counts
#   - Test partial completion: some batches succeed, others fail
#   - Test model missing: all fail gracefully, progress reflects it
#   - Test empty candidates: no-op with zero counts
#   - Test batch_size parameter controls chunking
#   - Test project_id filter is passed through
# Organization:
#   Uses pytest fixtures with mocked embed_batch, stale/blank detection,
#   and vector storage. Tests verify ReembedProgress values.
# =============================================================================

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
import sqlite3

from memory_cli.embedding.batch_reembed_blank_and_stale import ReembedProgress, batch_reembed


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


def _insert_neuron(
    conn: sqlite3.Connection,
    content: str = "test content",
    project: str = "proj-a",
    updated_at: int | None = None,
    embedding_updated_at: int | None = None,
    status: str = "active",
) -> int:
    """Insert a test neuron and return its integer id."""
    now_ms = int(time.time() * 1000)
    if updated_at is None:
        updated_at = now_ms
    cursor = conn.execute(
        """INSERT INTO neurons
           (content, created_at, updated_at, project, embedding_updated_at, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (content, now_ms, updated_at, project, embedding_updated_at, status),
    )
    return cursor.lastrowid


class TestHappyPath:
    """All candidates found, embedded, and stored successfully."""

    # --- Test: progress counts are correct ---
    # result = batch_reembed(conn)
    # assert result.blank_count == 2
    # assert result.stale_count == 1
    # assert result.total_candidates == 3
    # assert result.processed == 3
    # assert result.failed == 0
    # assert result.failed_neuron_ids == []
    def test_full_happy_path_counts(self, migrated_conn):
        # Insert 2 blank neurons (no embedding)
        blank1 = _insert_neuron(migrated_conn, content="blank 1")
        blank2 = _insert_neuron(migrated_conn, content="blank 2")

        # Insert 1 stale neuron (has embedding, but updated since)
        import struct
        now_ms = int(time.time() * 1000)
        old_ms = now_ms - 10000
        stale1 = _insert_neuron(
            migrated_conn,
            content="stale 1",
            updated_at=now_ms,
            embedding_updated_at=old_ms,
        )
        blob = struct.pack("<768f", *([0.0] * 768))
        migrated_conn.execute(
            "INSERT OR REPLACE INTO neurons_vec (neuron_id, embedding) VALUES (?, ?)",
            (stale1, blob),
        )
        migrated_conn.execute("COMMIT")

        # Mock model whose embed returns 768-dim vectors
        mock_model = MagicMock()
        mock_model.embed.return_value = [[0.0] * 768] * 10  # enough for any batch size

        def _embed_side_effect(texts, normalize=True):
            return [[0.0] * 768 for _ in texts]

        mock_model.embed.side_effect = _embed_side_effect

        result = batch_reembed(migrated_conn, mock_model)

        assert result.blank_count == 2
        assert result.stale_count == 1
        assert result.total_candidates == 3
        assert result.processed == 3
        assert result.failed == 0
        assert result.failed_neuron_ids == []


class TestPartialCompletion:
    """Some batches succeed, others fail — processed batches are kept."""

    # --- Test: first batch succeeds, second batch fails ---
    # Mock embed_batch to succeed for first call, raise for second
    # Use batch_size=2 so 3 candidates split into [2, 1]
    # result = batch_reembed(conn, batch_size=2)
    # assert result.processed == 2  # first batch succeeded
    # assert result.failed == 1  # second batch failed
    # assert len(result.failed_neuron_ids) == 1
    def test_first_batch_succeeds_second_fails(self, migrated_conn):
        blank1 = _insert_neuron(migrated_conn, content="c1")
        blank2 = _insert_neuron(migrated_conn, content="c2")
        blank3 = _insert_neuron(migrated_conn, content="c3")
        migrated_conn.execute("COMMIT")

        call_count = [0]

        def _embed_side_effect(texts, normalize=True):
            call_count[0] += 1
            if call_count[0] == 1:
                return [[0.0] * 768 for _ in texts]
            raise RuntimeError("Simulated embed failure")

        mock_model = MagicMock()
        mock_model.embed.side_effect = _embed_side_effect

        result = batch_reembed(migrated_conn, mock_model, batch_size=2)

        assert result.processed == 2
        assert result.failed == 1
        assert len(result.failed_neuron_ids) == 1


class TestModelMissing:
    """Model missing means all embedding fails, but gracefully."""

    # --- Test: all candidates fail when model missing (embed returns None) ---
    # Mock embed_batch to return None (model missing behavior)
    # result = batch_reembed(conn)
    # assert result.processed == 0
    # assert result.failed == result.total_candidates
    # assert len(result.failed_neuron_ids) == result.total_candidates
    def test_model_missing_all_fail(self, migrated_conn):
        blank1 = _insert_neuron(migrated_conn, content="c1")
        blank2 = _insert_neuron(migrated_conn, content="c2")
        migrated_conn.execute("COMMIT")

        mock_model = MagicMock()

        with patch(
            "memory_cli.embedding.batch_reembed_blank_and_stale.embed_batch",
            return_value=None,
        ):
            result = batch_reembed(migrated_conn, mock_model)

        assert result.processed == 0
        assert result.failed == result.total_candidates
        assert len(result.failed_neuron_ids) == result.total_candidates


class TestEmptyCandidates:
    """No blank or stale neurons means no-op."""

    # --- Test: zero counts, no processing ---
    # Mock detection to return empty lists
    # result = batch_reembed(conn)
    # assert result.blank_count == 0
    # assert result.stale_count == 0
    # assert result.total_candidates == 0
    # assert result.processed == 0
    # assert result.failed == 0
    def test_empty_candidates_is_noop(self, migrated_conn):
        # No neurons inserted — empty DB
        mock_model = MagicMock()

        result = batch_reembed(migrated_conn, mock_model)

        assert result.blank_count == 0
        assert result.stale_count == 0
        assert result.total_candidates == 0
        assert result.processed == 0
        assert result.failed == 0
        mock_model.embed.assert_not_called()


class TestBatchSizeControl:
    """batch_size parameter controls how candidates are chunked."""

    # --- Test: batch_size=1 processes one at a time ---
    # Mock everything, track number of embed_batch calls
    # batch_reembed(conn, batch_size=1)
    # Assert embed_batch called 3 times (once per candidate)
    def test_batch_size_1_calls_embed_per_candidate(self, migrated_conn):
        blank1 = _insert_neuron(migrated_conn, content="c1")
        blank2 = _insert_neuron(migrated_conn, content="c2")
        blank3 = _insert_neuron(migrated_conn, content="c3")
        migrated_conn.execute("COMMIT")

        embed_call_count = [0]

        def _embed_side_effect(texts, normalize=True):
            embed_call_count[0] += 1
            return [[0.0] * 768 for _ in texts]

        mock_model = MagicMock()
        mock_model.embed.side_effect = _embed_side_effect

        result = batch_reembed(migrated_conn, mock_model, batch_size=1)

        assert embed_call_count[0] == 3
        assert result.processed == 3

    # --- Test: batch_size=100 processes all in one batch ---
    # batch_reembed(conn, batch_size=100)
    # Assert embed_batch called 1 time (all 3 in one batch)
    def test_batch_size_100_single_call(self, migrated_conn):
        blank1 = _insert_neuron(migrated_conn, content="c1")
        blank2 = _insert_neuron(migrated_conn, content="c2")
        blank3 = _insert_neuron(migrated_conn, content="c3")
        migrated_conn.execute("COMMIT")

        embed_call_count = [0]

        def _embed_side_effect(texts, normalize=True):
            embed_call_count[0] += 1
            return [[0.0] * 768 for _ in texts]

        mock_model = MagicMock()
        mock_model.embed.side_effect = _embed_side_effect

        result = batch_reembed(migrated_conn, mock_model, batch_size=100)

        assert embed_call_count[0] == 1
        assert result.processed == 3


class TestProjectFilter:
    """project_id is passed through to detection functions."""

    # --- Test: project_id filter reaches detection layer ---
    # Mock detection functions, track arguments
    # batch_reembed(conn, project_id="proj-a")
    # Assert get_blank_neuron_ids called with project_id="proj-a"
    # Assert get_stale_neuron_ids called with project_id="proj-a"
    def test_project_id_passed_to_detection(self, migrated_conn):
        mock_model = MagicMock()

        with (
            patch(
                "memory_cli.embedding.batch_reembed_blank_and_stale.get_blank_neuron_ids",
                return_value=[],
            ) as mock_blank,
            patch(
                "memory_cli.embedding.batch_reembed_blank_and_stale.get_stale_neuron_ids",
                return_value=[],
            ) as mock_stale,
            patch(
                "memory_cli.embedding.batch_reembed_blank_and_stale.get_all_reembed_candidates",
                return_value=[],
            ) as mock_all,
        ):
            batch_reembed(migrated_conn, mock_model, project_id="proj-a")

        mock_blank.assert_called_once_with(migrated_conn, "proj-a")
        mock_stale.assert_called_once_with(migrated_conn, "proj-a")
        mock_all.assert_called_once_with(migrated_conn, "proj-a")
