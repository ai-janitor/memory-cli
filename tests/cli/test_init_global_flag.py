# =============================================================================
# FILE: tests/cli/test_init_global_flag.py
# PURPOSE: Verify that the --global flag is correctly wired in the init CLI
#          parser and passed through to init_memory_store().
# RATIONALE: Task #14 — the default was flipped from global to local. The
#            --global flag is how users opt into the old global (~/.memory/)
#            behavior. These tests lock in the new default and the flag.
# RESPONSIBILITY:
#   - Test _parse_init_flags() recognizes --global
#   - Test _parse_init_flags() handles --global + --force together
#   - Test _parse_init_flags() defaults to both False (local store)
#   - Test handle_init() passes project= to init_memory_store() correctly:
#     - No flags -> project=True (LOCAL default)
#     - --global -> project=False (GLOBAL)
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
        """No flags -> both force and global_store are False."""
        result = _parse_init_flags([])
        assert result == {"force": False, "global_store": False}

    def test_parse_init_flags_global(self):
        """--global alone -> global_store=True, force=False."""
        result = _parse_init_flags(["--global"])
        assert result == {"force": False, "global_store": True}

    def test_parse_init_flags_force(self):
        """--force alone -> force=True, global_store=False."""
        result = _parse_init_flags(["--force"])
        assert result == {"force": True, "global_store": False}

    def test_parse_init_flags_global_and_force(self):
        """Both --global and --force -> both True."""
        result = _parse_init_flags(["--global", "--force"])
        assert result == {"force": True, "global_store": True}

    def test_parse_init_flags_force_and_global_reversed_order(self):
        """--force --global (reversed order) -> both True."""
        result = _parse_init_flags(["--force", "--global"])
        assert result == {"force": True, "global_store": True}

    def test_parse_init_flags_unknown_flag_raises(self):
        """Unknown flag raises ValueError."""
        with pytest.raises(ValueError, match="Unknown flag for init"):
            _parse_init_flags(["--bogus"])

    def test_parse_init_flags_positional_arg_raises(self):
        """Positional arguments raise ValueError."""
        with pytest.raises(ValueError, match="init takes no positional arguments"):
            _parse_init_flags(["something"])

    def test_parse_init_flags_old_project_flag_rejected(self):
        """Old --project flag is no longer recognized."""
        with pytest.raises(ValueError, match="Unknown flag for init"):
            _parse_init_flags(["--project"])


# =============================================================================
# handle_init INTEGRATION TEST (mocked backend)
# =============================================================================

class TestHandleInitPassesGlobalFlag:
    """Verify handle_init() passes project= through to init_memory_store()."""

    def test_handle_init_default_is_local(self, tmp_path):
        """handle_init([], flags) calls init_memory_store(project=True) — LOCAL default."""
        mock_store = tmp_path / ".memory"
        mock_store.mkdir()

        mock_init = MagicMock(return_value=mock_store)
        global_flags = SimpleNamespace(db=None, config=None)

        with patch(
            "memory_cli.config.init_create_global_or_project_store.init_memory_store",
            mock_init,
        ):
            result = handle_init([], global_flags)

        mock_init.assert_called_once_with(project=True, force=False)
        assert result.status == "ok"

    def test_handle_init_global_flag_creates_global(self, tmp_path):
        """handle_init(["--global"], flags) calls init_memory_store(project=False) — GLOBAL."""
        mock_store = tmp_path / ".memory"
        mock_store.mkdir()

        mock_init = MagicMock(return_value=mock_store)
        global_flags = SimpleNamespace(db=None, config=None)

        with patch(
            "memory_cli.config.init_create_global_or_project_store.init_memory_store",
            mock_init,
        ):
            result = handle_init(["--global"], global_flags)

        mock_init.assert_called_once_with(project=False, force=False)
        assert result.status == "ok"

    def test_handle_init_global_and_force(self, tmp_path):
        """handle_init(["--global", "--force"], flags) passes both flags."""
        mock_store = tmp_path / ".memory"
        mock_store.mkdir()

        mock_init = MagicMock(return_value=mock_store)
        global_flags = SimpleNamespace(db=None, config=None)

        with patch(
            "memory_cli.config.init_create_global_or_project_store.init_memory_store",
            mock_init,
        ):
            result = handle_init(["--global", "--force"], global_flags)

        mock_init.assert_called_once_with(project=False, force=True)
        assert result.status == "ok"

    def test_handle_init_force_alone_is_local(self, tmp_path):
        """handle_init(["--force"], flags) calls init_memory_store(project=True, force=True)."""
        mock_store = tmp_path / ".memory"
        mock_store.mkdir()

        mock_init = MagicMock(return_value=mock_store)
        global_flags = SimpleNamespace(db=None, config=None)

        with patch(
            "memory_cli.config.init_create_global_or_project_store.init_memory_store",
            mock_init,
        ):
            result = handle_init(["--force"], global_flags)

        mock_init.assert_called_once_with(project=True, force=True)
        assert result.status == "ok"
