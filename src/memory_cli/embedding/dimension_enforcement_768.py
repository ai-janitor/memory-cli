# =============================================================================
# dimension_enforcement_768.py — Validate vector dimensions before write
# =============================================================================
# Purpose:     Enforce that all embedding vectors are exactly 768 dimensions
#              before they are stored or used. This is the single point of
#              dimension validation for the entire embedding subsystem.
# Rationale:   nomic-embed-text-v1.5 produces 768-dim vectors. The vec0 virtual
#              table is configured for 768 dims. A dimension mismatch would
#              corrupt the index or produce garbage similarity scores. Catching
#              mismatches early (before write) gives clear error messages instead
#              of cryptic sqlite-vec failures.
# Responsibility:
#   - Define EXPECTED_DIMENSIONS = 768 as a constant
#   - validate_dimensions(vector) — raise ValueError if len(vector) != 768
#   - validate_dimensions_batch(vectors) — validate a list of vectors
#   - Used by embed_single_and_batch and vector_storage_vec0_write
# Organization:
#   Constant: EXPECTED_DIMENSIONS = 768
#   validate_dimensions(vector) -> None (raises on mismatch)
#   validate_dimensions_batch(vectors) -> None (raises on any mismatch)
# =============================================================================

from __future__ import annotations

# --- Dimension constant ---
# nomic-embed-text-v1.5 output dimensionality
EXPECTED_DIMENSIONS: int = 768


def validate_dimensions(vector: list[float]) -> None:
    """Validate that a vector has exactly 768 dimensions.

    Args:
        vector: A list of floats representing an embedding vector.

    Raises:
        ValueError: If len(vector) != 768, with a message including the
                    actual dimension count for debugging.
    """
    # --- Check dimension count ---
    # actual = len(vector)
    # If actual != EXPECTED_DIMENSIONS:
    #   raise ValueError(
    #     f"Expected {EXPECTED_DIMENSIONS}-dim vector, got {actual}-dim. "
    #     f"This indicates a model mismatch or embedding corruption."
    #   )
    actual = len(vector)
    if actual != EXPECTED_DIMENSIONS:
        raise ValueError(
            f"Expected {EXPECTED_DIMENSIONS}-dim vector, got {actual}-dim. "
            f"This indicates a model mismatch or embedding corruption."
        )


def validate_dimensions_batch(vectors: list[list[float]]) -> None:
    """Validate that all vectors in a batch have exactly 768 dimensions.

    Checks every vector and reports the first mismatch found.

    Args:
        vectors: A list of embedding vectors to validate.

    Raises:
        ValueError: If any vector does not have exactly 768 dimensions,
                    with message including the index and actual dimension count.
    """
    # --- Check each vector ---
    # for i, vector in enumerate(vectors):
    #   actual = len(vector)
    #   If actual != EXPECTED_DIMENSIONS:
    #     raise ValueError(
    #       f"Vector at index {i}: expected {EXPECTED_DIMENSIONS}-dim, got {actual}-dim. "
    #       f"This indicates a model mismatch or embedding corruption."
    #     )
    for i, vector in enumerate(vectors):
        actual = len(vector)
        if actual != EXPECTED_DIMENSIONS:
            raise ValueError(
                f"Vector at index {i}: expected {EXPECTED_DIMENSIONS}-dim, got {actual}-dim. "
                f"This indicates a model mismatch or embedding corruption."
            )
