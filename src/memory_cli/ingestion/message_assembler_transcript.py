# =============================================================================
# Module: message_assembler_transcript.py
# Purpose: Assemble parsed messages into Human:/Assistant: transcript strings,
#   chunking at turn boundaries when the transcript exceeds Haiku's context
#   window limit.
# Rationale: Haiku needs a coherent conversational transcript to extract
#   entities and relationships. Raw JSONL messages must be stitched into a
#   readable format. Long sessions may exceed context limits, so we chunk
#   at natural turn boundaries (never mid-turn) to preserve conversational
#   coherence within each chunk.
# Responsibility:
#   - Sort messages by timestamp (preserving file order as tiebreaker)
#   - Format each message as "Human: <content>" or "Assistant: <content>"
#   - Estimate token count for chunking decisions
#   - Chunk at turn boundaries when approaching context limit
#   - Return ordered list of transcript chunk strings
# Organization:
#   1. Imports
#   2. Constants (context limits, token estimation)
#   3. assemble_transcript_chunks() — main entry point
#   4. _format_turn() — format a single message as Human:/Assistant: turn
#   5. _estimate_tokens() — rough token count estimation
#   6. _sort_messages_by_timestamp() — stable sort by timestamp
# =============================================================================

from __future__ import annotations

from typing import List

# Avoid circular import — use TYPE_CHECKING for type hints only
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .jsonl_parser_claude_code_sessions import ParsedMessage


# -----------------------------------------------------------------------------
# Constants — Haiku context window budget for extraction.
# We reserve tokens for the extraction prompt and structured output.
# The transcript chunk gets the remaining budget.
# -----------------------------------------------------------------------------
HAIKU_CONTEXT_LIMIT_TOKENS = 180_000  # Haiku total context window
EXTRACTION_PROMPT_RESERVE = 4_000  # Tokens reserved for system prompt + output
TRANSCRIPT_CHUNK_BUDGET = HAIKU_CONTEXT_LIMIT_TOKENS - EXTRACTION_PROMPT_RESERVE
CHARS_PER_TOKEN_ESTIMATE = 4  # Conservative estimate for English text


def assemble_transcript_chunks(messages: List["ParsedMessage"]) -> List[str]:
    """Assemble parsed messages into transcript chunks for Haiku extraction.

    Each chunk is a self-contained Human:/Assistant: transcript that fits
    within Haiku's context budget. Chunks split at turn boundaries only —
    a single turn is never split across chunks (if a single turn exceeds
    the budget, it goes into its own chunk with a warning).

    Logic flow:
    1. Sort messages by timestamp via _sort_messages_by_timestamp()
       - Stable sort: preserves file order for messages with same timestamp
    2. Format each message as a turn string via _format_turn()
    3. Accumulate turns into current chunk, tracking estimated token count
       a. For each formatted turn:
          - Estimate tokens via _estimate_tokens()
          - If adding this turn would exceed TRANSCRIPT_CHUNK_BUDGET:
            * Finalize current chunk (join accumulated turns with "\\n\\n")
            * Start new chunk with this turn
          - Else: append turn to current chunk accumulator
    4. Finalize last chunk if non-empty
    5. Return list of chunk strings

    Edge cases:
    - Empty messages list -> return empty list
    - Single message -> return list with one chunk
    - Single turn exceeding budget -> chunk contains just that turn (oversized)
    - All messages fit in one chunk -> return list with one chunk

    Args:
        messages: Parsed messages from JSONL parser, may be unsorted.

    Returns:
        List of transcript chunk strings, each suitable for Haiku extraction.
    """
    # --- Sort messages by timestamp ---
    # sorted_msgs = _sort_messages_by_timestamp(messages)

    # --- Format and accumulate into chunks ---
    # chunks = []
    # current_turns = []
    # current_tokens = 0
    #
    # for msg in sorted_msgs:
    #     turn = _format_turn(msg)
    #     turn_tokens = _estimate_tokens(turn)
    #
    #     if current_tokens + turn_tokens > TRANSCRIPT_CHUNK_BUDGET and current_turns:
    #         chunks.append("\n\n".join(current_turns))
    #         current_turns = []
    #         current_tokens = 0
    #
    #     current_turns.append(turn)
    #     current_tokens += turn_tokens

    # --- Finalize last chunk ---
    # if current_turns:
    #     chunks.append("\n\n".join(current_turns))

    # return chunks

    pass


def _format_turn(message: "ParsedMessage") -> str:
    """Format a single message as a Human: or Assistant: turn.

    Maps role to prefix:
    - "user" -> "Human: <content>"
    - "assistant" -> "Assistant: <content>"

    Content is used as-is (no additional stripping — parser already cleaned it).

    Args:
        message: A ParsedMessage with role and content.

    Returns:
        Formatted turn string with role prefix.
    """
    # --- Map role to prefix ---
    # prefix = "Human" if message.role == "user" else "Assistant"
    # return f"{prefix}: {message.content}"

    pass


def _estimate_tokens(text: str) -> int:
    """Estimate token count for a text string.

    Uses a simple character-based heuristic (chars / CHARS_PER_TOKEN_ESTIMATE).
    This is intentionally conservative — we'd rather chunk too early than
    exceed Haiku's context limit.

    Args:
        text: Text string to estimate.

    Returns:
        Estimated token count (integer, rounded up).
    """
    # --- Simple character-based estimation ---
    # return max(1, -(-len(text) // CHARS_PER_TOKEN_ESTIMATE))  # ceiling division

    pass


def _sort_messages_by_timestamp(messages: List["ParsedMessage"]) -> List["ParsedMessage"]:
    """Sort messages by timestamp, preserving file order as tiebreaker.

    Messages without timestamps sort to the end (None timestamps are
    treated as infinitely large). Within same-timestamp messages,
    original file order (line_number) is preserved via stable sort.

    Logic flow:
    1. Sort by (timestamp or "", line_number) — stable sort
       - Empty string sorts before any timestamp, but we want None-timestamps
         at the END, so use a high sentinel for None
    2. Return sorted list (new list, does not mutate input)

    Args:
        messages: List of ParsedMessages, potentially unsorted.

    Returns:
        New list sorted by timestamp with line_number as tiebreaker.
    """
    # --- Stable sort by timestamp then line_number ---
    # sentinel = "9999-99-99T99:99:99"  # sorts after any real ISO timestamp
    # return sorted(
    #     messages,
    #     key=lambda m: (m.timestamp or sentinel, m.line_number)
    # )

    pass
