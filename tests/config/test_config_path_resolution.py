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


# =============================================================================
# Fixtures
# =============================================================================

# --- fixture: tmp_home (monkeypatch) ---
# Create a temp dir as fake home, monkeypatch Path.home() to return it.
# This isolates tests from the real ~/.memory/ directory.

# --- fixture: project_with_memory_dir ---
# Create tmp_dir/project/.memory/config.json with valid content.
# Return the project dir path.

# --- fixture: nested_project_dir ---
# Create tmp_dir/project/.memory/config.json
# Create tmp_dir/project/src/deep/nested/ as cwd
# Return the nested dir path (ancestor walk should find project config).

# --- fixture: global_config ---
# Create fake_home/.memory/config.json with valid content.
# Return the config file path.


# =============================================================================
# TestConfigOverride
# =============================================================================

class TestConfigOverride:
    """Test that --config flag overrides all other resolution."""

    # --- test_explicit_config_path_used_directly ---
    # Create a config at /tmp/custom/config.json
    # Call resolve_config_path(config_override="/tmp/custom/config.json")
    # Assert returned path == /tmp/custom/config.json

    # --- test_nonexistent_config_override_raises ---
    # Call resolve_config_path(config_override="/nonexistent/config.json")
    # Assert raises FileNotFoundError (EC-1)

    # --- test_relative_config_override_resolved_to_absolute ---
    # Call resolve_config_path(config_override="./some/config.json")
    # from a cwd that has that file
    # Assert returned path is absolute (EC-13)

    # --- test_config_override_skips_ancestor_walk ---
    # Create both project .memory/config.json and custom config
    # Call with config_override pointing to custom
    # Assert custom config is returned, not project config

    pass


# =============================================================================
# TestAncestorWalk
# =============================================================================

class TestAncestorWalk:
    """Test ancestor directory walk for .memory/config.json."""

    # --- test_config_in_cwd ---
    # cwd has .memory/config.json -> found immediately

    # --- test_config_in_parent ---
    # cwd is project/src/, config at project/.memory/config.json
    # Assert found via parent walk

    # --- test_config_in_grandparent ---
    # cwd is project/src/deep/, config at project/.memory/config.json
    # Assert found via grandparent walk (EC-7)

    # --- test_nearest_ancestor_wins ---
    # Create project/.memory/config.json (inner)
    # Create workspace/.memory/config.json (outer, parent of project)
    # cwd is project/src/
    # Assert inner project config is returned, not outer (EC-8)

    # --- test_no_ancestor_config_continues_to_global ---
    # No .memory/ in any ancestor, but global exists
    # Assert global config returned (tested more in TestGlobalFallback)

    pass


# =============================================================================
# TestGlobalFallback
# =============================================================================

class TestGlobalFallback:
    """Test fallback to ~/.memory/config.json."""

    # --- test_global_config_used_when_no_project_config ---
    # No .memory/ in ancestors, ~/.memory/config.json exists
    # Assert global config returned

    # --- test_project_config_preferred_over_global ---
    # Both project and global exist
    # Assert project config returned, not global (EC-8)

    # --- test_global_config_path_uses_home ---
    # Verify _global_config_path() returns Path.home() / ".memory" / "config.json"

    pass


# =============================================================================
# TestNoConfigAnywhere
# =============================================================================

class TestNoConfigAnywhere:
    """Test error handling when no config exists."""

    # --- test_no_config_anywhere_raises_file_not_found ---
    # No --config, no .memory/ in ancestors, no ~/.memory/
    # Assert FileNotFoundError raised (EC-2)

    # --- test_error_message_suggests_memory_init ---
    # Catch the FileNotFoundError, assert "memory init" appears in message

    pass
