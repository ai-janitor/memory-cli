# =============================================================================
# task_prefix_search_document_query.py — Prefix constants and prepend logic
# =============================================================================
# Purpose:     Define the two nomic-embed task prefixes ("search_document: " for
#              indexing/storing, "search_query: " for searching/querying) and
#              provide a single function to prepend the correct prefix.
# Rationale:   nomic-embed-text-v1.5 uses task-specific prefixes to produce
#              asymmetric embeddings — documents and queries map to the same
#              space but are encoded differently for better retrieval. The engine
#              must prepend these transparently so callers only specify "index"
#              or "query" as an operation type.
# Responsibility:
#   - Define INDEX_PREFIX and QUERY_PREFIX as constants
#   - Provide prepend_prefix(text, operation) that returns prefixed text
#   - Validate operation type; raise ValueError on unknown operation
#   - Callers never see or manage prefix strings directly
# Organization:
#   Constants: INDEX_PREFIX, QUERY_PREFIX
#   Enum or literal type: OperationType ("index" | "query")
#   prepend_prefix(text, operation) -> str — the single public function
# =============================================================================

from __future__ import annotations

from typing import Literal

# --- Task prefix constants ---
# These match the nomic-embed-text-v1.5 expected prefix format exactly.
# Trailing space is intentional — it separates prefix from content.
INDEX_PREFIX: str = "search_document: "
QUERY_PREFIX: str = "search_query: "

# --- Operation type alias ---
OperationType = Literal["index", "query"]


def prepend_prefix(text: str, operation: OperationType) -> str:
    """Prepend the appropriate nomic task prefix to the input text.

    Args:
        text: The raw text to be embedded (already assembled from content + tags).
        operation: Either "index" (for storing/indexing neurons) or "query"
                   (for search queries).

    Returns:
        The text with the appropriate task prefix prepended.

    Raises:
        ValueError: If operation is not "index" or "query".
    """
    # --- Step 1: Validate operation type ---
    # If operation not in ("index", "query"):
    #   raise ValueError(f"Unknown operation type: {operation}. Must be 'index' or 'query'.")

    # --- Step 2: Select prefix ---
    # If operation == "index": prefix = INDEX_PREFIX
    # Else: prefix = QUERY_PREFIX

    # --- Step 3: Prepend and return ---
    # return prefix + text
    pass
