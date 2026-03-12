# =============================================================================
# Module: haiku_query_expansion_terms.py
# Purpose: Build a query expansion prompt for Haiku, call the API, and parse
#   the list of related search terms from the response.
# Rationale: Query expansion discovers related concepts the user didn't
#   explicitly mention, improving recall. A language model is better at
#   semantic expansion than synonym dictionaries. Isolating prompt
#   construction and parsing makes it testable and swappable.
# Responsibility:
#   - Build system prompt for query expansion (structured output instruction)
#   - Build user message with the original query
#   - Call Haiku API (single-turn, stateless)
#   - Parse response: extract flat list of related terms
#   - Validate term count (expect 3-8 terms)
#   - Raise typed exceptions for auth, network, malformed responses
# Organization:
#   1. Imports
#   2. Constants (system prompt, min/max terms)
#   3. haiku_expand_query() — main entry point
#   4. _build_expansion_system_prompt() — construct system prompt
#   5. _build_expansion_user_message() — construct user message
#   6. _parse_expansion_response() — extract term list from response
# =============================================================================

from __future__ import annotations

import json
from typing import List

from .haiku_rerank_by_neuron_ids import (
    HaikuAuthError,
    HaikuMalformedResponse,
    HaikuNetworkError,
    _call_haiku_api,
)


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
# MIN_EXPANSION_TERMS: minimum expected terms from Haiku
MIN_EXPANSION_TERMS = 3
# MAX_EXPANSION_TERMS: maximum terms to use (truncate if more)
MAX_EXPANSION_TERMS = 8


def haiku_expand_query(
    api_key: str,
    model: str,
    query: str,
) -> List[str]:
    """Call Haiku to generate related search terms for query expansion.

    Flow:
    1. Build system prompt via _build_expansion_system_prompt()
    2. Build user message via _build_expansion_user_message(query)
    3. Call Haiku API (reuse _call_haiku_api from rerank module)
       - Single-turn: one system message + one user message
       - Temperature: 0.5 (slight creativity for diverse terms)
       - Max tokens: 256 (term list is short)
    4. Parse response via _parse_expansion_response(response_text)
       - Expected: JSON array of strings, e.g., ["term1", "term2", ...]
    5. Truncate to MAX_EXPANSION_TERMS if more returned
    6. Return list of expansion terms

    The terms are meant to be fed back into light search as additional
    queries. They should be conceptually related but not identical to
    the original query.

    Args:
        api_key: Anthropic API key.
        model: Model identifier (e.g., "claude-haiku-4-5-20251001").
        query: User's original search query.

    Returns:
        List of 3-8 related search term strings.

    Raises:
        HaikuAuthError: On 401/403 response.
        HaikuNetworkError: On timeout, connection error, 429.
        HaikuMalformedResponse: If response cannot be parsed into term list.
    """
    system_prompt = _build_expansion_system_prompt()
    user_message = _build_expansion_user_message(query)
    response_text = _call_haiku_api(api_key, model, system_prompt, user_message)
    terms = _parse_expansion_response(response_text)
    return terms[:MAX_EXPANSION_TERMS]


def _build_expansion_system_prompt() -> str:
    """Construct the system prompt for Haiku query expansion.

    Prompt requirements:
    - Instruct Haiku to generate related search terms
    - Terms should be semantically related but not identical to query
    - Output format: JSON array of strings
    - Generate between 3 and 8 terms
    - Terms should be short (1-4 words each)
    - No explanation, no commentary, no wrapping
    - Example output: ["machine learning", "neural networks", "deep learning"]

    Returns:
        System prompt string.
    """
    return (
        "You are a search query expansion engine. Given a search query, generate 3 to 8 "
        "related search terms that are semantically related but not identical to the query.\n\n"
        "Terms should be short (1-4 words each). Return ONLY a JSON array of strings. "
        "No explanation, no commentary, no wrapping.\n\n"
        "Example output: [\"machine learning\", \"neural networks\", \"deep learning\"]"
    )


def _build_expansion_user_message(query: str) -> str:
    """Construct user message with the query for expansion.

    Format is simple — just the query. The system prompt provides
    all the context about what to do with it.

    Format:
    ```
    Query: <user query>
    ```

    Args:
        query: User's search query.

    Returns:
        Formatted user message string.
    """
    return f"Query: {query}"


def _parse_expansion_response(response_text: str) -> List[str]:
    """Parse Haiku's response into a list of expansion terms.

    Parsing steps:
    1. Strip whitespace
    2. Strip markdown code fences if present
    3. Parse as JSON
    4. Validate: must be a list
    5. Validate: each element must be a non-empty string
    6. Strip whitespace from each term
    7. Filter out empty strings after stripping
    8. Truncate to MAX_EXPANSION_TERMS
    9. Return list of term strings

    On parse failure: raise HaikuMalformedResponse.
    If fewer than MIN_EXPANSION_TERMS valid terms: raise HaikuMalformedResponse
    (Haiku didn't generate enough useful terms — not worth the expansion cost).

    Args:
        response_text: Raw text from Haiku API response.

    Returns:
        List of expansion term strings (3-8 items).

    Raises:
        HaikuMalformedResponse: If parsing fails or too few terms.
    """
    text = response_text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise HaikuMalformedResponse(f"Failed to parse JSON: {e}") from e
    if not isinstance(parsed, list):
        raise HaikuMalformedResponse(f"Expected a JSON array of strings, got {type(parsed).__name__}")
    terms = []
    for item in parsed:
        if not isinstance(item, str):
            raise HaikuMalformedResponse(f"Expected string elements, got {type(item).__name__}: {item!r}")
        stripped = item.strip()
        if stripped:
            terms.append(stripped)
    # Truncate to max
    terms = terms[:MAX_EXPANSION_TERMS]
    if len(terms) < MIN_EXPANSION_TERMS:
        raise HaikuMalformedResponse(
            f"Too few expansion terms: {len(terms)} (minimum {MIN_EXPANSION_TERMS})"
        )
    return terms
