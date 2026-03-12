# =============================================================================
# Module: test_message_assembler.py
# Purpose: Test transcript assembly — formatting, turn ordering by timestamp,
#   and chunking at turn boundaries when transcripts exceed context budget.
# Rationale: The assembler bridges raw messages and the Haiku extraction
#   prompt. Incorrect ordering corrupts the conversation context. Incorrect
#   chunking can split mid-turn or exceed context limits. Both produce
#   garbage extraction results, so each behavior needs explicit tests.
# Responsibility:
#   - Test Human:/Assistant: formatting
#   - Test timestamp-based ordering with line_number tiebreaker
#   - Test chunking at turn boundaries
#   - Test oversized single turns (allowed as solo chunk)
#   - Test edge cases: empty input, single message, no timestamps
# Organization:
#   1. Imports and fixtures
#   2. TestAssembleTranscriptChunks — main entry point tests
#   3. TestFormatTurn — turn formatting
#   4. TestEstimateTokens — token estimation
#   5. TestSortMessagesByTimestamp — sorting logic
# =============================================================================

from __future__ import annotations

import pytest

from memory_cli.ingestion.jsonl_parser_claude_code_sessions import ParsedMessage
from memory_cli.ingestion.message_assembler_transcript import (
    CHARS_PER_TOKEN_ESTIMATE,
    TRANSCRIPT_CHUNK_BUDGET,
    _estimate_tokens,
    _format_turn,
    _sort_messages_by_timestamp,
    assemble_transcript_chunks,
)


# -----------------------------------------------------------------------------
# Helpers — build ParsedMessage fixtures
# -----------------------------------------------------------------------------

def _msg(role: str, content: str, timestamp: str = None, line_number: int = 0) -> ParsedMessage:
    """Create a ParsedMessage for testing."""
    return ParsedMessage(
        role=role,
        content=content,
        timestamp=timestamp,
        line_number=line_number,
    )


class TestAssembleTranscriptChunks:
    """Test the main assemble_transcript_chunks() entry point."""

    def test_single_chunk_small_conversation(self):
        """3 messages well under budget -> 1 chunk containing all turns."""
        msgs = [
            _msg("user", "hi", "2024-01-01T00:00:00"),
            _msg("assistant", "hello", "2024-01-01T00:00:01"),
            _msg("user", "bye", "2024-01-01T00:00:02"),
        ]
        chunks = assemble_transcript_chunks(msgs)
        assert len(chunks) == 1
        assert "Human: hi" in chunks[0]
        assert "Assistant: hello" in chunks[0]
        assert "Human: bye" in chunks[0]

    def test_multiple_chunks_large_conversation(self):
        """Many messages exceeding budget -> multiple chunks."""
        # Create messages that each are ~1/4 of the budget
        big_content = "x" * (TRANSCRIPT_CHUNK_BUDGET * CHARS_PER_TOKEN_ESTIMATE // 3 + 1)
        msgs = [
            _msg("user", big_content, f"2024-01-01T00:00:0{i}", i)
            for i in range(6)
        ]
        chunks = assemble_transcript_chunks(msgs)
        assert len(chunks) > 1

    def test_empty_input_returns_empty(self):
        """Empty message list -> return []."""
        chunks = assemble_transcript_chunks([])
        assert chunks == []

    def test_single_message_returns_single_chunk(self):
        """1 message -> list with 1 chunk."""
        msgs = [_msg("user", "hello")]
        chunks = assemble_transcript_chunks(msgs)
        assert len(chunks) == 1

    def test_chunks_separated_by_double_newline(self):
        """Turns within a chunk are joined by "\\n\\n"."""
        msgs = [
            _msg("user", "hi", "2024-01-01T00:00:00"),
            _msg("assistant", "hello", "2024-01-01T00:00:01"),
        ]
        chunks = assemble_transcript_chunks(msgs)
        assert len(chunks) == 1
        assert "\n\nAssistant:" in chunks[0]

    def test_messages_sorted_before_chunking(self):
        """Messages passed in reverse order -> chunk content in chronological order."""
        msgs = [
            _msg("assistant", "second", "2024-01-01T00:00:01"),
            _msg("user", "first", "2024-01-01T00:00:00"),
        ]
        chunks = assemble_transcript_chunks(msgs)
        assert len(chunks) == 1
        # "first" should appear before "second" in the chunk
        chunk = chunks[0]
        assert chunk.index("first") < chunk.index("second")

    def test_oversized_single_turn_gets_own_chunk(self):
        """One message with content exceeding budget -> its own chunk."""
        huge_content = "x" * (TRANSCRIPT_CHUNK_BUDGET * CHARS_PER_TOKEN_ESTIMATE * 2)
        msgs = [_msg("user", huge_content)]
        chunks = assemble_transcript_chunks(msgs)
        assert len(chunks) == 1
        assert "Human: " in chunks[0]


class TestFormatTurn:
    """Test _format_turn() formatting logic."""

    def test_user_message_formats_as_human(self):
        """ParsedMessage(role="user") -> "Human: <content>"."""
        msg = ParsedMessage(role="user", content="hello")
        assert _format_turn(msg) == "Human: hello"

    def test_assistant_message_formats_as_assistant(self):
        """ParsedMessage(role="assistant") -> "Assistant: <content>"."""
        msg = ParsedMessage(role="assistant", content="hi")
        assert _format_turn(msg) == "Assistant: hi"

    def test_multiline_content_preserved(self):
        """Newlines in content are preserved."""
        msg = ParsedMessage(role="user", content="line1\nline2")
        result = _format_turn(msg)
        assert "line1\nline2" in result


class TestEstimateTokens:
    """Test _estimate_tokens() heuristic."""

    def test_short_text(self):
        """'hello' (5 chars) -> ceil(5/4) = 2 tokens."""
        assert _estimate_tokens("hello") == 2

    def test_empty_text(self):
        """Empty string -> at least 1 token (minimum)."""
        assert _estimate_tokens("") == 1

    def test_long_text_proportional(self):
        """400 chars -> 100 tokens."""
        assert _estimate_tokens("x" * 400) == 100

    def test_four_char_text(self):
        """4 chars -> 1 token."""
        assert _estimate_tokens("abcd") == 1

    def test_five_char_text(self):
        """5 chars -> ceil(5/4) = 2 tokens."""
        assert _estimate_tokens("abcde") == 2


class TestSortMessagesByTimestamp:
    """Test _sort_messages_by_timestamp() ordering."""

    def test_sorts_by_timestamp_ascending(self):
        """Messages with timestamps out of order -> sorted ascending."""
        msgs = [
            _msg("user", "b", "2024-01-02", line_number=2),
            _msg("user", "a", "2024-01-01", line_number=1),
        ]
        sorted_msgs = _sort_messages_by_timestamp(msgs)
        assert sorted_msgs[0].content == "a"
        assert sorted_msgs[1].content == "b"

    def test_none_timestamps_sort_last(self):
        """Messages with None timestamps appear at end."""
        msgs = [
            _msg("user", "no-ts", None, line_number=1),
            _msg("user", "has-ts", "2024-01-01", line_number=2),
        ]
        sorted_msgs = _sort_messages_by_timestamp(msgs)
        assert sorted_msgs[0].content == "has-ts"
        assert sorted_msgs[1].content == "no-ts"

    def test_same_timestamp_preserves_line_order(self):
        """Same timestamp -> sorted by line_number."""
        msgs = [
            _msg("user", "line3", "2024-01-01", line_number=3),
            _msg("user", "line1", "2024-01-01", line_number=1),
            _msg("user", "line2", "2024-01-01", line_number=2),
        ]
        sorted_msgs = _sort_messages_by_timestamp(msgs)
        assert [m.line_number for m in sorted_msgs] == [1, 2, 3]

    def test_does_not_mutate_input(self):
        """Original list is unchanged after sort."""
        msgs = [
            _msg("user", "b", "2024-01-02"),
            _msg("user", "a", "2024-01-01"),
        ]
        original_order = [m.content for m in msgs]
        _sort_messages_by_timestamp(msgs)
        assert [m.content for m in msgs] == original_order
