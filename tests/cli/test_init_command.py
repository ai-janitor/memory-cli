# =============================================================================
# FILE: tests/cli/test_init_command.py
# PURPOSE: Test `memory init` dispatch, delegation, flag parsing, and
#          error handling (already initialized, --force, bad flags).
# RATIONALE: Init is the only top-level exception to noun-verb grammar.
#            It must be tested separately from the noun dispatch path to
#            verify it's recognized before noun resolution and delegates
#            correctly to the config/storage layer.
# RESPONSIBILITY:
#   - Test handle_init() with various flag combinations
#   - Test --force behavior when store already exists
#   - Test error when store already exists without --force
#   - Test that init creates DB and config via storage layer
#   - Test _parse_init_flags() for valid and invalid inputs
# ORGANIZATION:
#   1. Fixtures (mock storage layer, temp paths)
#   2. Test class: TestInitHappyPath
#   3. Test class: TestInitAlreadyExists
#   4. Test class: TestInitFlagParsing
# =============================================================================

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

from memory_cli.cli.init_command_top_level_exception import handle_init, _parse_init_flags


# =============================================================================
# TEST: HAPPY PATH
# =============================================================================
class TestInitHappyPath:
    """Test successful init scenarios."""

    def test_init_default_creates_local_store(self, tmp_path: Path) -> None:
        """Init with no flags -> creates LOCAL store (.memory/ in cwd), returns success.

        Pseudo-logic:
        1. Mock init_memory_store to return tmp_path/.memory
        2. result = handle_init([], global_flags)
        3. Assert result.status == "ok"
        4. Assert init_memory_store called with project=True (local default)
        """
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
        assert "database" in result.data
        assert "config" in result.data

    def test_init_global_flag_creates_global_store(self, tmp_path: Path) -> None:
        """Init with --global -> creates GLOBAL store (~/.memory/), returns success.

        Pseudo-logic:
        1. Mock init_memory_store to return tmp_path/.memory
        2. result = handle_init(["--global"], global_flags)
        3. Assert result.status == "ok"
        4. Assert init_memory_store called with project=False (global)
        """
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

    def test_init_returns_created_paths(self, tmp_path: Path) -> None:
        """Result data includes the paths of created files.

        Pseudo-logic:
        1. Mock init_memory_store with known store path
        2. result = handle_init([], global_flags)
        3. Assert result.data["database"] and result.data["config"] are correct
        """
        mock_store = tmp_path / ".memory"
        mock_store.mkdir()
        mock_init = MagicMock(return_value=mock_store)
        global_flags = SimpleNamespace(db=None, config=None)

        with patch(
            "memory_cli.config.init_create_global_or_project_store.init_memory_store",
            mock_init,
        ):
            result = handle_init([], global_flags)

        assert result.status == "ok"
        assert result.data["database"] == str(mock_store / "memory.db")
        assert result.data["config"] == str(mock_store / "config.json")


# =============================================================================
# TEST: ALREADY EXISTS
# =============================================================================
class TestInitAlreadyExists:
    """Test init when store already exists."""

    def test_init_without_force_errors_on_existing_store(self) -> None:
        """Store exists + no --force -> error result from init_memory_store.

        Pseudo-logic:
        1. Mock init_memory_store to raise InitError("already_exists")
        2. result = handle_init([], global_flags)
        3. Assert result.status == "error"
        4. Assert "already exists" in result.error
        """
        from memory_cli.config.init_create_global_or_project_store import InitError

        mock_init = MagicMock(
            side_effect=InitError("already_exists", "Memory store already exists at /tmp/.memory. Use --force to overwrite the config (DB will be preserved).")
        )
        global_flags = SimpleNamespace(db=None, config=None)

        with patch(
            "memory_cli.config.init_create_global_or_project_store.init_memory_store",
            mock_init,
        ):
            result = handle_init([], global_flags)

        assert result.status == "error"
        assert "already exists" in result.error

    def test_init_with_force_overwrites_existing(self, tmp_path: Path) -> None:
        """Store exists + --force -> succeeds, returns success.

        Pseudo-logic:
        1. Mock init_memory_store to succeed with force=True
        2. result = handle_init(["--force"], global_flags)
        3. Assert result.status == "ok"
        4. Assert init_memory_store called with force=True
        """
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


# =============================================================================
# TEST: FLAG PARSING
# =============================================================================
class TestInitFlagParsing:
    """Test _parse_init_flags()."""

    def test_no_flags_returns_defaults(self) -> None:
        """Empty args -> force=False, global_store=False.

        Pseudo-logic:
        1. result = _parse_init_flags([])
        2. Assert result == {"force": False, "global_store": False}
        """
        result = _parse_init_flags([])
        assert result == {"force": False, "global_store": False}

    def test_force_flag_parsed(self) -> None:
        """--force -> force=True, global_store=False.

        Pseudo-logic:
        1. result = _parse_init_flags(["--force"])
        2. Assert result == {"force": True, "global_store": False}
        """
        result = _parse_init_flags(["--force"])
        assert result == {"force": True, "global_store": False}

    def test_global_flag_parsed(self) -> None:
        """--global -> force=False, global_store=True.

        Pseudo-logic:
        1. result = _parse_init_flags(["--global"])
        2. Assert result == {"force": False, "global_store": True}
        """
        result = _parse_init_flags(["--global"])
        assert result == {"force": False, "global_store": True}

    def test_unknown_flag_raises_error(self) -> None:
        """Unknown flag -> error.

        Pseudo-logic:
        1. pytest.raises(ValueError)
        2. Call _parse_init_flags(["--unknown"])
        """
        with pytest.raises(ValueError):
            _parse_init_flags(["--unknown"])

    def test_positional_args_raise_error(self) -> None:
        """Positional args -> error (init takes none).

        Pseudo-logic:
        1. pytest.raises(ValueError)
        2. Call _parse_init_flags(["something"])
        """
        with pytest.raises(ValueError):
            _parse_init_flags(["something"])

    def test_old_project_flag_raises_error(self) -> None:
        """--project is no longer recognized -> error.

        Pseudo-logic:
        1. pytest.raises(ValueError)
        2. Call _parse_init_flags(["--project"])
        """
        with pytest.raises(ValueError, match="Unknown flag for init"):
            _parse_init_flags(["--project"])
