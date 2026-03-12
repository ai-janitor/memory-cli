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

from unittest.mock import MagicMock, call

import pytest

from memory_cli.embedding.embed_single_and_batch import embed_batch, embed_single


# --- Fixtures ---
@pytest.fixture
def mock_model_single():
    """Mock model whose embed() returns a 768-dim vector for single input."""
    model = MagicMock()
    model.embed.return_value = [0.0] * 768
    return model


@pytest.fixture
def mock_model_batch():
    """Mock model whose embed() returns a list of 768-dim vectors for batch input."""

    def _embed_side_effect(texts, normalize=True):
        if isinstance(texts, list):
            return [[0.0] * 768 for _ in texts]
        return [0.0] * 768

    model = MagicMock()
    model.embed.side_effect = _embed_side_effect
    return model


@pytest.fixture
def mock_model_wrong_dim():
    """Mock model whose embed() returns a 512-dim vector (wrong)."""
    model = MagicMock()
    model.embed.return_value = [0.0] * 512
    return model


class TestEmbedSingle:
    """embed_single() embeds one text and returns a validated vector."""

    # --- Test: returns 768-dim vector for valid input ---
    # Use mock_model that returns [0.0] * 768
    # result = embed_single("test text", "index")
    # assert result is not None
    # assert len(result) == 768
    def test_returns_768_dim_vector(self, mock_model_single):
        result = embed_single(mock_model_single, "test text", "index")
        assert result is not None
        assert len(result) == 768

    # --- Test: prepends index prefix before calling model ---
    # Use mock_model, capture the text passed to model.embed()
    # embed_single("hello", "index")
    # Assert model.embed was called with "search_document: hello"
    def test_prepends_index_prefix(self, mock_model_single):
        embed_single(mock_model_single, "hello", "index")
        mock_model_single.embed.assert_called_once_with("search_document: hello", normalize=True)

    # --- Test: prepends query prefix for query operation ---
    # embed_single("hello", "query")
    # Assert model.embed was called with "search_query: hello"
    def test_prepends_query_prefix(self, mock_model_single):
        embed_single(mock_model_single, "hello", "query")
        mock_model_single.embed.assert_called_once_with("search_query: hello", normalize=True)

    def test_handles_nested_list_result(self):
        """Model returning [[...]] (nested) should be unwrapped."""
        model = MagicMock()
        model.embed.return_value = [[0.5] * 768]
        result = embed_single(model, "test", "index")
        assert len(result) == 768
        assert result[0] == 0.5


class TestEmbedBatch:
    """embed_batch() embeds multiple texts and returns validated vectors."""

    # --- Test: returns list of 768-dim vectors ---
    # Use mock_model that returns [[0.0]*768, [0.0]*768]
    # result = embed_batch(["text1", "text2"], "index")
    # assert len(result) == 2
    # assert all(len(v) == 768 for v in result)
    def test_returns_list_of_768_dim_vectors(self, mock_model_batch):
        result = embed_batch(mock_model_batch, ["text1", "text2"], "index")
        assert len(result) == 2
        assert all(len(v) == 768 for v in result)

    # --- Test: empty input returns empty list (not None) ---
    # result = embed_batch([], "index")
    # assert result == []
    def test_empty_input_returns_empty_list(self, mock_model_batch):
        result = embed_batch(mock_model_batch, [], "index")
        assert result == []
        # Model should not be called for empty input
        mock_model_batch.embed.assert_not_called()

    # --- Test: all texts get same prefix ---
    # Use mock_model, embed_batch(["a", "b"], "index")
    # Assert model.embed called with ["search_document: a", "search_document: b"]
    def test_all_texts_get_same_prefix(self, mock_model_batch):
        embed_batch(mock_model_batch, ["a", "b"], "index")
        mock_model_batch.embed.assert_called_once_with(
            ["search_document: a", "search_document: b"], normalize=True
        )

    def test_query_prefix_applied_to_batch(self, mock_model_batch):
        embed_batch(mock_model_batch, ["x", "y"], "query")
        mock_model_batch.embed.assert_called_once_with(
            ["search_query: x", "search_query: y"], normalize=True
        )


class TestDimensionValidation:
    """Vectors with wrong dimensions are rejected."""

    # --- Test: model returning 512-dim vector raises ValueError ---
    # Mock model.embed to return [0.0] * 512
    # with pytest.raises(ValueError):
    #   embed_single("text", "index")
    def test_single_wrong_dim_raises(self, mock_model_wrong_dim):
        with pytest.raises(ValueError):
            embed_single(mock_model_wrong_dim, "text", "index")

    # --- Test: batch with one wrong-dim vector raises ValueError ---
    # Mock model.embed to return [[0.0]*768, [0.0]*512]
    # with pytest.raises(ValueError):
    #   embed_batch(["a", "b"], "index")
    def test_batch_wrong_dim_raises(self):
        model = MagicMock()
        model.embed.return_value = [[0.0] * 768, [0.0] * 512]
        with pytest.raises(ValueError):
            embed_batch(model, ["a", "b"], "index")


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

    # NOTE: embed_single and embed_batch now take model as a parameter directly
    # rather than calling get_model() internally. The model-missing fallback
    # is handled by the caller (e.g., batch_reembed) not by these functions.
    # These tests are kept as placeholders per the scaffold structure.
    pass
