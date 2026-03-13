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

import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union


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
        handle: A string like "LOCAL-42", "L-42", "GLOBAL-42", "G-42", or "42".

    Returns:
        Tuple of (scope_or_none, int_id).
        scope is None for bare integer input, "LOCAL" or "GLOBAL" for prefixed.

    Raises:
        ValueError: If handle cannot be parsed.

    Pseudo-logic:
    1. Strip whitespace
    2. Match against regex: optional (LOCAL|GLOBAL|L|G)- prefix + digits
    3. If no match -> raise ValueError
    4. Extract scope group (may be None for bare int) and id group
    5. Map short scope (L/G) to long form (LOCAL/GLOBAL)
    6. Return (scope, int(id))
    """
    handle = handle.strip()
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
