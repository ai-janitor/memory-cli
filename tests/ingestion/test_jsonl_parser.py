# =============================================================================
# Module: test_jsonl_parser.py
# Purpose: Test JSONL parsing — valid lines, invalid JSON, type filtering,
#   content extraction from both string and content-block formats.
# Rationale: The parser is the entry point for external data and must handle
#   real-world messiness: malformed JSON, unexpected types, empty lines,
#   mixed content formats. Each edge case needs explicit test coverage to
#   prevent silent data loss or pipeline crashes.
# Responsibility:
#   - Test valid user/assistant message parsing
#   - Test invalid JSON handling (warning, not crash)
#   - Test type filtering (skip tool_use, system, etc.)
#   - Test content extraction: string format
#   - Test content extraction: array-of-blocks format
#   - Test metadata extraction: timestamp, cwd, sessionId
#   - Test empty/whitespace lines are skipped
#   - Test file-not-found and permission errors
# Organization:
#   1. Imports and fixtures
#   2. TestParseJsonlSession — main entry point tests
#   3. TestParseLine — single line parsing
#   4. TestExtractContent — content extraction from different formats
#   5. Helpers — JSONL fixture builders
# =============================================================================

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from memory_cli.ingestion.jsonl_parser_claude_code_sessions import (
    ParsedMessage,
    ParseResult,
    _extract_content,
    _parse_line,
    parse_jsonl_session,
)


# -----------------------------------------------------------------------------
# Helpers — build JSONL lines for test fixtures
# -----------------------------------------------------------------------------

def _make_user_line(content: str, **kwargs) -> str:
    """Build a JSON string for a user message."""
    data: dict = {"type": "user", "message": {"content": content}}
    data.update(kwargs)
    return json.dumps(data)


def _make_assistant_line(content: str, **kwargs) -> str:
    """Build a JSON string for an assistant message."""
    data: dict = {"type": "assistant", "message": {"content": content}}
    data.update(kwargs)
    return json.dumps(data)


def _make_tool_line() -> str:
    """Build a JSON string for a tool_use message (should be filtered)."""
    return json.dumps({"type": "tool_use", "tool": "bash", "input": "ls"})


def _write_jsonl_file(lines: list) -> Path:
    """Write lines to a temp file and return the path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for line in lines:
        tmp.write(line + "\n")
    tmp.close()
    return Path(tmp.name)


class TestParseJsonlSession:
    """Test the main parse_jsonl_session() entry point."""

    def test_parse_valid_user_and_assistant_messages(self):
        """JSONL with 2 user + 2 assistant messages."""
        lines = [
            _make_user_line("Hello"),
            _make_assistant_line("Hi there"),
            _make_user_line("How are you?"),
            _make_assistant_line("I'm fine"),
        ]
        path = _write_jsonl_file(lines)
        result = parse_jsonl_session(path)
        assert len(result.messages) == 4
        assert result.messages[0].role == "user"
        assert result.messages[0].content == "Hello"
        assert result.messages[1].role == "assistant"
        assert result.messages[1].content == "Hi there"

    def test_parse_skips_invalid_json_with_warning(self):
        """JSONL with 1 valid line + 1 malformed line."""
        lines = [
            _make_user_line("valid"),
            "not valid json {{{",
        ]
        path = _write_jsonl_file(lines)
        result = parse_jsonl_session(path)
        assert len(result.messages) == 1
        assert len(result.warnings) == 1
        assert "Line 2" in result.warnings[0]

    def test_parse_skips_empty_lines_silently(self):
        """JSONL with blank lines between valid messages."""
        lines = [
            _make_user_line("first"),
            "",
            "   ",
            _make_assistant_line("second"),
        ]
        path = _write_jsonl_file(lines)
        result = parse_jsonl_session(path)
        assert len(result.messages) == 2
        assert len(result.warnings) == 0

    def test_parse_filters_non_message_types(self):
        """JSONL with user, assistant, tool_use, system lines."""
        lines = [
            _make_user_line("hello"),
            _make_tool_line(),
            json.dumps({"type": "system", "content": "init"}),
            _make_assistant_line("world"),
        ]
        path = _write_jsonl_file(lines)
        result = parse_jsonl_session(path)
        assert len(result.messages) == 2
        assert result.messages[0].role == "user"
        assert result.messages[1].role == "assistant"

    def test_parse_extracts_metadata(self):
        """JSONL with timestamp, cwd, sessionId fields."""
        line = json.dumps({
            "type": "user",
            "message": {"content": "hi"},
            "timestamp": "2024-01-15T10:30:00Z",
            "cwd": "/home/user/project",
            "sessionId": "sess-abc-123",
        })
        path = _write_jsonl_file([line])
        result = parse_jsonl_session(path)
        assert len(result.messages) == 1
        msg = result.messages[0]
        assert msg.timestamp == "2024-01-15T10:30:00Z"
        assert msg.cwd == "/home/user/project"
        assert msg.session_id == "sess-abc-123"

    def test_parse_empty_file_returns_empty(self):
        """Empty JSONL file."""
        path = _write_jsonl_file([])
        result = parse_jsonl_session(path)
        assert result.messages == []
        assert result.warnings == []

    def test_parse_file_not_found_raises(self):
        """Nonexistent path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            parse_jsonl_session(Path("/nonexistent/file.jsonl"))

    def test_parse_line_numbers_are_correct(self):
        """Each ParsedMessage.line_number matches its position in file."""
        lines = [
            _make_user_line("line 1"),
            "bad json",
            _make_assistant_line("line 3"),
        ]
        path = _write_jsonl_file(lines)
        result = parse_jsonl_session(path)
        assert len(result.messages) == 2
        assert result.messages[0].line_number == 1
        assert result.messages[1].line_number == 3


class TestParseLine:
    """Test _parse_line() for single-line parsing logic."""

    def test_valid_user_message_returns_parsed_message(self):
        """JSON with type="user", message.content="hello"."""
        line = json.dumps({"type": "user", "message": {"content": "hello"}})
        result = _parse_line(line, 1)
        assert result is not None
        assert result.role == "user"
        assert result.content == "hello"

    def test_valid_assistant_message_returns_parsed_message(self):
        """JSON with type="assistant"."""
        line = json.dumps({"type": "assistant", "message": {"content": "hi"}})
        result = _parse_line(line, 1)
        assert result is not None
        assert result.role == "assistant"
        assert result.content == "hi"

    def test_tool_use_type_returns_none(self):
        """JSON with type="tool_use" returns None."""
        line = json.dumps({"type": "tool_use"})
        result = _parse_line(line, 1)
        assert result is None

    def test_missing_type_returns_none(self):
        """JSON without "type" field returns None."""
        line = json.dumps({"content": "no type"})
        result = _parse_line(line, 1)
        assert result is None

    def test_invalid_json_raises_value_error(self):
        """Malformed JSON raises ValueError."""
        with pytest.raises(ValueError):
            _parse_line("not valid json {{{", 1)

    def test_empty_content_returns_none(self):
        """JSON with type="user" but empty content returns None."""
        line = json.dumps({"type": "user", "message": {"content": ""}})
        result = _parse_line(line, 1)
        assert result is None

    def test_metadata_fallback_fields(self):
        """JSON with "created_at" instead of "timestamp", "session_id" instead of "sessionId"."""
        line = json.dumps({
            "type": "user",
            "message": {"content": "hello"},
            "created_at": "2024-01-01T00:00:00Z",
            "session_id": "fallback-sess",
        })
        result = _parse_line(line, 1)
        assert result is not None
        assert result.timestamp == "2024-01-01T00:00:00Z"
        assert result.session_id == "fallback-sess"


class TestExtractContent:
    """Test _extract_content() for different content formats."""

    def test_string_content(self):
        """data = {"message": {"content": "hello world"}}."""
        assert _extract_content({"message": {"content": "hello world"}}) == "hello world"

    def test_content_blocks_text_only(self):
        """Array of text blocks joined with newlines."""
        data = {
            "message": {
                "content": [
                    {"type": "text", "text": "part1"},
                    {"type": "text", "text": "part2"},
                ]
            }
        }
        result = _extract_content(data)
        assert result == "part1\npart2"

    def test_content_blocks_skips_non_text(self):
        """Image blocks are skipped."""
        data = {
            "message": {
                "content": [
                    {"type": "text", "text": "yes"},
                    {"type": "image", "source": "data:..."},
                ]
            }
        }
        result = _extract_content(data)
        assert result == "yes"

    def test_fallback_to_direct_content_field(self):
        """data = {"content": "fallback"} (no "message" wrapper)."""
        result = _extract_content({"content": "fallback"})
        assert result == "fallback"

    def test_no_content_returns_empty(self):
        """data = {"type": "user"} (no content at all)."""
        result = _extract_content({"type": "user"})
        assert result == ""

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped from content."""
        result = _extract_content({"message": {"content": "  spaced  "}})
        assert result == "spaced"
