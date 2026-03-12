# =============================================================================
# Test Module: test_config_path_resolution.py
# Purpose: Verify config path resolution: --config override, ancestor walk
#   for .memory/config.json, and global ~/.memory/config.json fallback.
# Rationale: Path resolution is the first step of every CLI invocation. Getting
#   it wrong means loading the wrong config or failing to find any. These tests
#   exercise every branch of the resolution strategy.
# Responsibility:
#   - Test --config override takes highest priority
#   - Test ancestor walk finds nearest .memory/config.json
#   - Test global fallback when no project config exists
#   - Test error when no config exists anywhere
#   - Test edge cases: deeply nested cwd, relative --config path, etc.
# Organization:
#   1. Imports and fixtures
#   2. TestConfigOverride — --config flag tests
#   3. TestAncestorWalk — directory traversal tests
#   4. TestGlobalFallback — ~/.memory/ tests
#   5. TestNoConfigAnywhere — error case tests
# =============================================================================

from __future__ import annotations

import pytest
from pathlib import Path

from memory_cli.config.config_path_resolution_ancestor_walk import (
    resolve_config_path,
    _walk_ancestors,
    _global_config_path,
)


# =============================================================================
# Fixtures
# =============================================================================

# --- fixture: tmp_home (monkeypatch) ---
# Create a temp dir as fake home, monkeypatch Path.home() to return it.
# This isolates tests from the real ~/.memory/ directory.

@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    return fake_home


# --- fixture: project_with_memory_dir ---
# Create tmp_dir/project/.memory/config.json with valid content.
# Return the project dir path.

@pytest.fixture
def project_with_memory_dir(tmp_path):
    project_dir = tmp_path / "project"
    memory_dir = project_dir / ".memory"
    memory_dir.mkdir(parents=True)
    config_file = memory_dir / "config.json"
    config_file.write_text('{"db_path": "/tmp/memory.db"}', encoding="utf-8")
    return project_dir


# --- fixture: nested_project_dir ---
# Create tmp_dir/project/.memory/config.json
# Create tmp_dir/project/src/deep/nested/ as cwd
# Return the nested dir path (ancestor walk should find project config).

@pytest.fixture
def nested_project_dir(tmp_path):
    project_dir = tmp_path / "project"
    memory_dir = project_dir / ".memory"
    memory_dir.mkdir(parents=True)
    config_file = memory_dir / "config.json"
    config_file.write_text('{"db_path": "/tmp/memory.db"}', encoding="utf-8")
    nested = project_dir / "src" / "deep" / "nested"
    nested.mkdir(parents=True)
    return nested


# --- fixture: global_config ---
# Create fake_home/.memory/config.json with valid content.
# Return the config file path.

@pytest.fixture
def global_config(tmp_home):
    memory_dir = tmp_home / ".memory"
    memory_dir.mkdir()
    config_file = memory_dir / "config.json"
    config_file.write_text('{"db_path": "/tmp/memory.db"}', encoding="utf-8")
    return config_file


# =============================================================================
# TestConfigOverride
# =============================================================================

class TestConfigOverride:
    """Test that --config flag overrides all other resolution."""

    # --- test_explicit_config_path_used_directly ---
    # Create a config at /tmp/custom/config.json
    # Call resolve_config_path(config_override="/tmp/custom/config.json")
    # Assert returned path == /tmp/custom/config.json
    def test_explicit_config_path_used_directly(self, tmp_path):
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        custom_config = custom_dir / "config.json"
        custom_config.write_text("{}", encoding="utf-8")

        result = resolve_config_path(config_override=str(custom_config))
        assert result == custom_config

    # --- test_nonexistent_config_override_raises ---
    # Call resolve_config_path(config_override="/nonexistent/config.json")
    # Assert raises FileNotFoundError (EC-1)
    def test_nonexistent_config_override_raises(self):
        with pytest.raises(FileNotFoundError):
            resolve_config_path(config_override="/nonexistent/config.json")

    # --- test_relative_config_override_resolved_to_absolute ---
    # Call resolve_config_path(config_override="./some/config.json")
    # from a cwd that has that file
    # Assert returned path is absolute (EC-13)
    def test_relative_config_override_resolved_to_absolute(self, tmp_path):
        some_dir = tmp_path / "some"
        some_dir.mkdir()
        config_file = some_dir / "config.json"
        config_file.write_text("{}", encoding="utf-8")

        result = resolve_config_path(
            config_override="some/config.json",
            cwd=tmp_path,
        )
        assert result.is_absolute()
        assert result == config_file

    # --- test_config_override_skips_ancestor_walk ---
    # Create both project .memory/config.json and custom config
    # Call with config_override pointing to custom
    # Assert custom config is returned, not project config
    def test_config_override_skips_ancestor_walk(self, project_with_memory_dir, tmp_path):
        custom_config = tmp_path / "custom_config.json"
        custom_config.write_text("{}", encoding="utf-8")

        result = resolve_config_path(
            config_override=str(custom_config),
            cwd=project_with_memory_dir,
        )
        assert result == custom_config


# =============================================================================
# TestAncestorWalk
# =============================================================================

class TestAncestorWalk:
    """Test ancestor directory walk for .memory/config.json."""

    # --- test_config_in_cwd ---
    # cwd has .memory/config.json -> found immediately
    def test_config_in_cwd(self, project_with_memory_dir, tmp_home):
        result = resolve_config_path(cwd=project_with_memory_dir)
        assert result == project_with_memory_dir / ".memory" / "config.json"

    # --- test_config_in_parent ---
    # cwd is project/src/, config at project/.memory/config.json
    # Assert found via parent walk
    def test_config_in_parent(self, project_with_memory_dir, tmp_home):
        src_dir = project_with_memory_dir / "src"
        src_dir.mkdir()
        result = resolve_config_path(cwd=src_dir)
        assert result == project_with_memory_dir / ".memory" / "config.json"

    # --- test_config_in_grandparent ---
    # cwd is project/src/deep/, config at project/.memory/config.json
    # Assert found via grandparent walk (EC-7)
    def test_config_in_grandparent(self, nested_project_dir, tmp_home):
        result = resolve_config_path(cwd=nested_project_dir)
        assert result.name == "config.json"
        assert ".memory" in str(result)

    # --- test_nearest_ancestor_wins ---
    # Create project/.memory/config.json (inner)
    # Create workspace/.memory/config.json (outer, parent of project)
    # cwd is project/src/
    # Assert inner project config is returned, not outer (EC-8)
    def test_nearest_ancestor_wins(self, tmp_path, tmp_home):
        workspace = tmp_path / "workspace"
        outer_memory = workspace / ".memory"
        outer_memory.mkdir(parents=True)
        (outer_memory / "config.json").write_text('{"scope": "outer"}', encoding="utf-8")

        project = workspace / "project"
        inner_memory = project / ".memory"
        inner_memory.mkdir(parents=True)
        (inner_memory / "config.json").write_text('{"scope": "inner"}', encoding="utf-8")

        src = project / "src"
        src.mkdir()

        result = resolve_config_path(cwd=src)
        assert result == project / ".memory" / "config.json"

    # --- test_no_ancestor_config_continues_to_global ---
    # No .memory/ in any ancestor, but global exists
    # Assert global config returned (tested more in TestGlobalFallback)
    def test_no_ancestor_config_continues_to_global(self, tmp_path, global_config):
        isolated_dir = tmp_path / "isolated"
        isolated_dir.mkdir()
        result = resolve_config_path(cwd=isolated_dir)
        assert result == global_config


# =============================================================================
# TestGlobalFallback
# =============================================================================

class TestGlobalFallback:
    """Test fallback to ~/.memory/config.json."""

    # --- test_global_config_used_when_no_project_config ---
    # No .memory/ in ancestors, ~/.memory/config.json exists
    # Assert global config returned
    def test_global_config_used_when_no_project_config(self, tmp_path, global_config):
        isolated_dir = tmp_path / "no_project"
        isolated_dir.mkdir()
        result = resolve_config_path(cwd=isolated_dir)
        assert result == global_config

    # --- test_project_config_preferred_over_global ---
    # Both project and global exist
    # Assert project config returned, not global (EC-8)
    def test_project_config_preferred_over_global(
        self, project_with_memory_dir, global_config
    ):
        result = resolve_config_path(cwd=project_with_memory_dir)
        assert result == project_with_memory_dir / ".memory" / "config.json"
        assert result != global_config

    # --- test_global_config_path_uses_home ---
    # Verify _global_config_path() returns Path.home() / ".memory" / "config.json"
    def test_global_config_path_uses_home(self, tmp_home):
        global_path = _global_config_path()
        assert global_path == tmp_home / ".memory" / "config.json"


# =============================================================================
# TestNoConfigAnywhere
# =============================================================================

class TestNoConfigAnywhere:
    """Test error handling when no config exists."""

    # --- test_no_config_anywhere_raises_file_not_found ---
    # No --config, no .memory/ in ancestors, no ~/.memory/
    # Assert FileNotFoundError raised (EC-2)
    def test_no_config_anywhere_raises_file_not_found(self, tmp_path, tmp_home):
        isolated_dir = tmp_path / "empty"
        isolated_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            resolve_config_path(cwd=isolated_dir)

    # --- test_error_message_suggests_memory_init ---
    # Catch the FileNotFoundError, assert "memory init" appears in message
    def test_error_message_suggests_memory_init(self, tmp_path, tmp_home):
        isolated_dir = tmp_path / "empty2"
        isolated_dir.mkdir()
        with pytest.raises(FileNotFoundError) as exc_info:
            resolve_config_path(cwd=isolated_dir)
        assert "memory init" in str(exc_info.value)
