# =============================================================================
# test_model_loader.py — Tests for lazy singleton Llama loader
# =============================================================================
# Purpose:     Verify that the model loader correctly implements lazy singleton
#              behavior, respects config parameters, and handles missing files.
# Rationale:   The singleton pattern and lazy loading are critical for CLI
#              performance. Misconfigurations (wrong path, bad params) must
#              produce clear errors, not silent failures.
# Responsibility:
#   - Test lazy loading: model not loaded at import time
#   - Test singleton: multiple get_model() calls return same instance
#   - Test missing file: FileNotFoundError with descriptive message
#   - Test config params: n_ctx, n_batch, embedding=True, verbose=False
#   - Test reset_model(): clears singleton, next call reloads
# Organization:
#   Uses pytest fixtures and monkeypatching to mock Llama constructor
#   and config values. No actual model file needed for unit tests.
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import memory_cli.embedding.model_loader_lazy_singleton as loader_module
from memory_cli.embedding.model_loader_lazy_singleton import get_model, reset_model


# --- Config stub helpers ---
@dataclass
class _EmbeddingConfig:
    model_path: str
    n_ctx: int = 2048
    n_batch: int = 512


@dataclass
class _Config:
    embedding: _EmbeddingConfig


def _make_config(model_path: str, n_ctx: int = 2048, n_batch: int = 512) -> _Config:
    return _Config(embedding=_EmbeddingConfig(model_path=model_path, n_ctx=n_ctx, n_batch=n_batch))


@pytest.fixture(autouse=True)
def reset_singleton():
    """Ensure singleton is cleared before and after each test."""
    reset_model()
    yield
    reset_model()


class TestLazyLoading:
    """Model should not load at import time — only on first get_model() call."""

    # --- Test: importing the module does not trigger model load ---
    # Import model_loader_lazy_singleton
    # Assert that _model_instance is None (no load happened)
    def test_import_does_not_load_model(self):
        assert loader_module._model_instance is None
        assert loader_module._model_loaded is False

    # --- Test: first call to get_model() triggers load ---
    # Mock Llama constructor to track calls
    # Mock config to return valid path to a temp file
    # Call get_model()
    # Assert Llama constructor was called exactly once
    # Assert return value is the mock Llama instance
    def test_first_call_triggers_load(self, tmp_path):
        model_file = tmp_path / "model.gguf"
        model_file.write_bytes(b"fake model")
        config = _make_config(str(model_file))

        mock_llama_instance = MagicMock()
        with patch.dict("sys.modules", {"llama_cpp": MagicMock(Llama=MagicMock(return_value=mock_llama_instance))}):
            result = get_model(config)

        assert result is mock_llama_instance


class TestSingletonBehavior:
    """Multiple get_model() calls must return the exact same instance."""

    # --- Test: second call returns same object without reloading ---
    # Mock Llama constructor
    # Mock config with valid path
    # model1 = get_model()
    # model2 = get_model()
    # Assert model1 is model2 (same object identity)
    # Assert Llama constructor called exactly once (not twice)
    def test_second_call_returns_same_instance(self, tmp_path):
        model_file = tmp_path / "model.gguf"
        model_file.write_bytes(b"fake model")
        config = _make_config(str(model_file))

        mock_llama_instance = MagicMock()
        mock_llama_class = MagicMock(return_value=mock_llama_instance)

        with patch.dict("sys.modules", {"llama_cpp": MagicMock(Llama=mock_llama_class)}):
            model1 = get_model(config)
            model2 = get_model(config)

        assert model1 is model2
        assert mock_llama_class.call_count == 1


class TestMissingModelFile:
    """FileNotFoundError when model path does not exist."""

    # --- Test: nonexistent path raises FileNotFoundError ---
    # Mock config to return "/nonexistent/model.gguf"
    # Call get_model()
    # Assert raises FileNotFoundError
    # Assert error message contains the path
    def test_nonexistent_path_raises(self):
        config = _make_config("/nonexistent/model.gguf")
        with pytest.raises(FileNotFoundError, match="/nonexistent/model.gguf"):
            get_model(config)

    # --- Test: path exists but is a directory raises FileNotFoundError ---
    # Mock config to return path to a directory (e.g., tmp_path)
    # Call get_model()
    # Assert raises FileNotFoundError
    def test_directory_path_raises(self, tmp_path):
        config = _make_config(str(tmp_path))
        with pytest.raises(FileNotFoundError):
            get_model(config)


class TestConfigParams:
    """Llama constructor receives correct params from config."""

    # --- Test: default config values (n_ctx=2048, n_batch=512) ---
    # Mock config with defaults, mock Llama constructor
    # Call get_model()
    # Assert Llama called with: embedding=True, n_ctx=2048, n_batch=512, verbose=False
    def test_default_config_params_passed(self, tmp_path):
        model_file = tmp_path / "model.gguf"
        model_file.write_bytes(b"fake model")
        config = _make_config(str(model_file), n_ctx=2048, n_batch=512)

        mock_llama_class = MagicMock(return_value=MagicMock())
        with patch.dict("sys.modules", {"llama_cpp": MagicMock(Llama=mock_llama_class)}):
            get_model(config)

        mock_llama_class.assert_called_once_with(
            model_path=str(model_file),
            embedding=True,
            n_ctx=2048,
            n_batch=512,
            verbose=False,
        )

    # --- Test: custom config values are passed through ---
    # Mock config with n_ctx=4096, n_batch=1024
    # Call get_model()
    # Assert Llama called with the custom values
    def test_custom_config_params_passed(self, tmp_path):
        model_file = tmp_path / "model.gguf"
        model_file.write_bytes(b"fake model")
        config = _make_config(str(model_file), n_ctx=4096, n_batch=1024)

        mock_llama_class = MagicMock(return_value=MagicMock())
        with patch.dict("sys.modules", {"llama_cpp": MagicMock(Llama=mock_llama_class)}):
            get_model(config)

        mock_llama_class.assert_called_once_with(
            model_path=str(model_file),
            embedding=True,
            n_ctx=4096,
            n_batch=1024,
            verbose=False,
        )

    # --- Test: model_path from config is passed as string ---
    # Mock config with Path object
    # Assert Llama receives str(path) not Path object
    def test_model_path_passed_as_string(self, tmp_path):
        model_file = tmp_path / "model.gguf"
        model_file.write_bytes(b"fake model")
        config = _make_config(str(model_file))

        mock_llama_class = MagicMock(return_value=MagicMock())
        with patch.dict("sys.modules", {"llama_cpp": MagicMock(Llama=mock_llama_class)}):
            get_model(config)

        call_kwargs = mock_llama_class.call_args
        passed_model_path = call_kwargs.kwargs.get("model_path") or call_kwargs.args[0]
        assert isinstance(passed_model_path, str)


class TestResetModel:
    """reset_model() clears singleton so next call reloads."""

    # --- Test: reset then get_model triggers fresh load ---
    # Mock Llama constructor, mock config
    # get_model()  # first load
    # reset_model()
    # get_model()  # should load again
    # Assert Llama constructor called twice (once per load)
    def test_reset_triggers_fresh_load(self, tmp_path):
        model_file = tmp_path / "model.gguf"
        model_file.write_bytes(b"fake model")
        config = _make_config(str(model_file))

        mock_llama_class = MagicMock(return_value=MagicMock())
        with patch.dict("sys.modules", {"llama_cpp": MagicMock(Llama=mock_llama_class)}):
            get_model(config)
            reset_model()
            get_model(config)

        assert mock_llama_class.call_count == 2
