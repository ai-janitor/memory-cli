# =============================================================================
# Module: haiku_rerank_by_neuron_ids.py
# Purpose: Build a re-ranking prompt for Haiku, call the API, and parse the
#   ordered neuron ID list from the response. Defensive handling of unknown
#   IDs, missing IDs, duplicates, and malformed responses.
# Rationale: Re-ranking is the highest-value phase of heavy search — it lets
#   a language model judge semantic relevance better than BM25/vector scores
#   alone. Isolating prompt construction and response parsing makes it
#   testable without live API calls and keeps the orchestrator clean.
# Responsibility:
#   - Build system prompt for re-ranking (structured output instruction)
#   - Build user message with query + candidate neuron summaries
#   - Call Haiku API (single-turn, stateless)
#   - Parse response: extract ordered list of neuron IDs
#   - Defensive handling: discard unknown IDs, append missing IDs at end
#   - Handle duplicates in Haiku response (keep first occurrence only)
#   - Raise typed exceptions for auth, network, malformed responses
# Organization:
#   1. Imports
#   2. Custom exceptions
#   3. Constants (system prompt template, max content preview length)
#   4. haiku_rerank() — main entry point
#   5. _build_rerank_system_prompt() — construct system prompt
#   6. _build_rerank_user_message() — construct user message with candidates
#   7. _call_haiku_api() — HTTP call to Anthropic Messages API
#   8. _parse_rerank_response() — extract ordered ID list from response
#   9. _apply_defensive_reorder() — reconcile Haiku IDs with actual candidates
# =============================================================================

from __future__ import annotations

import json
from typing import Any, Dict, List, Set


# -----------------------------------------------------------------------------
# Custom exceptions for typed error handling in orchestrator.
# -----------------------------------------------------------------------------

class HaikuAuthError(Exception):
    """Raised on 401/403 from Haiku API. Caller should sys.exit(2)."""

    pass


class HaikuNetworkError(Exception):
    """Raised on timeout, connection error, or 429 rate limit."""

    pass


class HaikuMalformedResponse(Exception):
    """Raised when Haiku response cannot be parsed into an ID list."""

    pass


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
# MAX_CONTENT_PREVIEW: truncate neuron content to this length in prompts
# to stay within Haiku's context window and reduce cost
MAX_CONTENT_PREVIEW = 500

# RERANK_SYSTEM_PROMPT: instructs Haiku to return only ordered neuron IDs
# Format: JSON array of integer IDs, most relevant first
# No explanation, no commentary, no extra fields
RERANK_SYSTEM_PROMPT = ""  # Will contain structured output instructions


def haiku_rerank(
    api_key: str,
    model: str,
    query: str,
    candidates: List[Dict[str, Any]],
) -> List[int]:
    """Call Haiku to re-rank candidate neurons by relevance to query.

    Flow:
    1. Build system prompt via _build_rerank_system_prompt()
    2. Build user message via _build_rerank_user_message(query, candidates)
       - Each candidate: ID + truncated content preview
       - Candidates presented in current order (light search ranking)
    3. Call Haiku API via _call_haiku_api(api_key, model, system, user)
       - Single-turn: one system message + one user message
       - Temperature: 0 (deterministic re-ranking)
       - Max tokens: enough for ID list (e.g., 1024)
    4. Parse response via _parse_rerank_response(response_text)
       - Expected: JSON array of integer IDs, e.g., [42, 17, 3, 88]
       - Strip markdown fences if present
    5. Apply defensive reorder via _apply_defensive_reorder(parsed_ids, candidates)
       - Discard IDs not in candidate set
       - Deduplicate (keep first occurrence)
       - Append any candidate IDs missing from Haiku's list at the end
    6. Return ordered list of neuron IDs

    Args:
        api_key: Anthropic API key.
        model: Model identifier (e.g., "claude-haiku-4-5-20251001").
        query: User's search query.
        candidates: List of neuron result dicts (must have "id" and "content").

    Returns:
        Ordered list of neuron IDs, most relevant first.

    Raises:
        HaikuAuthError: On 401/403 response.
        HaikuNetworkError: On timeout, connection error, 429.
        HaikuMalformedResponse: If response cannot be parsed into ID list.
    """
    system_prompt = _build_rerank_system_prompt()
    user_message = _build_rerank_user_message(query, candidates)
    response_text = _call_haiku_api(api_key, model, system_prompt, user_message)
    haiku_ids = _parse_rerank_response(response_text)
    return _apply_defensive_reorder(haiku_ids, candidates)


def _build_rerank_system_prompt() -> str:
    """Construct the system prompt for Haiku re-ranking.

    Prompt requirements:
    - Instruct Haiku to act as a relevance ranker
    - Specify output format: JSON array of integer neuron IDs
    - Most relevant to the query first
    - Must include ALL provided IDs (no dropping)
    - No explanation, no commentary, no wrapping
    - Example output: [42, 17, 3, 88]

    Returns:
        System prompt string.
    """
    return (
        "You are a relevance ranker. Given a query and a list of candidate items with IDs, "
        "re-rank them from most to least relevant to the query.\n\n"
        "Return ONLY a JSON array of integer IDs in order of relevance, most relevant first. "
        "Include ALL provided IDs. No explanation, no commentary, no wrapping.\n\n"
        "Example output: [42, 17, 3, 88]"
    )


def _build_rerank_user_message(
    query: str,
    candidates: List[Dict[str, Any]],
) -> str:
    """Construct user message with query and candidate summaries.

    Format:
    ```
    Query: <user query>

    Candidates:
    ID: 42
    Content: <first MAX_CONTENT_PREVIEW chars of content>

    ID: 17
    Content: <first MAX_CONTENT_PREVIEW chars of content>
    ...
    ```

    Content is truncated to MAX_CONTENT_PREVIEW characters with "..." suffix
    if truncated. This keeps the prompt size bounded.

    Args:
        query: User's search query.
        candidates: List of neuron result dicts.

    Returns:
        Formatted user message string.
    """
    lines = [f"Query: {query}", "", "Candidates:"]
    for candidate in candidates:
        cid = candidate.get("id", "")
        content = candidate.get("content", "")
        if len(content) > MAX_CONTENT_PREVIEW:
            content = content[:MAX_CONTENT_PREVIEW] + "..."
        lines.append(f"ID: {cid}")
        lines.append(f"Content: {content}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _call_haiku_api(
    api_key: str,
    model: str,
    system_prompt: str,
    user_message: str,
) -> str:
    """Make a single-turn API call to Anthropic Messages API.

    HTTP call details:
    - Endpoint: https://api.anthropic.com/v1/messages
    - Method: POST
    - Headers:
        x-api-key: <api_key>
        anthropic-version: 2023-06-01
        content-type: application/json
    - Body:
        model: <model>
        max_tokens: 1024
        temperature: 0
        system: <system_prompt>
        messages: [{"role": "user", "content": <user_message>}]
    - Timeout: 30 seconds

    Response handling:
    - 200: extract content[0].text from response JSON
    - 401/403: raise HaikuAuthError
    - 429: raise HaikuNetworkError (rate limited, treat as transient)
    - 5xx: raise HaikuNetworkError
    - Timeout: raise HaikuNetworkError
    - Connection error: raise HaikuNetworkError

    Args:
        api_key: Anthropic API key (never logged).
        model: Model identifier.
        system_prompt: System prompt string.
        user_message: User message string.

    Returns:
        Response text content from Haiku.

    Raises:
        HaikuAuthError: On 401/403.
        HaikuNetworkError: On timeout, connection error, 429, 5xx.
    """
    import httpx

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 1024,
        "temperature": 0,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }
    try:
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body,
            timeout=30.0,
        )
    except httpx.TimeoutException as e:
        raise HaikuNetworkError(f"Request timed out: {e}") from e
    except httpx.ConnectError as e:
        raise HaikuNetworkError(f"Connection error: {e}") from e
    except httpx.RequestError as e:
        raise HaikuNetworkError(f"Request error: {e}") from e

    if response.status_code in (401, 403):
        raise HaikuAuthError(f"Authentication failed: HTTP {response.status_code}")
    if response.status_code == 429:
        raise HaikuNetworkError(f"Rate limited: HTTP 429")
    if response.status_code >= 500:
        raise HaikuNetworkError(f"Server error: HTTP {response.status_code}")

    data = response.json()
    return data["content"][0]["text"]


def _parse_rerank_response(response_text: str) -> List[int]:
    """Parse Haiku's response text into an ordered list of neuron IDs.

    Parsing steps:
    1. Strip whitespace
    2. Strip markdown code fences if present (```json ... ``` or ``` ... ```)
    3. Parse as JSON
    4. Validate: must be a list
    5. Validate: each element must be an integer (or int-coercible string)
    6. Return list of ints

    On any parse failure: raise HaikuMalformedResponse with description.

    Args:
        response_text: Raw text from Haiku API response.

    Returns:
        List of integer neuron IDs.

    Raises:
        HaikuMalformedResponse: If parsing fails at any step.
    """
    text = response_text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise HaikuMalformedResponse(f"Failed to parse JSON: {e}") from e
    if not isinstance(parsed, list):
        raise HaikuMalformedResponse(f"Expected a JSON array, got {type(parsed).__name__}")
    result = []
    for item in parsed:
        if isinstance(item, int):
            result.append(item)
        elif isinstance(item, str):
            try:
                result.append(int(item))
            except ValueError:
                raise HaikuMalformedResponse(f"Non-integer element in ID list: {item!r}")
        else:
            raise HaikuMalformedResponse(f"Non-integer element in ID list: {item!r}")
    return result


def _apply_defensive_reorder(
    haiku_ids: List[int],
    candidates: List[Dict[str, Any]],
) -> List[int]:
    """Reconcile Haiku's ID list with actual candidate IDs.

    Defensive rules:
    1. Build set of valid candidate IDs from candidates list
    2. Walk haiku_ids in order:
       a. Skip if ID not in valid set (Haiku hallucinated an ID)
       b. Skip if ID already seen (Haiku duplicated an ID)
       c. Otherwise, add to result list and mark as seen
    3. After processing haiku_ids, find any candidate IDs NOT in result
       - Append them in their original order (from candidates list)
       - This ensures no candidates are lost

    This guarantees:
    - Every candidate appears exactly once in the output
    - Haiku's ordering is respected for IDs it returned correctly
    - Unknown/duplicate IDs from Haiku are silently dropped
    - Missing IDs appear at the end in original order

    Args:
        haiku_ids: Ordered ID list from Haiku (may be imperfect).
        candidates: Original candidate list from light search.

    Returns:
        Fully reconciled ordered list of neuron IDs.
    """
    # Build set of valid candidate IDs
    valid_ids = {c["id"] for c in candidates}
    candidate_order = [c["id"] for c in candidates]

    result: List[int] = []
    seen: Set[int] = set()

    # Walk haiku_ids: skip unknown and duplicates
    for hid in haiku_ids:
        if hid not in valid_ids:
            continue
        if hid in seen:
            continue
        result.append(hid)
        seen.add(hid)

    # Append any candidates missing from Haiku's list in original order
    for cid in candidate_order:
        if cid not in seen:
            result.append(cid)
            seen.add(cid)

    return result
