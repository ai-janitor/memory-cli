# =============================================================================
# FILE: src/memory_cli/cli/scoped_handle_format_and_parse.py
# PURPOSE: Format and parse scoped neuron handles at the CLI boundary.
#          Handles are scope-prefixed IDs like LOCAL-42 or GLOBAL-42.
# RATIONALE: Internal storage uses bare integer IDs. The CLI layer adds scope
#            context so users and agents always know which store an ID refers to.
#            Scope is derived from the resolved DB path — ~/.memory/ is GLOBAL,
#            everything else is LOCAL (project-scoped or custom path).
# RESPONSIBILITY:
#   - format_handle(neuron_id, scope) -> "LOCAL-42" or "GLOBAL-42"
#   - parse_handle(handle) -> (scope_or_none, int_id)
#   - detect_scope(db_path) -> "LOCAL" or "GLOBAL"
#   - scope_neuron_id_fields(data, scope) -> data with id fields wrapped
# ORGANIZATION:
#   1. detect_scope — path-based scope detection
#   2. format_handle — int -> scoped string
#   3. parse_handle — scoped string -> (scope, int)
#   4. scope_neuron_id_fields — bulk-wrap id fields in dicts/lists
# =============================================================================

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union

_logger = logging.getLogger(__name__)


# =============================================================================
# SCOPE DETECTION — determine LOCAL or GLOBAL from DB path
# =============================================================================

def detect_scope(db_path: str) -> str:
    """Determine scope from the resolved DB path.

    Args:
        db_path: Absolute or ~-prefixed path to the SQLite database.

    Returns:
        "GLOBAL" if db_path is under ~/.memory/, "LOCAL" otherwise.

    Pseudo-logic:
    1. Expand ~ in db_path to get absolute path
    2. Expand ~ in "~/.memory/" to get the global store prefix
    3. If db_path starts with global prefix -> "GLOBAL"
    4. Otherwise -> "LOCAL"
    """
    expanded = os.path.expanduser(db_path)
    global_prefix = os.path.expanduser("~/.memory/")
    if expanded.startswith(global_prefix) or expanded == os.path.expanduser("~/.memory"):
        return "GLOBAL"
    return "LOCAL"


# =============================================================================
# FORMAT HANDLE — int ID -> scoped handle string
# =============================================================================

def format_handle(neuron_id: int, scope: str) -> str:
    """Format a bare integer neuron ID into a scoped handle string.

    Args:
        neuron_id: Integer neuron ID from storage.
        scope: "LOCAL" or "GLOBAL".

    Returns:
        Scoped handle string, e.g. "LOCAL-42" or "GLOBAL-42".

    Pseudo-logic:
    1. Validate scope is LOCAL or GLOBAL
    2. Return f"{scope}-{neuron_id}"
    """
    return f"{scope}-{neuron_id}"


# =============================================================================
# PARSE HANDLE — scoped handle string -> (scope, int ID)
# =============================================================================

# Regex: optional scope prefix (LOCAL/GLOBAL/L/G) followed by dash, then digits
_HANDLE_RE = re.compile(
    r"^(?:(LOCAL|GLOBAL|L|G)-)?(\d+)$",
    re.IGNORECASE,
)

# Regex: fingerprint-prefixed handle — 8 hex chars followed by colon, then digits
_FINGERPRINT_HANDLE_RE = re.compile(
    r"^([0-9a-fA-F]{8}):(\d+)$",
)

# Short-form to long-form scope mapping
_SCOPE_MAP = {
    "L": "LOCAL",
    "G": "GLOBAL",
    "LOCAL": "LOCAL",
    "GLOBAL": "GLOBAL",
}


def parse_handle(handle: str) -> Tuple[Optional[str], int]:
    """Parse a scoped handle string into (scope, integer_id).

    Args:
        handle: A string like "LOCAL-42", "L-42", "GLOBAL-42", "G-42", "42",
                or "a1b2c3d4:42" (fingerprint-prefixed).

    Returns:
        Tuple of (scope_or_none, int_id).
        scope is None for bare integer input, "LOCAL" or "GLOBAL" for prefixed,
        or an 8-char hex fingerprint string for fingerprint-prefixed handles.

    Raises:
        ValueError: If handle cannot be parsed.

    Pseudo-logic:
    1. Strip whitespace
    2. Try fingerprint prefix match: 8 hex chars + ":" + digits
    3. Try scope prefix match: optional (LOCAL|GLOBAL|L|G)- prefix + digits
    4. If no match -> raise ValueError
    5. Extract scope group and id group
    6. Map short scope (L/G) to long form (LOCAL/GLOBAL)
    7. Return (scope, int(id))
    """
    handle = handle.strip()

    # Try fingerprint-prefixed handle first (e.g., "a1b2c3d4:42")
    fm = _FINGERPRINT_HANDLE_RE.match(handle)
    if fm:
        fingerprint = fm.group(1).lower()
        nid = int(fm.group(2))
        return (fingerprint, nid)

    m = _HANDLE_RE.match(handle)
    if not m:
        raise ValueError(f"Invalid neuron handle: {handle!r}")
    scope_raw = m.group(1)
    nid = int(m.group(2))
    if scope_raw is None:
        return (None, nid)
    scope = _SCOPE_MAP[scope_raw.upper()]
    return (scope, nid)


# =============================================================================
# BULK FIELD WRAPPERS — apply scope to id fields in dicts and lists
# =============================================================================

def scope_neuron_dict(data: Dict[str, Any], scope: str) -> Dict[str, Any]:
    """Wrap the 'id' field of a neuron dict with scoped handle.

    Non-destructive: returns a shallow copy with 'id' replaced.

    Pseudo-logic:
    1. If data has 'id' key and it's an int -> replace with format_handle
    2. Return modified copy
    """
    if "id" not in data:
        return data
    out = dict(data)
    val = out["id"]
    if isinstance(val, int):
        out["id"] = format_handle(val, scope)
    return out


def scope_edge_dict(data: Dict[str, Any], scope: str) -> Dict[str, Any]:
    """Wrap source_id and target_id fields of an edge dict with scoped handles.

    Pseudo-logic:
    1. If source_id is int -> replace with format_handle
    2. If target_id is int -> replace with format_handle
    3. Return modified copy
    """
    out = dict(data)
    for key in ("source_id", "target_id"):
        val = out.get(key)
        if isinstance(val, int):
            out[key] = format_handle(val, scope)
    return out


def scope_neuron_id_value(data: Dict[str, Any], scope: str) -> Dict[str, Any]:
    """Wrap a 'neuron_id' field (used by attr/tag handlers) with scoped handle.

    Pseudo-logic:
    1. If data has 'neuron_id' key and it's an int -> replace with format_handle
    2. Return modified copy
    """
    if "neuron_id" not in data:
        return data
    out = dict(data)
    val = out["neuron_id"]
    if isinstance(val, int):
        out["neuron_id"] = format_handle(val, scope)
    return out


def scope_ref_map(ref_map: Dict[str, Any], scope: str) -> Dict[str, Any]:
    """Wrap values of a ref_map dict (ref_label -> neuron_id) with scoped handles.

    Pseudo-logic:
    1. For each key-value pair, if value is int -> replace with format_handle
    2. Return new dict
    """
    return {
        k: format_handle(v, scope) if isinstance(v, int) else v
        for k, v in ref_map.items()
    }


# =============================================================================
# LEAN FIELD FILTERING — strip to essential fields for default output
# =============================================================================

# Fields returned by default (lean mode)
_LEAN_NEURON_FIELDS = {"id", "content", "tags", "created_at", "source", "edges"}

# Additional fields exposed by search results (always shown regardless of verbose)
_SEARCH_EXTRA_FIELDS = {"score", "match_type", "hop_distance", "edge_reason",
                        "score_breakdown", "tag_affinity_depth"}


def lean_neuron_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Strip a neuron dict to lean fields: id, content, tags, created_at, source.

    Verbose fields (status, updated_at, project, attrs, embedding_updated_at)
    are removed. This reduces token cost for AI agent consumers.

    Args:
        data: Full neuron dict from storage layer.

    Returns:
        New dict with only lean fields.
    """
    return {k: v for k, v in data.items() if k in _LEAN_NEURON_FIELDS}


def lean_search_result(data: Dict[str, Any]) -> Dict[str, Any]:
    """Strip a search result dict to lean neuron fields plus search metadata.

    Keeps id, content, tags, created_at, source, and search-specific fields
    like score, match_type, hop_distance, edge_reason, score_breakdown.

    Args:
        data: Full search result dict.

    Returns:
        New dict with only lean + search fields.
    """
    allowed = _LEAN_NEURON_FIELDS | _SEARCH_EXTRA_FIELDS
    return {k: v for k, v in data.items() if k in allowed}


# =============================================================================
# CONNECTION ROUTING — resolve a DB connection matching a handle's scope prefix
# =============================================================================

def _is_fingerprint_scope(scope: str) -> bool:
    """Check if a scope string is a fingerprint (8 hex chars) vs LOCAL/GLOBAL.

    Args:
        scope: Scope string from parse_handle().

    Returns:
        True if scope looks like an 8-char hex fingerprint, False otherwise.
    """
    return len(scope) == 8 and all(c in "0123456789abcdef" for c in scope)


def resolve_connection_by_scope(handle_scope: str, connections: List[Tuple[Any, str]]) -> Optional[Tuple[Any, str]]:
    """Resolve a DB connection from the connections list matching handle_scope.

    Shared routing utility used by all noun handlers. Given a handle scope
    (LOCAL, GLOBAL, or 8-char hex fingerprint), finds the matching (conn, scope)
    pair from the available connections list.

    Args:
        handle_scope: Scope string from parse_handle() — "LOCAL", "GLOBAL",
                      or an 8-char hex fingerprint string.
        connections: List of (conn, scope_str) tuples from get_layered_connections().

    Returns:
        (conn, scope) tuple if a match is found, None otherwise.

    Pseudo-logic:
    1. If handle_scope is NOT a fingerprint (i.e. LOCAL or GLOBAL):
       a. Iterate connections; return first where scope == handle_scope
       b. If none match, return None
    2. If handle_scope IS a fingerprint:
       a. For each connection, call get_fingerprint(conn)
          - ValueError: log DEBUG (expected — store has no fingerprint), skip
          - Other exception: log WARNING with traceback, skip
       b. Return the (conn, scope) whose store fingerprint matches handle_scope
       c. If none match, return None
    """
    if not _is_fingerprint_scope(handle_scope):
        # Standard LOCAL/GLOBAL routing
        for conn, scope in connections:
            if scope == handle_scope:
                return conn, scope
        return None

    # Fingerprint routing — check each store's fingerprint
    from memory_cli.db.store_fingerprint_read_and_cache import get_fingerprint
    for conn, scope in connections:
        try:
            store_fp = get_fingerprint(conn)
            if store_fp == handle_scope:
                return conn, scope
        except ValueError:
            # No fingerprint in this store's meta table — expected for
            # un-initialised stores. Skip and try the next connection.
            _logger.debug(
                "Store %s has no fingerprint in meta table, skipping",
                scope,
            )
            continue
        except Exception:
            # Unexpected error (DB corruption, connection failure, etc.).
            # Log with traceback so the caller has diagnostic info, then
            # skip this store rather than crashing the entire lookup.
            _logger.warning(
                "Fingerprint lookup failed for store %s during handle routing",
                scope,
                exc_info=True,
            )
            continue
    return None


def scope_list(items: List[Dict[str, Any]], scope: str, kind: str = "neuron") -> List[Dict[str, Any]]:
    """Apply scope to a list of dicts based on kind.

    Args:
        items: List of dicts to scope.
        scope: "LOCAL" or "GLOBAL".
        kind: "neuron" (wrap 'id'), "edge" (wrap source_id/target_id),
              "neuron_id" (wrap 'neuron_id').

    Returns:
        New list with scoped dicts.
    """
    if kind == "neuron":
        return [scope_neuron_dict(item, scope) for item in items]
    elif kind == "edge":
        return [scope_edge_dict(item, scope) for item in items]
    elif kind == "neuron_id":
        return [scope_neuron_id_value(item, scope) for item in items]
    return items
