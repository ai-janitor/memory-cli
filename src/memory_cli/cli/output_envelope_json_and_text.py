# =============================================================================
# FILE: src/memory_cli/cli/output_envelope_json_and_text.py
# PURPOSE: Format handler results into the JSON envelope or plain text output.
#          Handle stdout vs stderr routing and ANSI detection.
# RATIONALE: Uniform output contract — every response is wrapped in
#            {"status", "data", "error", "meta"} for JSON, or a human-readable
#            text block. Callers (scripts, agents) always know the shape.
# RESPONSIBILITY:
#   - Build JSON envelope: {"status": str, "data": Any, "error": str|null, "meta": dict|null}
#   - Build plain text representation of the same data
#   - Add pagination meta for list results: {"total": N, "limit": N, "offset": N}
#   - Route data to stdout, diagnostics/warnings to stderr
#   - Detect TTY for ANSI coloring in text mode (no ANSI in JSON ever)
#   - Handle serialization edge cases (dates, bytes, custom types)
# ORGANIZATION:
#   1. Result dataclass — internal result object from handlers
#   2. format_output() — main formatting function
#   3. _build_json_envelope() — JSON mode
#   4. _build_text_output() — text mode
#   5. write_output() — route to correct stream
#   6. _is_tty() — ANSI detection helper
# =============================================================================

from __future__ import annotations

import base64
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, TextIO


# =============================================================================
# RESULT DATACLASS — handler return type
# =============================================================================
@dataclass
class Result:
    """Standardized result object returned by all noun/verb handlers.

    Attributes:
        status: "ok", "not_found", or "error"
        data: Payload — dict, list, or None
        error: Error message string or None
        meta: Optional metadata dict (pagination, timing, etc.)
    """
    status: str = "ok"
    data: Any = None
    error: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


# =============================================================================
# MAIN FORMATTING FUNCTION
# =============================================================================
def format_output(result: Result, output_format: str = "json") -> str:
    """Format a Result object into the requested output format.

    Args:
        result: The Result object from a handler.
        output_format: "json" or "text".

    Returns:
        Formatted string ready to be written to a stream.

    Pseudo-logic:
    1. Validate output_format is "json" or "text"
       - If invalid, fall back to "json" (safe default for agents)
    2. If output_format == "json":
       - Call _build_json_envelope(result)
    3. If output_format == "text":
       - Call _build_text_output(result)
    4. Return the formatted string
    """
    if output_format not in ("json", "text"):
        output_format = "json"
    if output_format == "text":
        return _build_text_output(result)
    return _build_json_envelope(result)


# =============================================================================
# JSON ENVELOPE BUILDER
# =============================================================================
def _build_json_envelope(result: Result) -> str:
    """Build the JSON envelope string from a Result.

    Returns:
        JSON string with keys: status, data, error, meta.

    Pseudo-logic:
    1. Build dict: {
         "status": result.status,
         "data": result.data,
         "error": result.error,
         "meta": result.meta
       }
    2. Serialize with json.dumps():
       - indent=2 for readability
       - ensure_ascii=False for unicode support
       - default=_json_serializer for custom types (dates, etc.)
    3. No ANSI codes ever in JSON output
    4. Return the JSON string
    """
    envelope = {
        "status": result.status,
        "data": result.data,
        "error": result.error,
        "meta": result.meta,
    }
    return json.dumps(envelope, indent=2, ensure_ascii=False, default=_json_serializer)


# =============================================================================
# PLAIN TEXT BUILDER
# =============================================================================
def _build_text_output(result: Result) -> str:
    """Build plain text representation of a Result.

    Returns:
        Human-readable text string.

    Pseudo-logic:
    1. If result.status == "error":
       - Return "Error: {result.error}"
    2. If result.status == "not_found":
       - Return "Not found." or "Not found: {result.error}" if error has detail
    3. If result.data is None:
       - Return "OK" (success with no data)
    4. If result.data is a list:
       a. If empty: return "No results." (still success, exit 0)
       b. Detect noun type from item shape and dispatch to noun-aware formatter
       c. If result.meta has pagination: append "(showing {offset+1}-{offset+len} of {total})"
    5. If result.data is a dict:
       a. Detect noun type from dict shape and dispatch to noun-aware formatter
    6. Return assembled string
    """
    if result.status == "error":
        return f"Error: {result.error}"

    if result.status == "not_found":
        if result.error:
            return f"Not found: {result.error}"
        return "Not found."

    if result.data is None:
        return "OK"

    # --- List data: detect item type and format each item ---
    if isinstance(result.data, list):
        if not result.data:
            return "No results."
        lines = []
        for item in result.data:
            if isinstance(item, dict):
                lines.append(_format_dict_item(item, result.meta))
            else:
                # Plain string items (e.g., tag names for a neuron's tags)
                lines.append(str(item))
        if result.meta and "total" in result.meta:
            offset = result.meta.get("offset", 0)
            total = result.meta["total"]
            count = len(result.data)
            lines.append(f"(showing {offset + 1}-{offset + count} of {total})")
        return "\n".join(lines)

    # --- Dict data: detect noun type and format ---
    if isinstance(result.data, dict):
        return _format_single_dict(result.data, result.meta)

    return str(result.data)


# =============================================================================
# NOUN-AWARE TEXT FORMATTERS — dispatch by data shape detection
# =============================================================================

def _format_dict_item(item: Dict[str, Any], meta: Optional[Dict[str, Any]]) -> str:
    """Detect the noun type of a dict item and dispatch to the right formatter.

    Shape detection heuristics:
    - Has "score" + "match_type" -> search result
    - Has "content" + "id" + "tags" -> neuron
    - Has "source_id" + "target_id" -> edge
    - Has "id" + "name" + no "content" -> tag registry entry
    - Fallback -> generic key: value format
    """
    if "score" in item and "match_type" in item:
        return _format_neuron_search(item)
    if "content" in item and "id" in item:
        return _format_neuron(item)
    if "source_id" in item and "target_id" in item:
        return _format_edge(item)
    if "id" in item and "name" in item and "content" not in item:
        return _format_tag_registry(item)
    # Fallback: generic key=value one-liner
    return "  ".join(f"{k}: {v}" for k, v in item.items())


def _format_single_dict(data: Dict[str, Any], meta: Optional[Dict[str, Any]]) -> str:
    """Detect noun type for a single dict result and format.

    Shape detection:
    - Has "db_path" + "neuron_count" -> meta stats
    - Has "db_path" + "schema_version" + no "neuron_count" -> meta info
    - Has "content" + "id" + "tags" -> single neuron (neuron get)
    - Fallback -> generic key: value lines
    """
    if "db_path" in data and "neuron_count" in data:
        return _format_meta_stats(data)
    if "db_path" in data and "schema_version" in data:
        return _format_meta_info(data)
    if "content" in data and "id" in data:
        return _format_neuron(data)
    # Fallback: generic key: value lines (handles attrs dict, confirmation dicts, etc.)
    lines = [f"{k}: {v}" for k, v in data.items() if v is not None]
    return "\n".join(lines) if lines else "OK"


# =============================================================================
# NEURON FORMATTER — neuron get / neuron list
# =============================================================================
def _format_neuron(d: Dict[str, Any]) -> str:
    """Format a neuron dict for compact text display.

    Output:
        [1] The deploy script lives in scripts/deploy.sh
            project: memory-cli | active
            tags: 2026-03-12, memory-cli
            attrs: priority=high
            created: 2026-03-12T13:25:36

    Pseudo-logic:
    - Line 1: [id] content (truncated to first line if multiline)
    - Line 2: project + status (suppress if both empty)
    - Line 3: tags (suppress if empty)
    - Line 4: attrs (suppress if empty)
    - Line 5: created timestamp (epoch ms -> ISO 8601)
    - Suppress updated line when same as created
    - Suppress source, embedding_updated_at when null/empty
    """
    nid = d.get("id", "?")
    content = str(d.get("content", "")).strip()
    # Truncate to first line for list display
    first_line = content.split("\n")[0] if content else ""
    lines = [f"[{nid}] {first_line}"]

    # Project + status line
    project = d.get("project")
    status = d.get("status", "active")
    parts = []
    if project:
        parts.append(f"project: {project}")
    if status:
        parts.append(status)
    if parts:
        lines.append("    " + " | ".join(parts))

    # Source line (suppress if null/empty)
    source = d.get("source")
    if source:
        lines.append(f"    source: {source}")

    # Tags line (suppress if empty)
    tags = d.get("tags")
    if tags and isinstance(tags, list) and len(tags) > 0:
        lines.append("    tags: " + ", ".join(str(t) for t in tags))

    # Attrs line (suppress if empty)
    attrs = d.get("attrs")
    if attrs and isinstance(attrs, dict) and len(attrs) > 0:
        attr_parts = [f"{k}={v}" for k, v in attrs.items()]
        lines.append("    attrs: " + ", ".join(attr_parts))

    # Created timestamp (epoch ms -> ISO 8601)
    created = d.get("created_at")
    if created is not None:
        lines.append(f"    created: {_ms_to_iso(created)}")

    # Updated timestamp — suppress if same as created
    updated = d.get("updated_at")
    if updated is not None and updated != created:
        lines.append(f"    updated: {_ms_to_iso(updated)}")

    return "\n".join(lines)


# =============================================================================
# NEURON SEARCH FORMATTER — neuron search results with scores
# =============================================================================
def _format_neuron_search(d: Dict[str, Any]) -> str:
    """Format a search result for compact text display.

    Output:
        [1] (score: 0.40) Deploy script is at scripts/deploy.sh
            match: fan_out (hop 1, via: deploys_with)
            tags: 2026-03-12, memory-cli

    Pseudo-logic:
    - Line 1: [id] (score: X.XX) content first line
    - Line 2: match type + hop distance + edge reason
    - Line 3: tags (suppress if empty)
    """
    nid = d.get("id", "?")
    score = d.get("score", 0.0)
    content = str(d.get("content", "")).strip()
    first_line = content.split("\n")[0] if content else ""
    lines = [f"[{nid}] (score: {score:.2f}) {first_line}"]

    # Match info line
    match_type = d.get("match_type", "direct_match")
    hop = d.get("hop_distance", 0)
    edge_reason = d.get("edge_reason")
    match_parts = [match_type]
    if hop > 0:
        match_parts.append(f"hop {hop}")
    if edge_reason:
        match_parts.append(f"via: {edge_reason}")
    if len(match_parts) > 1:
        lines.append(f"    match: {match_parts[0]} ({', '.join(match_parts[1:])})")
    else:
        lines.append(f"    match: {match_parts[0]}")

    # Tags line (suppress if empty)
    tags = d.get("tags")
    if tags and isinstance(tags, list) and len(tags) > 0:
        lines.append("    tags: " + ", ".join(str(t) for t in tags))

    return "\n".join(lines)


# =============================================================================
# EDGE FORMATTER — edge list
# =============================================================================
def _format_edge(d: Dict[str, Any]) -> str:
    """Format an edge dict for compact text display.

    Output:
        1 -> 2  deploys_with  (weight: 1.0)
            snippet: CI runs on GitLab with .gitlab-ci.yml

    Pseudo-logic:
    - Line 1: source -> target  reason  (weight: W)
    - Line 2: snippet of connected neuron content (suppress if empty)
    """
    src = d.get("source_id", "?")
    tgt = d.get("target_id", "?")
    reason = d.get("reason", "related_to")
    weight = d.get("weight")
    weight_str = f"  (weight: {weight})" if weight is not None else ""
    lines = [f"{src} -> {tgt}  {reason}{weight_str}"]

    snippet = d.get("connected_neuron_snippet")
    if snippet:
        lines.append(f"    snippet: {snippet}")

    return "\n".join(lines)


# =============================================================================
# TAG REGISTRY FORMATTER — tag list (all tags)
# =============================================================================
def _format_tag_registry(d: Dict[str, Any]) -> str:
    """Format a tag registry entry for compact text display.

    Output:
        [1] 2026-03-12

    Pseudo-logic:
    - [id] name
    """
    tid = d.get("id", "?")
    name = d.get("name", "")
    return f"[{tid}] {name}"


# =============================================================================
# META INFO FORMATTER — meta info (aligned key-value)
# =============================================================================
def _format_meta_info(d: Dict[str, Any]) -> str:
    """Format meta info dict for compact aligned display.

    Output:
        db_path:    /Users/hung/.memory/memory.db
        schema:     1
        model:      /Users/hung/.memory/models/default.gguf
        dimensions: 768

    Pseudo-logic:
    - Map internal keys to display labels
    - Align values using fixed-width label column
    - Suppress null values
    """
    label_map = [
        ("db_path", "db_path"),
        ("schema_version", "schema"),
        ("embedding_model", "model"),
        ("embedding_dimensions", "dimensions"),
    ]
    lines = []
    # Find max label width for alignment
    max_label = max(len(label) for _, label in label_map)
    for key, label in label_map:
        val = d.get(key)
        if val is not None:
            lines.append(f"{label + ':':<{max_label + 1}} {val}")
    return "\n".join(lines)


# =============================================================================
# META STATS FORMATTER — meta stats (compact summary)
# =============================================================================
def _format_meta_stats(d: Dict[str, Any]) -> str:
    """Format meta stats dict for compact aligned display.

    Output:
        neurons:    3 (3 active, 0 archived)
        vectors:    0 (3 never embedded)
        tags:       4
        edges:      1
        db size:    164 KB

    Pseudo-logic:
    - Compute active/archived from neuron_count and counts
    - Format db_size_bytes to human-readable
    - Align values using fixed-width label column
    """
    neuron_count = d.get("neuron_count", 0)
    vector_count = d.get("vector_count", 0)
    never_embedded = d.get("never_embedded_count", 0)
    tag_count = d.get("tag_count", 0)
    edge_count = d.get("edge_count", 0)
    db_size = d.get("db_size_bytes", 0)

    # Active = total - archived; archived = total - (vector + never_embedded) is not exact,
    # so we just report what we have. neuron_count is total.
    # The stats dict doesn't have active/archived counts directly, so we derive:
    # active = neuron_count (we don't have archived_neuron_count in the stats dict)
    # Let's just show the raw counts with detail.

    lines = []
    # Neurons line with detail
    neuron_detail = f"{neuron_count}"
    lines.append(f"{'neurons:':<12}{neuron_detail}")

    # Vectors line with detail
    vec_parts = [str(vector_count)]
    if never_embedded > 0:
        vec_parts.append(f"{never_embedded} never embedded")
    if vector_count > 0 and never_embedded > 0:
        lines.append(f"{'vectors:':<12}{vector_count} ({never_embedded} never embedded)")
    elif never_embedded > 0:
        lines.append(f"{'vectors:':<12}{vector_count} ({never_embedded} never embedded)")
    else:
        lines.append(f"{'vectors:':<12}{vector_count}")

    # Tags and edges
    lines.append(f"{'tags:':<12}{tag_count}")
    lines.append(f"{'edges:':<12}{edge_count}")

    # DB size in human-readable format
    lines.append(f"{'db size:':<12}{_human_bytes(db_size)}")

    # Drift warning if detected
    if d.get("drift_detected"):
        lines.append(f"{'WARNING:':<12}model drift detected")

    return "\n".join(lines)


# =============================================================================
# HELPERS — timestamp conversion, byte formatting
# =============================================================================
def _ms_to_iso(ms_or_value: Any) -> str:
    """Convert epoch milliseconds to ISO 8601 string.

    If the value is already a string (ISO format), return as-is.
    If the value is an int/float (epoch ms), convert to ISO 8601.

    Pseudo-logic:
    1. If string -> return as-is (already formatted)
    2. If int/float -> divide by 1000, convert to datetime, format ISO 8601
    3. Fallback -> str(value)
    """
    if isinstance(ms_or_value, str):
        return ms_or_value
    if isinstance(ms_or_value, (int, float)):
        try:
            dt = datetime.fromtimestamp(ms_or_value / 1000.0)
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except (OSError, OverflowError, ValueError):
            return str(ms_or_value)
    return str(ms_or_value)


def _human_bytes(n: int) -> str:
    """Format byte count to human-readable string (KB, MB, GB).

    Pseudo-logic:
    1. If < 1024 -> "{n} B"
    2. If < 1024*1024 -> "{n/1024:.0f} KB"
    3. If < 1024^3 -> "{n/1024^2:.1f} MB"
    4. Else -> "{n/1024^3:.1f} GB"
    """
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n // 1024} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.1f} GB"


# =============================================================================
# OUTPUT WRITER — stdout/stderr routing
# =============================================================================
def write_output(formatted: str, stream: Optional[TextIO] = None) -> None:
    """Write formatted output to the appropriate stream.

    Args:
        formatted: The formatted string from format_output().
        stream: Override stream. Default is sys.stdout.

    Pseudo-logic:
    1. If stream is None, use sys.stdout
    2. Write formatted string to stream
    3. Ensure trailing newline
    4. Flush the stream (important for piped output)
    """
    if stream is None:
        stream = sys.stdout
    if not formatted.endswith("\n"):
        formatted = formatted + "\n"
    stream.write(formatted)
    stream.flush()


def write_error(message: str) -> None:
    """Write a diagnostic or warning message to stderr.

    Args:
        message: The message to write.

    Pseudo-logic:
    1. Write to sys.stderr
    2. Prefix with "memory: " for identification in logs
    3. Ensure trailing newline
    4. Flush stderr
    """
    line = f"memory: {message}"
    if not line.endswith("\n"):
        line = line + "\n"
    sys.stderr.write(line)
    sys.stderr.flush()


# =============================================================================
# HELPERS
# =============================================================================
def _is_tty() -> bool:
    """Check if stdout is a TTY (for ANSI color decisions).

    Returns:
        True if stdout is connected to a terminal.

    Pseudo-logic:
    1. Return sys.stdout.isatty()
    2. Wrapped in try/except for edge cases (detached stdout, etc.)
    """
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def _json_serializer(obj: Any) -> Any:
    """Custom JSON serializer for types that json.dumps can't handle.

    Pseudo-logic:
    1. If datetime: return ISO 8601 string
    2. If bytes: return base64-encoded string
    3. If Path: return str(obj)
    4. Else: raise TypeError (let json.dumps report it)
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
