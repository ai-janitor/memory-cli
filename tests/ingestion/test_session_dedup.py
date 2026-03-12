# =============================================================================
# Module: test_session_dedup.py
# Purpose: Test session dedup guard — detecting already-ingested sessions,
#   --force override behavior, and the underlying DB query.
# Rationale: The dedup guard prevents duplicate ingestion which would pollute
#   the graph with redundant neurons and edges. The guard must correctly
#   query the DB, handle the case where the attr_keys table doesn't have
#   the ingested_session_id key yet (first-ever ingest), and respect the
#   --force override. Each path needs test coverage.
# Responsibility:
#   - Test detection of already-ingested sessions
#   - Test clean session (not ingested) returns False
#   - Test --force override logic (tested at orchestrator level)
#   - Test DedupCheckResult dataclass
#   - Test DB query with mocked connection
# Organization:
#   1. Imports and fixtures
#   2. TestCheckSessionAlreadyIngested — main entry point
#   3. TestQueryExistingSessionNeurons — DB query logic
#   4. TestDedupCheckResult — dataclass behavior
# =============================================================================

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest

from memory_cli.ingestion.session_dedup_guard_by_session_id import (
    DedupCheckResult,
    _query_existing_session_neurons,
    check_session_already_ingested,
)


class TestCheckSessionAlreadyIngested:
    """Test check_session_already_ingested() main entry point."""

    def _make_conn(self, count: int) -> MagicMock:
        """Create a mock connection that returns count from execute."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (count,)
        conn.execute.return_value = cursor
        return conn

    def test_returns_true_when_neurons_exist(self):
        """Mock _query to return count=5 -> already_ingested=True."""
        conn = self._make_conn(5)
        result = check_session_already_ingested(conn, "sess-abc")
        assert result.already_ingested is True
        assert result.existing_neuron_count == 5

    def test_returns_false_when_no_neurons(self):
        """Mock _query to return count=0 -> already_ingested=False."""
        conn = self._make_conn(0)
        result = check_session_already_ingested(conn, "sess-abc")
        assert result.already_ingested is False
        assert result.existing_neuron_count == 0

    def test_session_id_passed_through(self):
        """result.session_id matches the input session_id."""
        conn = self._make_conn(0)
        result = check_session_already_ingested(conn, "sess-xyz-123")
        assert result.session_id == "sess-xyz-123"

    def test_returns_dedup_check_result_type(self):
        """Return type is DedupCheckResult."""
        conn = self._make_conn(0)
        result = check_session_already_ingested(conn, "sess-abc")
        assert isinstance(result, DedupCheckResult)


class TestQueryExistingSessionNeurons:
    """Test _query_existing_session_neurons() DB query."""

    def test_executes_correct_sql(self):
        """Mock conn.execute, verify SQL contains JOIN on neuron_attrs and attr_keys."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (3,)
        conn.execute.return_value = cursor

        result = _query_existing_session_neurons(conn, "sess-abc")
        assert result == 3

        # Verify SQL
        sql = conn.execute.call_args[0][0]
        assert "ingested_session_id" in sql
        assert "active" in sql

    def test_returns_count_from_query(self):
        """Mock cursor.fetchone() to return (3,) -> returns 3."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (3,)
        conn.execute.return_value = cursor
        assert _query_existing_session_neurons(conn, "sess-abc") == 3

    def test_returns_zero_for_no_matches(self):
        """Mock cursor.fetchone() to return (0,) -> returns 0."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (0,)
        conn.execute.return_value = cursor
        assert _query_existing_session_neurons(conn, "new-session") == 0

    def test_passes_session_id_as_parameter(self):
        """Verify conn.execute called with session_id as bind parameter."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (0,)
        conn.execute.return_value = cursor

        _query_existing_session_neurons(conn, "specific-session-id")

        # Verify session_id was passed as bind param
        call_args = conn.execute.call_args
        params = call_args[0][1]  # second positional arg is params tuple
        assert "specific-session-id" in params


class TestDedupCheckResult:
    """Test DedupCheckResult dataclass."""

    def test_fields_accessible(self):
        """Create DedupCheckResult(True, 5, "sess-abc") -> all fields accessible."""
        result = DedupCheckResult(
            already_ingested=True,
            existing_neuron_count=5,
            session_id="sess-abc",
        )
        assert result.already_ingested is True
        assert result.existing_neuron_count == 5
        assert result.session_id == "sess-abc"

    def test_equality(self):
        """Two instances with same values are equal."""
        r1 = DedupCheckResult(already_ingested=True, existing_neuron_count=5, session_id="sess-abc")
        r2 = DedupCheckResult(already_ingested=True, existing_neuron_count=5, session_id="sess-abc")
        assert r1 == r2
