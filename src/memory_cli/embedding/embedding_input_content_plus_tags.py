# =============================================================================
# embedding_input_content_plus_tags.py — Build embedding input from content + tags
# =============================================================================
# Purpose:     Assemble the raw embedding input string from a neuron's content
#              and its associated tags. Tags carry semantic meaning and are
#              included in the embedding to improve retrieval relevance.
# Rationale:   By appending space-separated lowercase tags to the content, the
#              embedding captures both the textual meaning and the categorical
#              context. This is done BEFORE task prefix prepending — the prefix
#              is added by the task_prefix module, not here.
# Responsibility:
#   - Combine content and tags into a single embedding input string
#   - Tags are space-separated, lowercased, appended after content
#   - Handle edge cases: no tags (content only), empty content, whitespace normalization
#   - Does NOT add task prefixes — that's task_prefix_search_document_query.py's job
#   - Does NOT truncate — model handles truncation (truncate=True in embed call)
# Organization:
#   build_embedding_input(content, tags) -> str — the single public function
# =============================================================================

from __future__ import annotations


def build_embedding_input(content: str, tags: list[str] | None = None) -> str:
    """Build the embedding input string from neuron content and optional tags.

    Format: "<content> <tag1> <tag2> <tag3>"
    If no tags: "<content>" (no trailing space)

    Args:
        content: The neuron's text content. May be empty string but not None.
        tags: Optional list of tag strings. Will be lowercased and space-joined.
              None or empty list means no tags appended.

    Returns:
        The assembled embedding input string, ready for prefix prepending.
    """
    # --- Step 1: Normalize content ---
    # Strip leading/trailing whitespace from content
    # Content may be empty string — that's valid (will still embed tags if present)

    # --- Step 2: Process tags ---
    # If tags is None or empty list:
    #   tags_string = ""
    # Else:
    #   Lowercase each tag, strip whitespace from each
    #   Filter out empty strings after stripping
    #   Join with single space: tags_string = " ".join(processed_tags)

    # --- Step 3: Combine content and tags ---
    # If tags_string is empty:
    #   return stripped_content
    # Else:
    #   return f"{stripped_content} {tags_string}"
    # Note: single space separator between content and tags block
    pass
