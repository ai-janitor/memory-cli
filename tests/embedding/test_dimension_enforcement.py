# =============================================================================
# test_dimension_enforcement.py — Tests for vector dimension validation
# =============================================================================
# Purpose:     Verify that validate_dimensions() and validate_dimensions_batch()
#              correctly accept 768-dim vectors and reject all others, with
#              informative error messages.
# Rationale:   Dimension enforcement is the last line of defense against storing
#              corrupt vectors. Tests must cover the exact boundary (768) and
#              common failure modes (512, 1024, 0, 1).
# Responsibility:
#   - Test EXPECTED_DIMENSIONS constant is 768
#   - Test 768-dim vector passes validation (no error)
#   - Test wrong dimensions raise ValueError with dimension count in message
#   - Test batch validation: all correct passes, any wrong fails
#   - Test batch error message includes the index of the bad vector
# Organization:
#   Simple pytest functions — no fixtures, pure validation logic.
# =============================================================================

from __future__ import annotations

import pytest

from memory_cli.embedding.dimension_enforcement_768 import (
    EXPECTED_DIMENSIONS,
    validate_dimensions,
    validate_dimensions_batch,
)


class TestExpectedDimensions:
    """EXPECTED_DIMENSIONS constant must be 768."""

    # --- Test: constant value ---
    # from memory_cli.embedding.dimension_enforcement_768 import EXPECTED_DIMENSIONS
    # assert EXPECTED_DIMENSIONS == 768
    def test_constant_is_768(self):
        assert EXPECTED_DIMENSIONS == 768


class TestValidateDimensions:
    """validate_dimensions() accepts 768-dim, rejects everything else."""

    # --- Test: 768-dim vector passes (no exception) ---
    # validate_dimensions([0.0] * 768)  # should not raise
    def test_768_dim_passes(self):
        validate_dimensions([0.0] * 768)  # should not raise

    # --- Test: 512-dim vector raises ValueError ---
    # with pytest.raises(ValueError, match="512"):
    #   validate_dimensions([0.0] * 512)
    def test_512_dim_raises(self):
        with pytest.raises(ValueError, match="512"):
            validate_dimensions([0.0] * 512)

    # --- Test: 1024-dim vector raises ValueError ---
    # with pytest.raises(ValueError, match="1024"):
    #   validate_dimensions([0.0] * 1024)
    def test_1024_dim_raises(self):
        with pytest.raises(ValueError, match="1024"):
            validate_dimensions([0.0] * 1024)

    # --- Test: empty vector raises ValueError ---
    # with pytest.raises(ValueError, match="0"):
    #   validate_dimensions([])
    def test_empty_vector_raises(self):
        with pytest.raises(ValueError, match="0"):
            validate_dimensions([])

    # --- Test: single-element vector raises ValueError ---
    # with pytest.raises(ValueError, match="1"):
    #   validate_dimensions([1.0])
    def test_single_element_raises(self):
        with pytest.raises(ValueError, match="1"):
            validate_dimensions([1.0])

    # --- Test: error message includes expected dimension ---
    # with pytest.raises(ValueError, match="768"):
    #   validate_dimensions([0.0] * 100)
    def test_error_message_includes_expected(self):
        with pytest.raises(ValueError, match="768"):
            validate_dimensions([0.0] * 100)


class TestValidateDimensionsBatch:
    """validate_dimensions_batch() checks every vector in the list."""

    # --- Test: all 768-dim vectors pass ---
    # validate_dimensions_batch([[0.0]*768, [1.0]*768, [0.5]*768])
    # Should not raise
    def test_all_correct_passes(self):
        validate_dimensions_batch([[0.0] * 768, [1.0] * 768, [0.5] * 768])

    # --- Test: empty batch passes (no vectors to check) ---
    # validate_dimensions_batch([])  # should not raise
    def test_empty_batch_passes(self):
        validate_dimensions_batch([])

    # --- Test: first vector wrong raises immediately ---
    # with pytest.raises(ValueError, match="index 0"):
    #   validate_dimensions_batch([[0.0]*512, [0.0]*768])
    def test_first_vector_wrong_raises(self):
        with pytest.raises(ValueError, match="index 0"):
            validate_dimensions_batch([[0.0] * 512, [0.0] * 768])

    # --- Test: middle vector wrong is caught ---
    # with pytest.raises(ValueError, match="index 1"):
    #   validate_dimensions_batch([[0.0]*768, [0.0]*512, [0.0]*768])
    def test_middle_vector_wrong_raises(self):
        with pytest.raises(ValueError, match="index 1"):
            validate_dimensions_batch([[0.0] * 768, [0.0] * 512, [0.0] * 768])

    # --- Test: last vector wrong is caught ---
    # with pytest.raises(ValueError, match="index 2"):
    #   validate_dimensions_batch([[0.0]*768, [0.0]*768, [0.0]*512])
    def test_last_vector_wrong_raises(self):
        with pytest.raises(ValueError, match="index 2"):
            validate_dimensions_batch([[0.0] * 768, [0.0] * 768, [0.0] * 512])

    # --- Test: error message includes actual dimension count ---
    # with pytest.raises(ValueError, match="512"):
    #   validate_dimensions_batch([[0.0]*768, [0.0]*512])
    def test_error_message_includes_actual_dim(self):
        with pytest.raises(ValueError, match="512"):
            validate_dimensions_batch([[0.0] * 768, [0.0] * 512])
