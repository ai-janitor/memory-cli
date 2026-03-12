# =============================================================================
# Test Module: test_config_loader_validator.py
# Purpose: Test the full config loading pipeline: resolve -> read -> parse ->
#   merge defaults -> apply overrides -> validate -> return typed config.
# Rationale: This is the integration-level test for config. Unit tests cover
#   individual pieces (schema, path resolution); these tests verify the
#   pipeline works end-to-end and surfaces correct errors at each stage.
# Responsibility:
#   - Test successful load with valid config file
#   - Test --db override is applied correctly
#   - Test defaults are filled for missing keys
#   - Test error propagation from each pipeline stage
#   - Test ConfigLoadError has correct stage and details
# Organization:
#   1. Imports and fixtures
#   2. TestSuccessfulLoad — happy path tests
#   3. TestDbOverride — --db flag behavior
#   4. TestDefaultsMerging — partial configs get defaults
#   5. TestErrorStages — error from each pipeline stage
#   6. TestReadConfigFile — _read_config_file unit tests
#   7. TestApplyOverrides — _apply_overrides unit tests
# =============================================================================

from __future__ import annotations

import json
import pytest
from pathlib import Path

from memory_cli.config.config_loader_and_validator import (
    load_config,
    MemoryConfig,
    ConfigLoadError,
    _read_config_file,
    _apply_overrides,
)
from memory_cli.config.config_schema_and_defaults import CONFIG_DEFAULTS


# =============================================================================
# Fixtures
# =============================================================================

# --- fixture: valid_config_file (tmp_path) ---
# Create a tmp dir with .memory/config.json containing a complete valid config.
# Monkeypatch Path.home() or pass cwd to isolate from real config.
# Return the path to the config file and the expected config values.

@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    return fake_home


@pytest.fixture
def valid_config_file(tmp_path):
    memory_dir = tmp_path / ".memory"
    memory_dir.mkdir()
    config = {
        "db_path": str(tmp_path / ".memory" / "memory.db"),
        "embedding": {
            "model_path": str(tmp_path / ".memory" / "models" / "default.gguf"),
            "n_ctx": 2048,
            "n_batch": 512,
            "dimensions": 768,
        },
        "search": {
            "default_limit": 10,
            "fan_out_depth": 1,
            "decay_rate": 0.25,
            "temporal_decay_enabled": True,
        },
        "haiku": {
            "api_key_env_var": "ANTHROPIC_API_KEY",
            "model": "claude-haiku-4-5-20251001",
        },
        "output": {
            "default_format": "json",
        },
    }
    config_path = memory_dir / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return tmp_path, config


# --- fixture: minimal_config_file (tmp_path) ---
# Create config.json with only db_path and embedding.model_path set.
# All other fields should come from defaults after loading.

@pytest.fixture
def minimal_config_file(tmp_path):
    memory_dir = tmp_path / ".memory"
    memory_dir.mkdir()
    config = {
        "db_path": str(tmp_path / ".memory" / "memory.db"),
        "embedding": {
            "model_path": str(tmp_path / ".memory" / "models" / "default.gguf"),
        },
    }
    config_path = memory_dir / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return tmp_path, config


# --- fixture: config_dir ---
# Helper to create a .memory/config.json in a tmp dir with given content.
# Returns the parent dir (for use as cwd).

@pytest.fixture
def config_dir(tmp_path):
    def _make(content: dict) -> Path:
        memory_dir = tmp_path / ".memory"
        memory_dir.mkdir(exist_ok=True)
        (memory_dir / "config.json").write_text(json.dumps(content), encoding="utf-8")
        return tmp_path
    return _make


# =============================================================================
# TestSuccessfulLoad
# =============================================================================

class TestSuccessfulLoad:
    """Test load_config returns a valid MemoryConfig on happy path."""

    # --- test_load_complete_config ---
    # Create a valid config.json with all fields
    # Call load_config(cwd=project_dir)
    # Assert returns MemoryConfig with all fields matching file contents
    def test_load_complete_config(self, valid_config_file):
        project_dir, expected = valid_config_file
        result = load_config(cwd=project_dir)
        assert result.db_path == expected["db_path"]
        assert result.embedding.n_ctx == expected["embedding"]["n_ctx"]

    # --- test_load_returns_memory_config_type ---
    # Assert return value is instance of MemoryConfig (ConfigSchema)
    def test_load_returns_memory_config_type(self, valid_config_file):
        project_dir, _ = valid_config_file
        result = load_config(cwd=project_dir)
        assert isinstance(result, MemoryConfig)

    # --- test_loaded_config_has_correct_values ---
    # Set specific values in config.json (e.g., n_ctx=4096)
    # Load and assert the specific values come through
    def test_loaded_config_has_correct_values(self, config_dir):
        project_dir = config_dir({
            "db_path": "/tmp/memory.db",
            "embedding": {
                "model_path": "/tmp/models/default.gguf",
                "n_ctx": 4096,
                "n_batch": 512,
                "dimensions": 768,
            },
            "search": {
                "default_limit": 10,
                "fan_out_depth": 1,
                "decay_rate": 0.25,
                "temporal_decay_enabled": True,
            },
            "haiku": {"api_key_env_var": "ANTHROPIC_API_KEY", "model": "claude-haiku-4-5-20251001"},
            "output": {"default_format": "json"},
        })
        result = load_config(cwd=project_dir)
        assert result.embedding.n_ctx == 4096


# =============================================================================
# TestDbOverride
# =============================================================================

class TestDbOverride:
    """Test --db flag override behavior."""

    # --- test_db_override_replaces_config_db_path ---
    # Config file has db_path="/original/path.db"
    # Call load_config(db_override="/override/path.db")
    # Assert returned config.db_path == "/override/path.db"
    def test_db_override_replaces_config_db_path(self, config_dir):
        project_dir = config_dir({
            "db_path": "/original/path.db",
            "embedding": {
                "model_path": "/tmp/models/default.gguf",
                "n_ctx": 2048,
                "n_batch": 512,
                "dimensions": 768,
            },
            "search": {
                "default_limit": 10,
                "fan_out_depth": 1,
                "decay_rate": 0.25,
                "temporal_decay_enabled": True,
            },
            "haiku": {"api_key_env_var": "ANTHROPIC_API_KEY", "model": "claude-haiku-4-5-20251001"},
            "output": {"default_format": "json"},
        })
        result = load_config(db_override="/override/path.db", cwd=project_dir)
        assert result.db_path == "/override/path.db"

    # --- test_db_override_none_preserves_config ---
    # Call load_config(db_override=None)
    # Assert db_path from config file is preserved
    def test_db_override_none_preserves_config(self, config_dir):
        project_dir = config_dir({
            "db_path": "/original/path.db",
            "embedding": {
                "model_path": "/tmp/models/default.gguf",
                "n_ctx": 2048,
                "n_batch": 512,
                "dimensions": 768,
            },
            "search": {
                "default_limit": 10,
                "fan_out_depth": 1,
                "decay_rate": 0.25,
                "temporal_decay_enabled": True,
            },
            "haiku": {"api_key_env_var": "ANTHROPIC_API_KEY", "model": "claude-haiku-4-5-20251001"},
            "output": {"default_format": "json"},
        })
        result = load_config(db_override=None, cwd=project_dir)
        assert result.db_path == "/original/path.db"

    # --- test_db_override_relative_path_fails_validation ---
    # Call load_config(db_override="relative/path.db")
    # Assert ConfigLoadError at validate stage (EC-9)
    def test_db_override_relative_path_fails_validation(self, config_dir):
        project_dir = config_dir({
            "db_path": "/original/path.db",
            "embedding": {
                "model_path": "/tmp/models/default.gguf",
                "n_ctx": 2048,
                "n_batch": 512,
                "dimensions": 768,
            },
            "search": {
                "default_limit": 10,
                "fan_out_depth": 1,
                "decay_rate": 0.25,
                "temporal_decay_enabled": True,
            },
            "haiku": {"api_key_env_var": "ANTHROPIC_API_KEY", "model": "claude-haiku-4-5-20251001"},
            "output": {"default_format": "json"},
        })
        with pytest.raises(ConfigLoadError) as exc_info:
            load_config(db_override="relative/path.db", cwd=project_dir)
        assert exc_info.value.stage == "validate"


# =============================================================================
# TestDefaultsMerging
# =============================================================================

class TestDefaultsMerging:
    """Test that missing config keys get filled from defaults."""

    # --- test_minimal_config_gets_all_defaults ---
    # Config file has only db_path and model_path
    # Load -> assert n_ctx==2048, decay_rate==0.25, etc.
    def test_minimal_config_gets_all_defaults(self, minimal_config_file):
        project_dir, _ = minimal_config_file
        result = load_config(cwd=project_dir)
        assert result.embedding.n_ctx == 2048
        assert result.search.decay_rate == 0.25
        assert result.search.default_limit == 10

    # --- test_partial_section_gets_section_defaults ---
    # Config has embedding.n_ctx=4096 but no n_batch
    # Load -> assert n_batch==512 (default), n_ctx==4096 (user value)
    def test_partial_section_gets_section_defaults(self, config_dir):
        project_dir = config_dir({
            "db_path": "/tmp/memory.db",
            "embedding": {
                "model_path": "/tmp/models/default.gguf",
                "n_ctx": 4096,
            },
        })
        result = load_config(cwd=project_dir)
        assert result.embedding.n_ctx == 4096
        assert result.embedding.n_batch == CONFIG_DEFAULTS["embedding"]["n_batch"]

    # --- test_all_defaults_config_is_valid ---
    # Config written by init (all defaults) should load without errors (EC-10)
    def test_all_defaults_config_is_valid(self, config_dir):
        import copy
        config = copy.deepcopy(CONFIG_DEFAULTS)
        config["db_path"] = "/tmp/memory.db"
        config["embedding"]["model_path"] = "/tmp/models/default.gguf"
        project_dir = config_dir(config)
        result = load_config(cwd=project_dir)
        assert result.db_path == "/tmp/memory.db"


# =============================================================================
# TestErrorStages
# =============================================================================

class TestErrorStages:
    """Test error propagation from each pipeline stage."""

    # --- test_resolve_stage_error ---
    # No config file anywhere, no --config
    # Assert ConfigLoadError with stage="resolve"
    def test_resolve_stage_error(self, tmp_path, tmp_home):
        isolated = tmp_path / "isolated"
        isolated.mkdir()
        with pytest.raises(ConfigLoadError) as exc_info:
            load_config(cwd=isolated)
        assert exc_info.value.stage == "resolve"

    # --- test_read_stage_io_error ---
    # Config path exists but is unreadable (EC-14)
    # Assert ConfigLoadError with stage="read"
    @pytest.mark.skipif(
        __import__("os").getuid() == 0,
        reason="root bypasses permission checks",
    )
    def test_read_stage_io_error(self, tmp_path):
        # Create a file, make it unreadable, then pass it via --config override
        config_file = tmp_path / "config.json"
        config_file.write_text("{}", encoding="utf-8")
        config_file.chmod(0o000)
        try:
            with pytest.raises(ConfigLoadError) as exc_info:
                load_config(config_override=str(config_file), cwd=tmp_path)
            assert exc_info.value.stage == "read"
        finally:
            config_file.chmod(0o644)

    # --- test_parse_stage_invalid_json ---
    # Config file contains "not json at all"
    # Assert ConfigLoadError with stage="parse" (EC-4)
    def test_parse_stage_invalid_json(self, tmp_path):
        memory_dir = tmp_path / ".memory"
        memory_dir.mkdir()
        (memory_dir / "config.json").write_text("not json at all", encoding="utf-8")
        with pytest.raises(ConfigLoadError) as exc_info:
            load_config(cwd=tmp_path)
        assert exc_info.value.stage == "parse"

    # --- test_parse_stage_empty_file ---
    # Config file is empty (0 bytes)
    # Assert ConfigLoadError with stage="parse" (EC-3)
    def test_parse_stage_empty_file(self, tmp_path):
        memory_dir = tmp_path / ".memory"
        memory_dir.mkdir()
        (memory_dir / "config.json").write_text("", encoding="utf-8")
        with pytest.raises(ConfigLoadError) as exc_info:
            load_config(cwd=tmp_path)
        assert exc_info.value.stage == "parse"

    # --- test_validate_stage_bad_values ---
    # Config file has n_ctx=100 (below minimum)
    # Assert ConfigLoadError with stage="validate"
    def test_validate_stage_bad_values(self, tmp_path):
        memory_dir = tmp_path / ".memory"
        memory_dir.mkdir()
        config = {
            "db_path": "/tmp/memory.db",
            "embedding": {
                "model_path": "/tmp/models/default.gguf",
                "n_ctx": 100,
            },
        }
        (memory_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
        with pytest.raises(ConfigLoadError) as exc_info:
            load_config(cwd=tmp_path)
        assert exc_info.value.stage == "validate"

    # --- test_validate_error_includes_details ---
    # Config with multiple bad fields
    # Assert ConfigLoadError.details contains all error messages
    def test_validate_error_includes_details(self, tmp_path):
        memory_dir = tmp_path / ".memory"
        memory_dir.mkdir()
        config = {
            "db_path": "/tmp/memory.db",
            "embedding": {
                "model_path": "/tmp/models/default.gguf",
                "n_ctx": 100,
                "n_batch": 0,
            },
        }
        (memory_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
        with pytest.raises(ConfigLoadError) as exc_info:
            load_config(cwd=tmp_path)
        assert exc_info.value.stage == "validate"
        assert len(exc_info.value.details) > 0


# =============================================================================
# TestReadConfigFile
# =============================================================================

class TestReadConfigFile:
    """Unit tests for _read_config_file."""

    # --- test_reads_valid_json ---
    # Write valid JSON dict to file -> read -> assert returns dict
    def test_reads_valid_json(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('{"key": "value"}', encoding="utf-8")
        result = _read_config_file(config_file)
        assert result == {"key": "value"}

    # --- test_rejects_json_array ---
    # Write JSON array to file -> read -> assert error (top-level must be dict)
    def test_rejects_json_array(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('[1, 2, 3]', encoding="utf-8")
        with pytest.raises(ConfigLoadError) as exc_info:
            _read_config_file(config_file)
        assert exc_info.value.stage == "parse"

    # --- test_rejects_json_string ---
    # Write JSON string to file -> assert error
    def test_rejects_json_string(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('"just a string"', encoding="utf-8")
        with pytest.raises(ConfigLoadError) as exc_info:
            _read_config_file(config_file)
        assert exc_info.value.stage == "parse"

    # --- test_handles_utf8 ---
    # Write config with unicode values -> read -> assert values preserved
    def test_handles_utf8(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('{"key": "日本語"}', encoding="utf-8")
        result = _read_config_file(config_file)
        assert result["key"] == "日本語"


# =============================================================================
# TestApplyOverrides
# =============================================================================

class TestApplyOverrides:
    """Unit tests for _apply_overrides."""

    # --- test_db_override_sets_db_path ---
    # config = {"db_path": "/old"}, db_override="/new"
    # Call _apply_overrides -> assert config["db_path"] == "/new"
    def test_db_override_sets_db_path(self):
        config = {"db_path": "/old"}
        _apply_overrides(config, db_override="/new")
        assert config["db_path"] == "/new"

    # --- test_no_override_no_change ---
    # config = {"db_path": "/old"}, db_override=None
    # Call _apply_overrides -> assert config["db_path"] == "/old"
    def test_no_override_no_change(self):
        config = {"db_path": "/old"}
        _apply_overrides(config, db_override=None)
        assert config["db_path"] == "/old"

    # --- test_mutates_in_place ---
    # Assert _apply_overrides returns the same dict object (not a copy)
    def test_mutates_in_place(self):
        config = {"db_path": "/old"}
        result = _apply_overrides(config, db_override="/new")
        assert result is config
