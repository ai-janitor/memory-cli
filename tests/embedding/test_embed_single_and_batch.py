# =============================================================================
# test_embed_single_and_batch.py — Tests for single/batch embed functions
# =============================================================================
# Purpose:     Verify embed_single() and embed_batch() correctly handle model
#              interaction, prefix prepending, dimension validation, empty inputs,
#              and model-missing fallbacks.
# Rationale:   These are the core embedding entry points used by all callers.
#              Mocking the Llama model allows testing the orchestration logic
#              without requiring an actual GGUF model file.
# Responsibility:
#   - Test embed_single returns 768-dim vector
#   - Test embed_single prepends correct prefix
#   - Test embed_batch returns list of 768-dim vectors
#   - Test embed_batch with empty list returns empty list
#   - Test model-missing fallback returns None with warning
#   - Test dimension mismatch raises ValueError
#   - Test normalization (vectors should be L2-normalized by model)
# Organization:
#   Uses pytest fixtures to mock model_loader and config.
#   Mock Llama.embed() to return controlled vectors.
# =============================================================================

from __future__ import annotations

import pytest


# --- Fixtures ---
# @pytest.fixture
# def mock_model(monkeypatch):
#     """Mock get_model() to return a fake Llama with controllable embed()."""
#     Create a mock that returns 768-dim zero vectors (or known test vectors)
#     Monkeypatch get_model in embed_single_and_batch module
#     Return the mock for assertion

# @pytest.fixture
# def mock_model_missing(monkeypatch):
#     """Mock get_model() to raise FileNotFoundError."""
#     Monkeypatch get_model to raise FileNotFoundError("Model not found")


class TestEmbedSingle:
    """embed_single() embeds one text and returns a validated vector."""

    # --- Test: returns 768-dim vector for valid input ---
    # Use mock_model that returns [0.0] * 768
    # result = embed_single("test text", "index")
    # assert result is not None
    # assert len(result) == 768

    # --- Test: prepends index prefix before calling model ---
    # Use mock_model, capture the text passed to model.embed()
    # embed_single("hello", "index")
    # Assert model.embed was called with "search_document: hello"

    # --- Test: prepends query prefix for query operation ---
    # embed_single("hello", "query")
    # Assert model.embed was called with "search_query: hello"

    # --- Test: model missing returns None ---
    # Use mock_model_missing
    # result = embed_single("hello", "index")
    # assert result is None
    pass


class TestEmbedBatch:
    """embed_batch() embeds multiple texts and returns validated vectors."""

    # --- Test: returns list of 768-dim vectors ---
    # Use mock_model that returns [[0.0]*768, [0.0]*768]
    # result = embed_batch(["text1", "text2"], "index")
    # assert len(result) == 2
    # assert all(len(v) == 768 for v in result)

    # --- Test: empty input returns empty list (not None) ---
    # result = embed_batch([], "index")
    # assert result == []

    # --- Test: all texts get same prefix ---
    # Use mock_model, embed_batch(["a", "b"], "index")
    # Assert model.embed called with ["search_document: a", "search_document: b"]

    # --- Test: model missing returns None ---
    # Use mock_model_missing
    # result = embed_batch(["hello"], "query")
    # assert result is None
    pass


class TestDimensionValidation:
    """Vectors with wrong dimensions are rejected."""

    # --- Test: model returning 512-dim vector raises ValueError ---
    # Mock model.embed to return [0.0] * 512
    # with pytest.raises(ValueError):
    #   embed_single("text", "index")

    # --- Test: batch with one wrong-dim vector raises ValueError ---
    # Mock model.embed to return [[0.0]*768, [0.0]*512]
    # with pytest.raises(ValueError):
    #   embed_batch(["a", "b"], "index")
    pass


class TestModelMissingWarnings:
    """Appropriate warnings emitted when model is missing."""

    # --- Test: index operation warns about storing without vector ---
    # Use mock_model_missing
    # with warnings.catch_warnings(record=True) as w:
    #   embed_single("text", "index")
    #   Assert warning about "stored without vector"

    # --- Test: query operation warns about BM25 fallback ---
    # Use mock_model_missing
    # with warnings.catch_warnings(record=True) as w:
    #   embed_single("text", "query")
    #   Assert warning about "BM25-only"
    pass
