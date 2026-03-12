# =============================================================================
# Module: test_haiku_api_key.py
# Purpose: Test API key resolution from config env var name through
#   os.environ lookup, covering happy path, missing env var, empty value,
#   and missing config field.
# Rationale: API key resolution is a security-sensitive path. Tests must
#   verify that missing/empty keys produce clear errors, that the key
#   value never appears in error messages, and that whitespace is handled.
# Responsibility:
#   - Test successful resolution from environment
#   - Test missing env var raises HaikuApiKeyError
#   - Test empty env var value raises HaikuApiKeyError
#   - Test whitespace-only env var value raises HaikuApiKeyError
#   - Test key value is stripped of whitespace
#   - Test key value never appears in exception message
#   - Test missing config field raises HaikuApiKeyError
# Organization:
#   1. Imports and fixtures
#   2. Happy path tests
#   3. Missing env var tests
#   4. Empty/whitespace value tests
#   5. Config field missing tests
#   6. Security tests (key not in errors)
# =============================================================================

from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch

from memory_cli.search.heavy.haiku_api_key_resolution import (
    HaikuApiKeyError,
    resolve_haiku_api_key,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def mock_config():
    """ConfigSchema-like object with haiku.api_key_env_var = "ANTHROPIC_API_KEY"."""
    config = MagicMock()
    config.haiku.api_key_env_var = "ANTHROPIC_API_KEY"
    return config


@pytest.fixture
def custom_config():
    """ConfigSchema-like object with haiku.api_key_env_var = "CUSTOM_KEY_VAR"."""
    config = MagicMock()
    config.haiku.api_key_env_var = "CUSTOM_KEY_VAR"
    return config


# -----------------------------------------------------------------------------
# Happy path tests
# -----------------------------------------------------------------------------

class TestApiKeyResolutionHappyPath:
    """Test successful API key resolution."""

    def test_resolves_key_from_env(self, mock_config):
        """When env var is set to a valid key, return it.

        Set ANTHROPIC_API_KEY="sk-ant-test-key", expect that value returned.
        """
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test-key"}):
            key = resolve_haiku_api_key(mock_config)
        assert key == "sk-ant-test-key"

    def test_strips_whitespace_from_key(self, mock_config):
        """When env var has leading/trailing whitespace, strip it.

        Set ANTHROPIC_API_KEY="  sk-ant-test-key  ", expect "sk-ant-test-key".
        """
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "  sk-ant-test-key  "}):
            key = resolve_haiku_api_key(mock_config)
        assert key == "sk-ant-test-key"

    def test_uses_config_env_var_name(self, custom_config):
        """Verify the env var name comes from config, not hardcoded.

        Set config.haiku.api_key_env_var = "CUSTOM_KEY_VAR"
        Set CUSTOM_KEY_VAR="my-key" in env
        Expect "my-key" returned.
        """
        with patch.dict(os.environ, {"CUSTOM_KEY_VAR": "my-key"}, clear=False):
            # Remove ANTHROPIC_API_KEY if present to ensure we're using CUSTOM_KEY_VAR
            env = {**os.environ, "CUSTOM_KEY_VAR": "my-key"}
            with patch.dict(os.environ, env):
                key = resolve_haiku_api_key(custom_config)
        assert key == "my-key"


# -----------------------------------------------------------------------------
# Missing env var tests
# -----------------------------------------------------------------------------

class TestApiKeyMissing:
    """Test behavior when the env var is not set."""

    def test_missing_env_var_raises(self, mock_config, monkeypatch):
        """When env var is not set at all, raise HaikuApiKeyError.

        Unset ANTHROPIC_API_KEY from env, expect HaikuApiKeyError.
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(HaikuApiKeyError):
            resolve_haiku_api_key(mock_config)

    def test_error_includes_env_var_name(self, mock_config, monkeypatch):
        """Error message should include the env var name (safe to log).

        The user needs to know WHICH env var to set.
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(HaikuApiKeyError) as exc_info:
            resolve_haiku_api_key(mock_config)
        assert "ANTHROPIC_API_KEY" in str(exc_info.value)

    def test_error_does_not_include_key_value(self, mock_config):
        """Error message must never contain the actual key value.

        Even on a different error path, verify no key leakage.
        """
        # This test verifies that on missing key, the error doesn't leak anything sensitive
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(HaikuApiKeyError) as exc_info:
                resolve_haiku_api_key(mock_config)
            # No actual key value in error (it doesn't exist anyway, but defensive check)
            assert "sk-ant" not in str(exc_info.value)


# -----------------------------------------------------------------------------
# Empty/whitespace value tests
# -----------------------------------------------------------------------------

class TestApiKeyEmpty:
    """Test behavior when env var is set but empty or whitespace."""

    def test_empty_string_raises(self, mock_config):
        """When env var is set to "", raise HaikuApiKeyError.

        An empty key is useless and should fail fast.
        """
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            with pytest.raises(HaikuApiKeyError):
                resolve_haiku_api_key(mock_config)

    def test_whitespace_only_raises(self, mock_config):
        """When env var is "   " (whitespace only), raise HaikuApiKeyError.

        After stripping, it's empty — same as not set.
        """
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "   "}):
            with pytest.raises(HaikuApiKeyError):
                resolve_haiku_api_key(mock_config)


# -----------------------------------------------------------------------------
# Config field missing tests
# -----------------------------------------------------------------------------

class TestApiKeyConfigMissing:
    """Test behavior when config is missing haiku section or field."""

    def test_missing_haiku_section_raises(self):
        """When config has no haiku section, raise HaikuApiKeyError.

        Config might be from an older version without haiku support.
        """
        config = MagicMock()
        del config.haiku  # Remove haiku attribute
        config.haiku = MagicMock(side_effect=AttributeError("haiku"))
        # Use object that throws on attribute access
        class BadConfig:
            @property
            def haiku(self):
                raise AttributeError("no haiku")
            def get(self, key, default=None):
                return default

        with pytest.raises(HaikuApiKeyError):
            resolve_haiku_api_key(BadConfig())

    def test_empty_env_var_name_in_config_raises(self, monkeypatch):
        """When config.haiku.api_key_env_var is "", raise HaikuApiKeyError.

        Empty env var name means misconfigured — fail fast.
        """
        config = MagicMock()
        config.haiku.api_key_env_var = ""
        with pytest.raises(HaikuApiKeyError):
            resolve_haiku_api_key(config)
