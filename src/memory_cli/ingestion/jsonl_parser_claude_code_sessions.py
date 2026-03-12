# =============================================================================
# Module: jsonl_parser_claude_code_sessions.py
# Purpose: Parse Claude Code JSONL session files line-by-line, extracting
#   user and assistant messages with their metadata. Handles the specific
#   JSONL format that Claude Code emits for session logs.
# Rationale: JSONL parsing is the first stage of ingestion and must be
#   resilient — real session files can have malformed lines, empty lines,
#   and non-message entries (tool calls, system events). This module
#   isolates format-specific parsing so the rest of the pipeline works
#   with clean, typed message objects.
# Responsibility:
#   - Read JSONL file line-by-line (streaming, not load-all)
#   - Parse each line as JSON, skip unparseable lines with warning
#   - Filter for type "user" and "assistant" messages only
#   - Extract content from string or array-of-content-blocks format
#   - Extract metadata: timestamp, cwd, sessionId, role
#   - Return ordered list of ParsedMessage objects
# Organization:
#   1. Imports
#   2. ParsedMessage — dataclass for a single parsed message
#   3. ParseResult — dataclass wrapping messages + parse warnings
#   4. parse_jsonl_session() — main entry point
#   5. _parse_line() — single line JSON parse + validation
#   6. _extract_content() — handle string vs content-blocks array
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ParsedMessage:
    """A single message extracted from a JSONL session file.

    Represents one conversational turn (user or assistant) with all
    relevant metadata needed by downstream pipeline stages.

    Attributes:
        role: "user" or "assistant".
        content: Extracted text content of the message.
        timestamp: ISO timestamp string from the message, if present.
        cwd: Working directory at time of message, if present.
        session_id: Session identifier from the message metadata, if present.
        line_number: 1-based line number in the source JSONL file.
    """

    role: str
    content: str
    timestamp: Optional[str] = None
    cwd: Optional[str] = None
    session_id: Optional[str] = None
    line_number: int = 0


@dataclass
class ParseResult:
    """Result of parsing a JSONL session file.

    Contains the ordered list of valid messages and any warnings
    from unparseable or skipped lines.

    Attributes:
        messages: List of successfully parsed messages, in file order.
        warnings: List of warning strings for skipped/malformed lines.
    """

    messages: List[ParsedMessage] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def parse_jsonl_session(jsonl_path: Path) -> ParseResult:
    """Parse a Claude Code JSONL session file into message objects.

    Reads the file line-by-line (streaming) to handle large session files
    without loading everything into memory.

    Logic flow:
    1. Open file for reading (UTF-8)
       - FileNotFoundError -> re-raise with clear message
       - PermissionError -> re-raise with clear message
    2. For each line (enumerate from 1):
       a. Strip whitespace — skip empty lines silently
       b. Call _parse_line(line, line_number)
       c. If _parse_line returns None: skip (not a user/assistant message)
       d. If _parse_line raises ValueError: append warning, continue
       e. If valid ParsedMessage: append to messages list
    3. Return ParseResult(messages, warnings)

    Args:
        jsonl_path: Path to the JSONL session file.

    Returns:
        ParseResult with messages and any parse warnings.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        PermissionError: If the file isn't readable.
    """
    # --- Open file for line-by-line reading ---
    # with open(jsonl_path, "r", encoding="utf-8") as f:
    #     for line_number, raw_line in enumerate(f, start=1):
    #         stripped = raw_line.strip()
    #         if not stripped: continue
    #         try:
    #             msg = _parse_line(stripped, line_number)
    #             if msg is not None:
    #                 messages.append(msg)
    #         except ValueError as e:
    #             warnings.append(f"Line {line_number}: {e}")

    # --- Return collected messages and warnings ---
    # return ParseResult(messages=messages, warnings=warnings)

    pass


def _parse_line(raw_json: str, line_number: int) -> Optional[ParsedMessage]:
    """Parse a single JSONL line into a ParsedMessage or None.

    Returns None for valid JSON that isn't a user/assistant message
    (e.g., tool calls, system events). Raises ValueError for
    unparseable JSON.

    Logic flow:
    1. json.loads(raw_json) — raise ValueError on parse failure
    2. Check "type" field — must be "user" or "assistant"
       - If missing or different type: return None (not a message we care about)
    3. Extract "role" from type field
    4. Extract content via _extract_content(data)
       - If content is empty after extraction: return None
    5. Extract optional metadata:
       - timestamp: data.get("timestamp") or data.get("created_at")
       - cwd: data.get("cwd")
       - session_id: data.get("sessionId") or data.get("session_id")
    6. Return ParsedMessage with all fields

    Args:
        raw_json: A single line from the JSONL file.
        line_number: 1-based line number for error reporting.

    Returns:
        ParsedMessage if line is a user/assistant message, None otherwise.

    Raises:
        ValueError: If JSON parsing fails.
    """
    # --- Parse JSON ---
    # try: data = json.loads(raw_json)
    # except json.JSONDecodeError as e: raise ValueError(f"Invalid JSON: {e}")

    # --- Check message type ---
    # msg_type = data.get("type")
    # if msg_type not in ("user", "assistant"): return None

    # --- Extract content ---
    # content = _extract_content(data)
    # if not content: return None

    # --- Extract metadata ---
    # timestamp = data.get("timestamp") or data.get("created_at")
    # cwd = data.get("cwd")
    # session_id = data.get("sessionId") or data.get("session_id")

    # --- Build and return ParsedMessage ---
    # return ParsedMessage(
    #     role=msg_type, content=content, timestamp=timestamp,
    #     cwd=cwd, session_id=session_id, line_number=line_number
    # )

    pass


def _extract_content(data: Dict[str, Any]) -> str:
    """Extract text content from a message data dict.

    Claude Code messages store content either as a plain string or as
    an array of content blocks (each with a "type" and "text" field).
    We only extract text blocks, ignoring images and other types.

    Logic flow:
    1. Get raw_content = data.get("message", {}).get("content")
       - Also check data.get("content") as fallback
    2. If raw_content is a string: return it stripped
    3. If raw_content is a list:
       a. Filter for items where item.get("type") == "text"
       b. Extract item.get("text", "") from each
       c. Join with newline separator
       d. Return stripped result
    4. If raw_content is None or other type: return ""

    Args:
        data: Parsed JSON dict from a JSONL line.

    Returns:
        Extracted text content, empty string if none found.
    """
    # --- Get raw content field ---
    # raw_content = data.get("message", {}).get("content")
    # if raw_content is None:
    #     raw_content = data.get("content")

    # --- Handle string content ---
    # if isinstance(raw_content, str):
    #     return raw_content.strip()

    # --- Handle array of content blocks ---
    # if isinstance(raw_content, list):
    #     text_parts = [
    #         block.get("text", "")
    #         for block in raw_content
    #         if isinstance(block, dict) and block.get("type") == "text"
    #     ]
    #     return "\n".join(text_parts).strip()

    # --- Fallback: no content ---
    # return ""

    pass
