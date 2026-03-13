# =============================================================================
# FILE: tests/cli/test_init_project_flag.py
# PURPOSE: Verify that the --project flag is correctly wired in the init CLI
#          parser and passed through to init_memory_store().
# RATIONALE: Task #13 — the --project flag was documented and backend-implemented
#            but the CLI parser rejected it as unknown. These tests lock in the fix.
# RESPONSIBILITY:
#   - Test _parse_init_flags() recognizes --project
#   - Test _parse_init_flags() handles --project + --force together
#   - Test _parse_init_flags() defaults to both False
#   - Test handle_init() passes project= to init_memory_store()
# ORGANIZATION:
#   1. _parse_init_flags unit tests
#   2. handle_init integration test (mocked backend)
# =============================================================================

from __future__ import annotations

from unittest.mock import patch, MagicMock
from pathlib import Path
from types import SimpleNamespace

import pytest

from memory_cli.cli.init_command_top_level_exception import (
    _parse_init_flags,
    handle_init,
)


# =============================================================================
# _parse_init_flags UNIT TESTS
# =============================================================================

class TestParseInitFlags:
    """Unit tests for _parse_init_flags()."""

    def test_parse_init_flags_default(self):
        """No flags -> both force and project are False."""
        result = _parse_init_flags([])
        assert result == {"force": False, "project": False}

    def test_parse_init_flags_project(self):
        """--project alone -> project=True, force=False."""
        result = _parse_init_flags(["--project"])
        assert result == {"force": False, "project": True}

    def test_parse_init_flags_force(self):
        """--force alone -> force=True, project=False."""
        result = _parse_init_flags(["--force"])
        assert result == {"force": True, "project": False}

    def test_parse_init_flags_project_and_force(self):
        """Both --project and --force -> both True."""
        result = _parse_init_flags(["--project", "--force"])
        assert result == {"force": True, "project": True}

    def test_parse_init_flags_force_and_project_reversed_order(self):
        """--force --project (reversed order) -> both True."""
        result = _parse_init_flags(["--force", "--project"])
        assert result == {"force": True, "project": True}

    def test_parse_init_flags_unknown_flag_raises(self):
        """Unknown flag raises ValueError."""
        with pytest.raises(ValueError, match="Unknown flag for init"):
            _parse_init_flags(["--bogus"])

    def test_parse_init_flags_positional_arg_raises(self):
        """Positional arguments raise ValueError."""
        with pytest.raises(ValueError, match="init takes no positional arguments"):
            _parse_init_flags(["something"])


# =============================================================================
# handle_init INTEGRATION TEST (mocked backend)
# =============================================================================

class TestHandleInitPassesProjectFlag:
    """Verify handle_init() passes project= through to init_memory_store()."""

    def _run_handle_init(self, args, mock_init):
        """Helper: run handle_init with a non-existent db path so we reach init_memory_store.

        We patch the init module's init_memory_store via sys.modules so the
        lazy import inside handle_init picks up the mock.
        """
        global_flags = SimpleNamespace(db=None, config=None)
        # Patch at the module that handle_init imports from
        with patch(
            "memory_cli.config.init_create_global_or_project_store.init_memory_store",
            mock_init,
        ):
            return handle_init(args, global_flags)

    def test_handle_init_passes_project_true(self, tmp_path):
        """handle_init(["--project"], flags) calls init_memory_store(project=True)."""
        mock_store = tmp_path / ".memory"
        mock_store.mkdir()
        (mock_store / "memory.db").touch()
        (mock_store / "config.json").write_text("{}")

        mock_init = MagicMock(return_value=mock_store)

        # Use a db path that doesn't exist so we don't hit the early return
        global_flags = SimpleNamespace(db=str(tmp_path / "nonexistent" / "memory.db"), config=None)

        with patch(
            "memory_cli.config.init_create_global_or_project_store.init_memory_store",
            mock_init,
        ):
            result = handle_init(["--project"], global_flags)

        mock_init.assert_called_once_with(project=True, force=False)
        assert result.status == "ok"

    def test_handle_init_passes_project_false_by_default(self, tmp_path):
        """handle_init([], flags) calls init_memory_store(project=False)."""
        mock_store = tmp_path / ".memory"
        mock_store.mkdir()
        (mock_store / "memory.db").touch()
        (mock_store / "config.json").write_text("{}")

        mock_init = MagicMock(return_value=mock_store)

        global_flags = SimpleNamespace(db=str(tmp_path / "nonexistent" / "memory.db"), config=None)

        with patch(
            "memory_cli.config.init_create_global_or_project_store.init_memory_store",
            mock_init,
        ):
            result = handle_init([], global_flags)

        mock_init.assert_called_once_with(project=False, force=False)
        assert result.status == "ok"

    def test_handle_init_passes_project_and_force(self, tmp_path):
        """handle_init(["--project", "--force"], flags) passes both flags."""
        mock_store = tmp_path / ".memory"
        mock_store.mkdir()
        (mock_store / "memory.db").touch()
        (mock_store / "config.json").write_text("{}")

        mock_init = MagicMock(return_value=mock_store)

        global_flags = SimpleNamespace(db=str(tmp_path / "nonexistent" / "memory.db"), config=None)

        with patch(
            "memory_cli.config.init_create_global_or_project_store.init_memory_store",
            mock_init,
        ):
            result = handle_init(["--project", "--force"], global_flags)

        mock_init.assert_called_once_with(project=True, force=True)
        assert result.status == "ok"
