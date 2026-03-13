# =============================================================================
# Test Module: test_init_global_and_project.py
# Purpose: Test `memory init` for both global (~/.memory/) and project-scoped
#   (.memory/) stores, including --force reinit and error handling.
# Rationale: Init is the gateway command — if it fails or writes bad config,
#   nothing else works. These tests verify the full directory structure, config
#   content, DB file creation, and --force behavior.
# Responsibility:
#   - Test global init creates ~/.memory/ with correct contents
#   - Test project init creates .memory/ in cwd with correct contents
#   - Test --force overwrites config but preserves DB
#   - Test error when store already exists without --force
#   - Test directory structure is complete
#   - Test config.json content has correct absolute paths
# Organization:
#   1. Imports and fixtures
#   2. TestGlobalInit — global store tests
#   3. TestProjectInit — project-scoped store tests
#   4. TestForceReinit — --force behavior tests
#   5. TestInitErrors — error case tests
#   6. TestDirectoryStructure — verify created dirs and files
#   7. TestConfigContent — verify written config.json
#   8. TestPostInitInstructions — verify output messages
# =============================================================================

from __future__ import annotations

import json
import pytest
from pathlib import Path

from memory_cli.config.init_create_global_or_project_store import (
    init_memory_store,
    InitError,
)


# =============================================================================
# Fixtures
# =============================================================================

# --- fixture: fake_home (tmp_path, monkeypatch) ---
# Create a temp dir as fake home, monkeypatch Path.home() to return it.
# Ensures tests don't touch real ~/.memory/. Returns fake home path.

@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "fake_home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return home


# --- fixture: project_dir (tmp_path) ---
# Create a temp dir representing a project. Returns the project dir path.
# Used as cwd for project-scoped init.

@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "project"
    d.mkdir()
    return d


# --- fixture: existing_global_store (fake_home) ---
# Run init_memory_store() to create a global store, return store path.
# Used for testing --force and already-exists error.

@pytest.fixture
def existing_global_store(fake_home):
    store_path = init_memory_store(project=False)
    return store_path


# --- fixture: existing_project_store (project_dir) ---
# Run init_memory_store(project=True, cwd=project_dir) to create project store.
# Return store path.

@pytest.fixture
def existing_project_store(project_dir, fake_home):
    store_path = init_memory_store(project=True, cwd=project_dir)
    return store_path


# =============================================================================
# TestGlobalInit
# =============================================================================

class TestGlobalInit:
    """Test global memory store initialization at ~/.memory/."""

    # --- test_creates_global_store_dir ---
    # Call init_memory_store(project=False)
    # Assert ~/.memory/ directory exists
    def test_creates_global_store_dir(self, fake_home):
        init_memory_store(project=False)
        assert (fake_home / ".memory").is_dir()

    # --- test_returns_store_path ---
    # Assert return value == Path.home() / ".memory"
    def test_returns_store_path(self, fake_home):
        result = init_memory_store(project=False)
        assert result == fake_home / ".memory"

    # --- test_creates_config_json ---
    # Assert ~/.memory/config.json exists and is valid JSON
    def test_creates_config_json(self, fake_home):
        init_memory_store(project=False)
        config_path = fake_home / ".memory" / "config.json"
        assert config_path.is_file()
        data = json.loads(config_path.read_text())
        assert isinstance(data, dict)

    # --- test_creates_models_dir ---
    # Assert ~/.memory/models/ directory exists
    def test_creates_models_dir(self, fake_home):
        init_memory_store(project=False)
        assert (fake_home / ".memory" / "models").is_dir()

    # --- test_creates_db_file_with_schema ---
    # Assert ~/.memory/memory.db exists
    # Assert file is non-empty (schema bootstrapped at init time)
    def test_creates_db_file_with_schema(self, fake_home):
        init_memory_store(project=False)
        db_path = fake_home / ".memory" / "memory.db"
        assert db_path.is_file()
        assert db_path.stat().st_size > 0


# =============================================================================
# TestProjectInit
# =============================================================================

class TestProjectInit:
    """Test project-scoped memory store initialization at .memory/."""

    # --- test_creates_project_store_dir ---
    # Call init_memory_store(project=True, cwd=project_dir)
    # Assert project_dir/.memory/ directory exists
    def test_creates_project_store_dir(self, project_dir, fake_home):
        init_memory_store(project=True, cwd=project_dir)
        assert (project_dir / ".memory").is_dir()

    # --- test_returns_project_store_path ---
    # Assert return value == project_dir / ".memory"
    def test_returns_project_store_path(self, project_dir, fake_home):
        result = init_memory_store(project=True, cwd=project_dir)
        assert result == project_dir / ".memory"

    # --- test_creates_config_json_in_project ---
    # Assert project_dir/.memory/config.json exists
    def test_creates_config_json_in_project(self, project_dir, fake_home):
        init_memory_store(project=True, cwd=project_dir)
        assert (project_dir / ".memory" / "config.json").is_file()

    # --- test_creates_models_dir_in_project ---
    # Assert project_dir/.memory/models/ directory exists
    def test_creates_models_dir_in_project(self, project_dir, fake_home):
        init_memory_store(project=True, cwd=project_dir)
        assert (project_dir / ".memory" / "models").is_dir()

    # --- test_creates_empty_db_in_project ---
    # Assert project_dir/.memory/memory.db exists
    def test_creates_empty_db_in_project(self, project_dir, fake_home):
        init_memory_store(project=True, cwd=project_dir)
        assert (project_dir / ".memory" / "memory.db").is_file()

    # --- test_project_config_paths_are_absolute ---
    # Read config.json, assert db_path starts with /
    # Assert embedding.model_path starts with /
    # (No relative paths — must be absolute even for project scope)
    def test_project_config_paths_are_absolute(self, project_dir, fake_home):
        init_memory_store(project=True, cwd=project_dir)
        config_path = project_dir / ".memory" / "config.json"
        data = json.loads(config_path.read_text())
        assert data["db_path"].startswith("/")
        assert data["embedding"]["model_path"].startswith("/")


# =============================================================================
# TestForceReinit
# =============================================================================

class TestForceReinit:
    """Test --force flag behavior on existing stores."""

    # --- test_force_overwrites_config ---
    # Create store, modify config.json manually, reinit with --force
    # Assert config.json has been overwritten to defaults (EC-13)
    def test_force_overwrites_config(self, existing_global_store, fake_home):
        config_path = existing_global_store / "config.json"
        # Modify config manually
        config_path.write_text('{"modified": true}', encoding="utf-8")
        # Reinit with --force
        init_memory_store(project=False, force=True)
        # Config should be overwritten to defaults
        data = json.loads(config_path.read_text())
        assert "modified" not in data
        assert "embedding" in data

    # --- test_force_preserves_db ---
    # Create store, write some bytes to memory.db
    # Reinit with --force
    # Assert memory.db still has the same bytes (not truncated/deleted)
    def test_force_preserves_db(self, existing_global_store, fake_home):
        db_path = existing_global_store / "memory.db"
        # Write some data to the DB
        db_path.write_bytes(b"fake db data")
        # Reinit with --force
        init_memory_store(project=False, force=True)
        # DB data should be preserved
        assert db_path.read_bytes() == b"fake db data"

    # --- test_force_on_nonexistent_store_works ---
    # Call init_memory_store(force=True) when no store exists
    # Assert store created normally (force is a no-op here)
    def test_force_on_nonexistent_store_works(self, fake_home):
        result = init_memory_store(project=False, force=True)
        assert result.is_dir()
        assert (result / "config.json").is_file()


# =============================================================================
# TestInitErrors
# =============================================================================

class TestInitErrors:
    """Test error handling during init."""

    # --- test_existing_store_without_force_raises ---
    # Create store, call init again without --force
    # Assert InitError with reason="already_exists" (EC-11)
    def test_existing_store_without_force_raises(self, existing_global_store, fake_home):
        with pytest.raises(InitError) as exc_info:
            init_memory_store(project=False, force=False)
        assert exc_info.value.reason == "already_exists"

    # --- test_error_message_suggests_force ---
    # Catch InitError, assert "--force" appears in the message
    def test_error_message_suggests_force(self, existing_global_store, fake_home):
        with pytest.raises(InitError) as exc_info:
            init_memory_store(project=False, force=False)
        assert "--force" in str(exc_info.value)

    # --- test_permission_denied_raises ---
    # Create a read-only parent directory
    # Call init_memory_store -> assert InitError with reason="permission_denied"
    # (May need to skip on some CI environments)
    @pytest.mark.skipif(
        __import__("os").getuid() == 0,
        reason="root bypasses permission checks",
    )
    def test_permission_denied_raises(self, tmp_path, monkeypatch):
        readonly_parent = tmp_path / "readonly"
        readonly_parent.mkdir()
        readonly_parent.chmod(0o444)
        try:
            fake_readonly_home = readonly_parent / "home"
            monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_readonly_home))
            with pytest.raises(InitError) as exc_info:
                init_memory_store(project=False)
            assert exc_info.value.reason == "permission_denied"
        finally:
            readonly_parent.chmod(0o755)


# =============================================================================
# TestDirectoryStructure
# =============================================================================

class TestDirectoryStructure:
    """Verify the complete directory structure created by init."""

    # --- test_global_structure ---
    # After global init, verify:
    #   ~/.memory/           (dir)
    #   ~/.memory/config.json (file)
    #   ~/.memory/memory.db   (file)
    #   ~/.memory/models/     (dir)
    def test_global_structure(self, fake_home):
        init_memory_store(project=False)
        store = fake_home / ".memory"
        assert store.is_dir()
        assert (store / "config.json").is_file()
        assert (store / "memory.db").is_file()
        assert (store / "models").is_dir()

    # --- test_project_structure ---
    # After project init, verify:
    #   .memory/              (dir)
    #   .memory/config.json   (file)
    #   .memory/memory.db     (file)
    #   .memory/models/       (dir)
    def test_project_structure(self, project_dir, fake_home):
        init_memory_store(project=True, cwd=project_dir)
        store = project_dir / ".memory"
        assert store.is_dir()
        assert (store / "config.json").is_file()
        assert (store / "memory.db").is_file()
        assert (store / "models").is_dir()


# =============================================================================
# TestConfigContent
# =============================================================================

class TestConfigContent:
    """Verify the content of the written config.json."""

    # --- test_config_is_valid_json ---
    # Read config.json, json.loads() succeeds
    def test_config_is_valid_json(self, fake_home):
        init_memory_store(project=False)
        config_path = fake_home / ".memory" / "config.json"
        data = json.loads(config_path.read_text())
        assert isinstance(data, dict)

    # --- test_config_has_all_sections ---
    # Assert top-level keys: db_path, embedding, search, haiku, output
    def test_config_has_all_sections(self, fake_home):
        init_memory_store(project=False)
        config_path = fake_home / ".memory" / "config.json"
        data = json.loads(config_path.read_text())
        assert "db_path" in data
        assert "embedding" in data
        assert "search" in data
        assert "haiku" in data
        assert "output" in data

    # --- test_db_path_is_absolute_and_inside_store ---
    # Assert db_path == str(store_path / "memory.db")
    # Assert it starts with "/"
    def test_db_path_is_absolute_and_inside_store(self, fake_home):
        store = init_memory_store(project=False)
        config_path = store / "config.json"
        data = json.loads(config_path.read_text())
        assert data["db_path"] == str(store / "memory.db")
        assert data["db_path"].startswith("/")

    # --- test_model_path_is_absolute_and_inside_store ---
    # Assert embedding.model_path == str(store_path / "models" / "default.gguf")
    def test_model_path_is_absolute_and_inside_store(self, fake_home):
        store = init_memory_store(project=False)
        config_path = store / "config.json"
        data = json.loads(config_path.read_text())
        assert data["embedding"]["model_path"] == str(store / "models" / "default.gguf")

    # --- test_default_values_match_spec ---
    # Assert embedding.n_ctx == 2048
    # Assert embedding.n_batch == 512
    # Assert embedding.dimensions == 768
    # Assert search.default_limit == 10
    # Assert search.fan_out_depth == 1
    # Assert search.decay_rate == 0.25
    # Assert search.temporal_decay_enabled == True
    # Assert haiku.api_key_env_var == "ANTHROPIC_API_KEY"
    # Assert output.default_format == "json"
    def test_default_values_match_spec(self, fake_home):
        store = init_memory_store(project=False)
        data = json.loads((store / "config.json").read_text())
        assert data["embedding"]["n_ctx"] == 2048
        assert data["embedding"]["n_batch"] == 512
        assert data["embedding"]["dimensions"] == 768
        assert data["search"]["default_limit"] == 10
        assert data["search"]["fan_out_depth"] == 1
        assert data["search"]["decay_rate"] == 0.25
        assert data["search"]["temporal_decay_enabled"] is True
        assert data["haiku"]["api_key_env_var"] == "ANTHROPIC_API_KEY"
        assert data["output"]["default_format"] == "json"

    # --- test_config_is_human_readable ---
    # Read raw file content, assert it contains newlines (indented JSON)
    # (Verifies indent=2 formatting)
    def test_config_is_human_readable(self, fake_home):
        store = init_memory_store(project=False)
        raw = (store / "config.json").read_text()
        assert "\n" in raw


# =============================================================================
# TestPostInitInstructions
# =============================================================================

class TestPostInitInstructions:
    """Verify post-init output messages."""

    # --- test_global_init_prints_store_location ---
    # Capture stdout, assert it mentions ~/.memory/ path
    def test_global_init_prints_store_location(self, fake_home, capsys):
        store = init_memory_store(project=False)
        captured = capsys.readouterr()
        assert str(store) in captured.out

    # --- test_project_init_prints_store_location ---
    # Capture stdout, assert it mentions .memory/ path
    def test_project_init_prints_store_location(self, project_dir, fake_home, capsys):
        store = init_memory_store(project=True, cwd=project_dir)
        captured = capsys.readouterr()
        assert str(store) in captured.out

    # --- test_instructions_mention_model_download ---
    # Assert output mentions downloading or placing an embedding model
    def test_instructions_mention_model_download(self, fake_home, capsys):
        init_memory_store(project=False)
        captured = capsys.readouterr()
        assert "model" in captured.out.lower() or "gguf" in captured.out.lower()

    # --- test_instructions_mention_next_command ---
    # Assert output mentions a next command to try (e.g., memory neuron add)
    def test_instructions_mention_next_command(self, fake_home, capsys):
        init_memory_store(project=False)
        captured = capsys.readouterr()
        assert "memory" in captured.out
