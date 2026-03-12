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

import pytest


class TestLazyLoading:
    """Model should not load at import time — only on first get_model() call."""

    # --- Test: importing the module does not trigger model load ---
    # Import model_loader_lazy_singleton
    # Assert that _model_instance is None (no load happened)

    # --- Test: first call to get_model() triggers load ---
    # Mock Llama constructor to track calls
    # Mock config to return valid path to a temp file
    # Call get_model()
    # Assert Llama constructor was called exactly once
    # Assert return value is the mock Llama instance
    pass


class TestSingletonBehavior:
    """Multiple get_model() calls must return the exact same instance."""

    # --- Test: second call returns same object without reloading ---
    # Mock Llama constructor
    # Mock config with valid path
    # model1 = get_model()
    # model2 = get_model()
    # Assert model1 is model2 (same object identity)
    # Assert Llama constructor called exactly once (not twice)
    pass


class TestMissingModelFile:
    """FileNotFoundError when model path does not exist."""

    # --- Test: nonexistent path raises FileNotFoundError ---
    # Mock config to return "/nonexistent/model.gguf"
    # Call get_model()
    # Assert raises FileNotFoundError
    # Assert error message contains the path

    # --- Test: path exists but is a directory raises FileNotFoundError ---
    # Mock config to return path to a directory (e.g., tmp_path)
    # Call get_model()
    # Assert raises FileNotFoundError
    pass


class TestConfigParams:
    """Llama constructor receives correct params from config."""

    # --- Test: default config values (n_ctx=2048, n_batch=512) ---
    # Mock config with defaults, mock Llama constructor
    # Call get_model()
    # Assert Llama called with: embedding=True, n_ctx=2048, n_batch=512, verbose=False

    # --- Test: custom config values are passed through ---
    # Mock config with n_ctx=4096, n_batch=1024
    # Call get_model()
    # Assert Llama called with the custom values

    # --- Test: model_path from config is passed as string ---
    # Mock config with Path object
    # Assert Llama receives str(path) not Path object
    pass


class TestResetModel:
    """reset_model() clears singleton so next call reloads."""

    # --- Test: reset then get_model triggers fresh load ---
    # Mock Llama constructor, mock config
    # get_model()  # first load
    # reset_model()
    # get_model()  # should load again
    # Assert Llama constructor called twice (once per load)
    pass
