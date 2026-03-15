# =============================================================================
# FILE: tests/cli/test_resolve_connection_by_scope_exception_handling.py
# PURPOSE: Verify resolve_connection_by_scope logs exceptions instead of
#          silently swallowing them during fingerprint lookup.
# RATIONALE: Bug fix for backlog #40 — the old code had
#            `except (ValueError, Exception): continue` which gave callers
#            zero diagnostic info on DB corruption or connection failure.
# NOTE: resolve_connection_by_scope was moved from neuron_noun_handler to
#       scoped_handle_format_and_parse (Task #22) to be shared by all noun
#       handlers. The private alias _resolve_connection_by_scope remains in
#       neuron_noun_handler for backwards compatibility.
# =============================================================================

from __future__ import annotations

import logging
from unittest.mock import patch, MagicMock

import pytest

from memory_cli.cli.scoped_handle_format_and_parse import resolve_connection_by_scope as _resolve_connection_by_scope

# Logger name after move to scoped_handle_format_and_parse
_LOGGER = "memory_cli.cli.scoped_handle_format_and_parse"


# =============================================================================
# Standard LOCAL/GLOBAL routing (no fingerprint involved)
# =============================================================================

class TestNonFingerprintRouting:
    def test_returns_matching_connection_for_local(self):
        conn = MagicMock()
        connections = [(conn, "LOCAL")]
        result = _resolve_connection_by_scope("LOCAL", connections)
        assert result == (conn, "LOCAL")

    def test_returns_none_when_scope_not_found(self):
        conn = MagicMock()
        connections = [(conn, "LOCAL")]
        result = _resolve_connection_by_scope("GLOBAL", connections)
        assert result is None


# =============================================================================
# Fingerprint routing — happy path
# =============================================================================

class TestFingerprintRoutingHappyPath:
    @patch("memory_cli.db.store_fingerprint_read_and_cache.get_fingerprint")
    def test_returns_matching_connection_by_fingerprint(self, mock_fp):
        conn = MagicMock()
        mock_fp.return_value = "abcd1234"
        connections = [(conn, "LOCAL")]
        result = _resolve_connection_by_scope("abcd1234", connections)
        assert result == (conn, "LOCAL")

    @patch("memory_cli.db.store_fingerprint_read_and_cache.get_fingerprint")
    def test_returns_none_when_no_fingerprint_matches(self, mock_fp):
        conn = MagicMock()
        mock_fp.return_value = "deadbeef"
        connections = [(conn, "LOCAL")]
        result = _resolve_connection_by_scope("abcd1234", connections)
        assert result is None


# =============================================================================
# Fingerprint routing — ValueError (expected, missing fingerprint)
# =============================================================================

class TestFingerprintValueError:
    @patch("memory_cli.db.store_fingerprint_read_and_cache.get_fingerprint")
    def test_value_error_logs_debug_and_continues(self, mock_fp, caplog):
        conn_bad = MagicMock()
        conn_good = MagicMock()
        # First store raises ValueError (no fingerprint), second matches
        mock_fp.side_effect = [
            ValueError("No fingerprint found"),
            "abcd1234",
        ]
        connections = [(conn_bad, "LOCAL"), (conn_good, "GLOBAL")]
        with caplog.at_level(logging.DEBUG, logger="memory_cli.cli.scoped_handle_format_and_parse"):
            result = _resolve_connection_by_scope("abcd1234", connections)
        assert result == (conn_good, "GLOBAL")
        assert "no fingerprint in meta table" in caplog.text.lower()

    @patch("memory_cli.db.store_fingerprint_read_and_cache.get_fingerprint")
    def test_value_error_does_not_log_warning(self, mock_fp, caplog):
        """ValueError is expected — should NOT produce a warning."""
        conn = MagicMock()
        mock_fp.side_effect = ValueError("No fingerprint found")
        connections = [(conn, "LOCAL")]
        with caplog.at_level(logging.WARNING, logger="memory_cli.cli.scoped_handle_format_and_parse"):
            _resolve_connection_by_scope("abcd1234", connections)
        # No WARNING-level messages for expected ValueError
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warning_records) == 0


# =============================================================================
# Fingerprint routing — unexpected Exception (DB corruption, etc.)
# =============================================================================

class TestFingerprintUnexpectedException:
    @patch("memory_cli.db.store_fingerprint_read_and_cache.get_fingerprint")
    def test_unexpected_exception_logs_warning_and_continues(self, mock_fp, caplog):
        conn_bad = MagicMock()
        conn_good = MagicMock()
        # First store has a DB error, second matches
        mock_fp.side_effect = [
            RuntimeError("database disk image is malformed"),
            "abcd1234",
        ]
        connections = [(conn_bad, "LOCAL"), (conn_good, "GLOBAL")]
        with caplog.at_level(logging.WARNING, logger="memory_cli.cli.scoped_handle_format_and_parse"):
            result = _resolve_connection_by_scope("abcd1234", connections)
        assert result == (conn_good, "GLOBAL")
        assert "fingerprint lookup failed" in caplog.text.lower()

    @patch("memory_cli.db.store_fingerprint_read_and_cache.get_fingerprint")
    def test_unexpected_exception_includes_traceback(self, mock_fp, caplog):
        conn = MagicMock()
        mock_fp.side_effect = RuntimeError("database disk image is malformed")
        connections = [(conn, "LOCAL")]
        with caplog.at_level(logging.WARNING, logger="memory_cli.cli.scoped_handle_format_and_parse"):
            result = _resolve_connection_by_scope("abcd1234", connections)
        assert result is None
        # exc_info=True should produce traceback text in the log
        assert "malformed" in caplog.text

    @patch("memory_cli.db.store_fingerprint_read_and_cache.get_fingerprint")
    def test_all_stores_fail_returns_none_with_warnings(self, mock_fp, caplog):
        conn1 = MagicMock()
        conn2 = MagicMock()
        mock_fp.side_effect = [
            OSError("connection refused"),
            RuntimeError("database locked"),
        ]
        connections = [(conn1, "LOCAL"), (conn2, "GLOBAL")]
        with caplog.at_level(logging.WARNING, logger="memory_cli.cli.scoped_handle_format_and_parse"):
            result = _resolve_connection_by_scope("abcd1234", connections)
        assert result is None
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warning_records) == 2
