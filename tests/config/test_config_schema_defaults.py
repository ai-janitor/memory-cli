# =============================================================================
# Test Module: test_config_schema_defaults.py
# Purpose: Verify config schema definition, default values, and validation
#   rules are correct and self-consistent.
# Rationale: The schema is the source of truth for what a valid config looks
#   like. These tests ensure defaults are valid, rules catch bad values, and
#   the merge function correctly overlays user config over defaults.
# Responsibility:
#   - Test CONFIG_DEFAULTS has all required keys
#   - Test default values match spec (n_ctx=2048, decay_rate=0.25, etc.)
#   - Test VALIDATION_RULES covers every config field
#   - Test validate_config catches each type of violation
#   - Test build_config_with_defaults merge behavior
#   - Test dict_to_config_schema conversion
# Organization:
#   1. Imports and fixtures
#   2. TestConfigDefaults — default values tests
#   3. TestValidationRules — validation rule tests
#   4. TestBuildConfigWithDefaults — merge logic tests
#   5. TestDictToConfigSchema — conversion tests
# =============================================================================

from __future__ import annotations

import copy
import pytest

from memory_cli.config.config_schema_and_defaults import (
    CONFIG_DEFAULTS,
    VALIDATION_RULES,
    ConfigSchema,
    EmbeddingConfig,
    SearchConfig,
    HaikuConfig,
    OutputConfig,
    build_config_with_defaults,
    validate_config,
    dict_to_config_schema,
)


# =============================================================================
# Fixtures
# =============================================================================

# --- fixture: valid_full_config ---
# Returns a complete config dict with all fields set to valid values.
# Used as a baseline for mutation-based validation tests.

@pytest.fixture
def valid_full_config():
    return {
        "db_path": "/home/user/.memory/memory.db",
        "embedding": {
            "model_path": "/home/user/.memory/models/default.gguf",
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


# --- fixture: minimal_user_config ---
# Returns a config dict with only db_path and embedding.model_path set.
# Everything else should come from defaults after merge.

@pytest.fixture
def minimal_user_config():
    return {
        "db_path": "/home/user/.memory/memory.db",
        "embedding": {
            "model_path": "/home/user/.memory/models/default.gguf",
        },
    }


# =============================================================================
# TestConfigDefaults
# =============================================================================

class TestConfigDefaults:
    """Verify CONFIG_DEFAULTS has correct structure and values."""

    # --- test_defaults_has_all_top_level_keys ---
    # Assert CONFIG_DEFAULTS contains: db_path, embedding, search, haiku, output
    def test_defaults_has_all_top_level_keys(self):
        assert "db_path" in CONFIG_DEFAULTS
        assert "embedding" in CONFIG_DEFAULTS
        assert "search" in CONFIG_DEFAULTS
        assert "haiku" in CONFIG_DEFAULTS
        assert "output" in CONFIG_DEFAULTS

    # --- test_embedding_defaults ---
    # Assert embedding.n_ctx == 2048
    # Assert embedding.n_batch == 512
    # Assert embedding.dimensions == 768
    # Assert embedding.model_path is None or empty (set by init)
    def test_embedding_defaults(self):
        emb = CONFIG_DEFAULTS["embedding"]
        assert emb["n_ctx"] == 2048
        assert emb["n_batch"] == 512
        assert emb["dimensions"] == 768
        assert emb["model_path"] is None

    # --- test_search_defaults ---
    # Assert search.default_limit == 10
    # Assert search.fan_out_depth == 1
    # Assert search.decay_rate == 0.25
    # Assert search.temporal_decay_enabled == True
    def test_search_defaults(self):
        srch = CONFIG_DEFAULTS["search"]
        assert srch["default_limit"] == 10
        assert srch["fan_out_depth"] == 1
        assert srch["decay_rate"] == 0.25
        assert srch["temporal_decay_enabled"] is True

    # --- test_haiku_defaults ---
    # Assert haiku.api_key_env_var == "ANTHROPIC_API_KEY"
    def test_haiku_defaults(self):
        assert CONFIG_DEFAULTS["haiku"]["api_key_env_var"] == "ANTHROPIC_API_KEY"

    # --- test_output_defaults ---
    # Assert output.default_format == "json"
    def test_output_defaults(self):
        assert CONFIG_DEFAULTS["output"]["default_format"] == "json"


# =============================================================================
# TestValidationRules
# =============================================================================

class TestValidationRules:
    """Verify validate_config catches all invalid field values."""

    # --- test_valid_config_returns_no_errors ---
    # Pass a fully valid config -> expect empty error list
    def test_valid_config_returns_no_errors(self, valid_full_config):
        errors = validate_config(valid_full_config)
        assert errors == []

    # --- test_db_path_must_be_absolute ---
    # Set db_path to "relative/path.db" -> expect error about absolute path
    def test_db_path_must_be_absolute(self, valid_full_config):
        valid_full_config["db_path"] = "relative/path.db"
        errors = validate_config(valid_full_config)
        assert any("db_path" in e and "absolute" in e for e in errors)

    # --- test_model_path_must_be_absolute ---
    # Set embedding.model_path to "models/x.gguf" -> expect error
    def test_model_path_must_be_absolute(self, valid_full_config):
        valid_full_config["embedding"]["model_path"] = "models/x.gguf"
        errors = validate_config(valid_full_config)
        assert any("embedding.model_path" in e and "absolute" in e for e in errors)

    # --- test_n_ctx_minimum_512 ---
    # Set embedding.n_ctx to 511 -> expect error (EC-6)
    # Set embedding.n_ctx to 512 -> expect no error
    def test_n_ctx_minimum_512(self, valid_full_config):
        cfg = copy.deepcopy(valid_full_config)
        cfg["embedding"]["n_ctx"] = 511
        errors = validate_config(cfg)
        assert any("embedding.n_ctx" in e for e in errors)

        cfg2 = copy.deepcopy(valid_full_config)
        cfg2["embedding"]["n_ctx"] = 512
        errors2 = validate_config(cfg2)
        assert not any("embedding.n_ctx" in e for e in errors2)

    # --- test_n_batch_minimum_1 ---
    # Set embedding.n_batch to 0 -> expect error
    # Set embedding.n_batch to 1 -> expect no error
    def test_n_batch_minimum_1(self, valid_full_config):
        cfg = copy.deepcopy(valid_full_config)
        cfg["embedding"]["n_batch"] = 0
        errors = validate_config(cfg)
        assert any("embedding.n_batch" in e for e in errors)

        cfg2 = copy.deepcopy(valid_full_config)
        cfg2["embedding"]["n_batch"] = 1
        errors2 = validate_config(cfg2)
        assert not any("embedding.n_batch" in e for e in errors2)

    # --- test_dimensions_must_be_positive ---
    # Set embedding.dimensions to 0 -> expect error
    # Set embedding.dimensions to -1 -> expect error
    def test_dimensions_must_be_positive(self, valid_full_config):
        cfg = copy.deepcopy(valid_full_config)
        cfg["embedding"]["dimensions"] = 0
        errors = validate_config(cfg)
        assert any("embedding.dimensions" in e for e in errors)

        cfg2 = copy.deepcopy(valid_full_config)
        cfg2["embedding"]["dimensions"] = -1
        errors2 = validate_config(cfg2)
        assert any("embedding.dimensions" in e for e in errors2)

    # --- test_search_default_limit_minimum_1 ---
    # Set search.default_limit to 0 -> expect error
    def test_search_default_limit_minimum_1(self, valid_full_config):
        valid_full_config["search"]["default_limit"] = 0
        errors = validate_config(valid_full_config)
        assert any("search.default_limit" in e for e in errors)

    # --- test_fan_out_depth_range_0_to_10 ---
    # Set search.fan_out_depth to -1 -> expect error
    # Set search.fan_out_depth to 11 -> expect error
    # Set search.fan_out_depth to 0 -> expect no error
    # Set search.fan_out_depth to 10 -> expect no error
    def test_fan_out_depth_range_0_to_10(self, valid_full_config):
        cfg = copy.deepcopy(valid_full_config)
        cfg["search"]["fan_out_depth"] = -1
        assert any("search.fan_out_depth" in e for e in validate_config(cfg))

        cfg2 = copy.deepcopy(valid_full_config)
        cfg2["search"]["fan_out_depth"] = 11
        assert any("search.fan_out_depth" in e for e in validate_config(cfg2))

        cfg3 = copy.deepcopy(valid_full_config)
        cfg3["search"]["fan_out_depth"] = 0
        assert not any("search.fan_out_depth" in e for e in validate_config(cfg3))

        cfg4 = copy.deepcopy(valid_full_config)
        cfg4["search"]["fan_out_depth"] = 10
        assert not any("search.fan_out_depth" in e for e in validate_config(cfg4))

    # --- test_decay_rate_exclusive_bounds ---
    # Set search.decay_rate to 0.0 -> expect error (EC-5, exclusive lower bound)
    # Set search.decay_rate to 1.0 -> expect error (EC-5, exclusive upper bound)
    # Set search.decay_rate to 0.001 -> expect no error
    # Set search.decay_rate to 0.999 -> expect no error
    def test_decay_rate_exclusive_bounds(self, valid_full_config):
        cfg = copy.deepcopy(valid_full_config)
        cfg["search"]["decay_rate"] = 0.0
        assert any("search.decay_rate" in e for e in validate_config(cfg))

        cfg2 = copy.deepcopy(valid_full_config)
        cfg2["search"]["decay_rate"] = 1.0
        assert any("search.decay_rate" in e for e in validate_config(cfg2))

        cfg3 = copy.deepcopy(valid_full_config)
        cfg3["search"]["decay_rate"] = 0.001
        assert not any("search.decay_rate" in e for e in validate_config(cfg3))

        cfg4 = copy.deepcopy(valid_full_config)
        cfg4["search"]["decay_rate"] = 0.999
        assert not any("search.decay_rate" in e for e in validate_config(cfg4))

    # --- test_temporal_decay_must_be_bool ---
    # Set search.temporal_decay_enabled to "true" (string) -> expect error
    def test_temporal_decay_must_be_bool(self, valid_full_config):
        valid_full_config["search"]["temporal_decay_enabled"] = "true"
        errors = validate_config(valid_full_config)
        assert any("search.temporal_decay_enabled" in e for e in errors)

    # --- test_output_format_enum ---
    # Set output.default_format to "json" -> no error
    # Set output.default_format to "text" -> no error
    # Set output.default_format to "xml" -> expect error
    # Set output.default_format to "JSON" -> expect error (case sensitive)
    def test_output_format_enum(self, valid_full_config):
        cfg = copy.deepcopy(valid_full_config)
        cfg["output"]["default_format"] = "json"
        assert not any("output.default_format" in e for e in validate_config(cfg))

        cfg2 = copy.deepcopy(valid_full_config)
        cfg2["output"]["default_format"] = "text"
        assert not any("output.default_format" in e for e in validate_config(cfg2))

        cfg3 = copy.deepcopy(valid_full_config)
        cfg3["output"]["default_format"] = "xml"
        assert any("output.default_format" in e for e in validate_config(cfg3))

        cfg4 = copy.deepcopy(valid_full_config)
        cfg4["output"]["default_format"] = "JSON"
        assert any("output.default_format" in e for e in validate_config(cfg4))

    # --- test_unknown_keys_ignored ---
    # Add config["future_feature"] = True -> expect no error (EC-12)
    # Add config["embedding"]["new_param"] = 42 -> expect no error
    def test_unknown_keys_ignored(self, valid_full_config):
        valid_full_config["future_feature"] = True
        valid_full_config["embedding"]["new_param"] = 42
        errors = validate_config(valid_full_config)
        assert errors == []

    # --- test_multiple_errors_reported ---
    # Set several invalid fields -> expect all errors in list, not just first
    def test_multiple_errors_reported(self, valid_full_config):
        valid_full_config["embedding"]["n_ctx"] = 100
        valid_full_config["embedding"]["n_batch"] = 0
        valid_full_config["output"]["default_format"] = "xml"
        errors = validate_config(valid_full_config)
        assert len(errors) >= 3


# =============================================================================
# TestBuildConfigWithDefaults
# =============================================================================

class TestBuildConfigWithDefaults:
    """Verify deep merge of user config over defaults."""

    # --- test_empty_user_config_returns_all_defaults ---
    # Pass {} -> result should equal CONFIG_DEFAULTS
    def test_empty_user_config_returns_all_defaults(self):
        result = build_config_with_defaults({})
        assert result == CONFIG_DEFAULTS

    # --- test_user_override_replaces_default ---
    # Pass {"search": {"default_limit": 20}} -> result has limit=20, other defaults intact
    def test_user_override_replaces_default(self):
        result = build_config_with_defaults({"search": {"default_limit": 20}})
        assert result["search"]["default_limit"] == 20
        assert result["search"]["fan_out_depth"] == CONFIG_DEFAULTS["search"]["fan_out_depth"]

    # --- test_partial_section_preserves_other_keys ---
    # Pass {"embedding": {"n_ctx": 4096}} -> n_batch, dimensions still at defaults
    def test_partial_section_preserves_other_keys(self):
        result = build_config_with_defaults({"embedding": {"n_ctx": 4096}})
        assert result["embedding"]["n_ctx"] == 4096
        assert result["embedding"]["n_batch"] == CONFIG_DEFAULTS["embedding"]["n_batch"]
        assert result["embedding"]["dimensions"] == CONFIG_DEFAULTS["embedding"]["dimensions"]

    # --- test_unknown_keys_preserved ---
    # Pass {"my_plugin": {"setting": true}} -> key exists in result
    def test_unknown_keys_preserved(self):
        result = build_config_with_defaults({"my_plugin": {"setting": True}})
        assert "my_plugin" in result
        assert result["my_plugin"]["setting"] is True

    # --- test_deep_merge_not_shallow ---
    # Pass {"search": {"decay_rate": 0.5}} -> search.default_limit still at default
    # (Verifies nested merge, not top-level key replacement)
    def test_deep_merge_not_shallow(self):
        result = build_config_with_defaults({"search": {"decay_rate": 0.5}})
        assert result["search"]["decay_rate"] == 0.5
        assert result["search"]["default_limit"] == CONFIG_DEFAULTS["search"]["default_limit"]
        assert result["search"]["fan_out_depth"] == CONFIG_DEFAULTS["search"]["fan_out_depth"]


# =============================================================================
# TestDictToConfigSchema
# =============================================================================

class TestDictToConfigSchema:
    """Verify conversion from validated dict to ConfigSchema dataclass."""

    # --- test_conversion_produces_correct_types ---
    # Convert a valid dict -> check all fields have correct Python types
    def test_conversion_produces_correct_types(self, valid_full_config):
        schema = dict_to_config_schema(valid_full_config)
        assert isinstance(schema.db_path, str)
        assert isinstance(schema.embedding.n_ctx, int)
        assert isinstance(schema.embedding.n_batch, int)
        assert isinstance(schema.embedding.dimensions, int)
        assert isinstance(schema.search.default_limit, int)
        assert isinstance(schema.search.fan_out_depth, int)
        assert isinstance(schema.search.decay_rate, float)
        assert isinstance(schema.search.temporal_decay_enabled, bool)
        assert isinstance(schema.haiku.api_key_env_var, str)
        assert isinstance(schema.output.default_format, str)

    # --- test_nested_sections_are_dataclasses ---
    # Check that embedding, search, haiku, output are their respective dataclass types
    def test_nested_sections_are_dataclasses(self, valid_full_config):
        schema = dict_to_config_schema(valid_full_config)
        assert isinstance(schema, ConfigSchema)
        assert isinstance(schema.embedding, EmbeddingConfig)
        assert isinstance(schema.search, SearchConfig)
        assert isinstance(schema.haiku, HaikuConfig)
        assert isinstance(schema.output, OutputConfig)

    # --- test_roundtrip_values ---
    # Set specific values in dict -> convert -> verify values match on dataclass
    def test_roundtrip_values(self, valid_full_config):
        valid_full_config["embedding"]["n_ctx"] = 4096
        valid_full_config["search"]["decay_rate"] = 0.5
        valid_full_config["output"]["default_format"] = "text"
        schema = dict_to_config_schema(valid_full_config)
        assert schema.embedding.n_ctx == 4096
        assert schema.search.decay_rate == 0.5
        assert schema.output.default_format == "text"
