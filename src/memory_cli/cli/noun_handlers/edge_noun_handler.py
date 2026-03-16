# =============================================================================
# FILE: src/memory_cli/cli/noun_handlers/edge_noun_handler.py
# PURPOSE: Register the "edge" noun with the CLI dispatch registry.
#          Edges are directed, typed connections between neurons in the graph.
# RATIONALE: Edges form the graph structure. They connect neurons with typed
#            relationships (e.g., "related_to", "derived_from", "contradicts").
#            Three verbs: add, list, remove. Edges are always between two
#            neurons with a relationship type.
# RESPONSIBILITY:
#   - Define verb map: add, list, remove
#   - Define flag/arg specs for each verb
#   - Register with entrypoint dispatch via register_noun()
#   - Each verb handler: parse args, validate, call storage, return Result
# ORGANIZATION:
#   1. Verb handler stubs
#   2. Noun registration at module level
# =============================================================================

from __future__ import annotations

from typing import List, Any

from memory_cli.cli.entrypoint_and_argv_dispatch import register_noun


# =============================================================================
# VERB: add — create a directed edge between two neurons
# =============================================================================
def handle_add(args: List[str], global_flags: Any) -> Any:
    """Create a directed edge from source neuron to target neuron.

    Args:
        args: [source_id, target_id, --type <rel_type>, --weight <float>]
        global_flags: Parsed global flags.

    Returns:
        Result confirming edge created.

    Pseudo-logic:
    1. Parse positional args: source_id, target_id (both required)
    2. Parse optional flags:
       - --type <rel_type>: relationship type (default "related_to")
       - --weight <float>: edge weight for activation spreading (default 1.0)
    3. Validate: both neurons must exist
    4. Validate: no self-edges (source_id != target_id)
    5. Delegate to storage: edge_store.create(source_id, target_id, type, weight)
    6. Handle duplicate edge: upsert (update weight/type) or error (TBD)
    7. Return Result(status="ok", data={"source": s, "target": t, "type": type, "weight": w})
    8. If either neuron not found: Result(status="not_found", error="Neuron {id} not found")
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_layered_connections
    from memory_cli.cli.noun_handlers.arg_parse_extract_positional_and_flags import (
        require_positional, extract_flag,
    )
    from memory_cli.cli.scoped_handle_format_and_parse import (
        parse_handle, scope_edge_dict, resolve_connection_by_scope,
    )
    try:
        source_raw, rest = require_positional(list(args), "source_id")
        target_raw, rest = require_positional(rest, "target_id")
        handle_scope_s, source_id = parse_handle(source_raw)
        handle_scope_t, target_id = parse_handle(target_raw)
        # Use scope from either ID (both must be in the same store)
        handle_scope = handle_scope_s or handle_scope_t
        reason, rest = extract_flag(rest, "--type", default=None)
        weight, rest = extract_flag(rest, "--weight", type_fn=float, default=None)
        # If --type was not provided, check for an optional 3rd positional arg as reason
        if reason is None and rest and not rest[0].startswith("--"):
            reason = rest.pop(0)
        if reason is None:
            reason = "related_to"
        # Route by handle scope; default to first (local-preferred) connection
        connections = get_layered_connections(global_flags)
        conn, scope = connections[0]
        if handle_scope is not None:
            match = resolve_connection_by_scope(handle_scope, connections)
            if match is not None:
                conn, scope = match
            else:
                return Result(status="not_found", error=f"No {handle_scope} store available")
        from memory_cli.edge import edge_add
        result = edge_add(conn, source_id, target_id, reason=reason, weight=weight)
        conn.commit()
        return Result(status="ok", data=scope_edge_dict(result, scope))
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: list — list edges for a neuron or between two neurons
# =============================================================================
def handle_list(args: List[str], global_flags: Any) -> Any:
    """List edges, filtered by neuron, direction, or type.

    Args:
        args: [--neuron <id>, --direction <in|out|both>, --type <rel_type>]
        global_flags: Parsed global flags.

    Returns:
        Result with list of edge dicts.

    Pseudo-logic:
    1. Parse optional flags:
       - --neuron <id>: show edges for this neuron (required unless listing all)
       - --direction <in|out|both>: filter by edge direction (default "both")
       - --type <rel_type>: filter by relationship type
       - --limit <N>: max results (default 50)
       - --offset <N>: skip first N (default 0)
    2. If --neuron provided:
       a. Validate neuron exists
       b. Delegate: edge_store.list_for_neuron(id, direction, type)
    3. If no --neuron:
       a. List all edges (with optional type filter)
    4. Return Result(status="ok", data=edge_list, meta=pagination)
    5. Empty list is success (exit 0)
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_layered_connections
    from memory_cli.cli.noun_handlers.arg_parse_extract_positional_and_flags import extract_flag
    from memory_cli.cli.scoped_handle_format_and_parse import (
        parse_handle, scope_list, resolve_connection_by_scope,
    )
    try:
        rest = list(args)
        neuron_id_raw, rest = extract_flag(rest, "--neuron")
        direction, rest = extract_flag(rest, "--direction", default="both")
        limit, rest = extract_flag(rest, "--limit", type_fn=int, default=50)
        offset, rest = extract_flag(rest, "--offset", type_fn=int, default=0)
        if neuron_id_raw is None:
            return Result(status="error", error="--neuron <id> is required for edge list")
        handle_scope, neuron_id = parse_handle(neuron_id_raw)
        # Resolve connections; if handle has explicit scope, route to that store only
        connections = get_layered_connections(global_flags)
        if handle_scope is not None:
            match = resolve_connection_by_scope(handle_scope, connections)
            if match is None:
                return Result(status="not_found", error=f"No {handle_scope} store available for {neuron_id_raw}")
            connections = [match]
        from memory_cli.edge import edge_list
        # Map CLI direction names to internal names
        dir_map = {"in": "incoming", "out": "outgoing", "both": "both",
                    "incoming": "incoming", "outgoing": "outgoing"}
        direction = dir_map.get(direction, direction)
        all_edges = []
        for conn, scope in connections:
            edges = edge_list(conn, neuron_id, direction=direction, limit=limit, offset=offset)
            all_edges.extend(scope_list(edges, scope, "edge"))
        return Result(status="ok", data=all_edges, meta={"limit": limit, "offset": offset})
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: remove — delete an edge between two neurons
# =============================================================================
def handle_remove(args: List[str], global_flags: Any) -> Any:
    """Remove an edge between two neurons.

    Args:
        args: [source_id, target_id, --type <rel_type>]
        global_flags: Parsed global flags.

    Returns:
        Result confirming edge removed.

    Pseudo-logic:
    1. Parse positional args: source_id, target_id (both required)
    2. Parse optional flag: --type <rel_type> (if multiple edges between same pair)
    3. Delegate to storage: edge_store.remove(source_id, target_id, type)
    4. If edge not found: Result(status="not_found", error="Edge not found")
    5. Return Result(status="ok", data={"source": s, "target": t, "removed": True})
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_layered_connections
    from memory_cli.cli.noun_handlers.arg_parse_extract_positional_and_flags import require_positional
    from memory_cli.cli.scoped_handle_format_and_parse import parse_handle, resolve_connection_by_scope
    try:
        source_raw, rest = require_positional(list(args), "source_id")
        target_raw, rest = require_positional(rest, "target_id")
        handle_scope_s, source_id = parse_handle(source_raw)
        handle_scope_t, target_id = parse_handle(target_raw)
        # Use scope from either ID (both must be in the same store)
        handle_scope = handle_scope_s or handle_scope_t
        # Route by handle scope; default to first (local-preferred) connection
        connections = get_layered_connections(global_flags)
        conn, scope = connections[0]
        if handle_scope is not None:
            match = resolve_connection_by_scope(handle_scope, connections)
            if match is not None:
                conn, scope = match
            else:
                return Result(status="not_found", error=f"No {handle_scope} store available")
        from memory_cli.edge import edge_remove
        result = edge_remove(conn, source_id, target_id)
        conn.commit()
        return Result(status="ok", data=result)
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: splice — atomically insert a neuron between an existing edge
# =============================================================================
def handle_splice(args: List[str], global_flags: Any) -> Any:
    """Splice a neuron into an existing edge: A->B becomes A->C->B.

    Args:
        args: [source_id, target_id, --through <middle_id>,
               --type-ac <text>, --type-cb <text>,
               --weight-ac <float>, --weight-cb <float>]
        global_flags: Parsed global flags.

    Returns:
        Result with removed_edge, edge_a_c, edge_c_b.
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_layered_connections
    from memory_cli.cli.noun_handlers.arg_parse_extract_positional_and_flags import (
        require_positional, extract_flag,
    )
    from memory_cli.cli.scoped_handle_format_and_parse import (
        parse_handle, resolve_connection_by_scope,
    )
    try:
        source_raw, rest = require_positional(list(args), "source_id")
        target_raw, rest = require_positional(rest, "target_id")
        handle_scope_s, source_id = parse_handle(source_raw)
        handle_scope_t, target_id = parse_handle(target_raw)
        handle_scope = handle_scope_s or handle_scope_t
        through_raw, rest = extract_flag(rest, "--through")
        if through_raw is None:
            return Result(status="error", error="--through <neuron_id> is required for edge splice")
        handle_scope_m, through_id = parse_handle(through_raw)
        handle_scope = handle_scope or handle_scope_m
        reason_ac, rest = extract_flag(rest, "--type-ac", default=None)
        reason_cb, rest = extract_flag(rest, "--type-cb", default=None)
        weight_ac, rest = extract_flag(rest, "--weight-ac", type_fn=float, default=None)
        weight_cb, rest = extract_flag(rest, "--weight-cb", type_fn=float, default=None)
        connections = get_layered_connections(global_flags)
        conn, scope = connections[0]
        if handle_scope is not None:
            match = resolve_connection_by_scope(handle_scope, connections)
            if match is not None:
                conn, scope = match
            else:
                return Result(status="not_found", error=f"No {handle_scope} store available")
        from memory_cli.edge import edge_splice
        result = edge_splice(
            conn, source_id, target_id, through_id,
            reason_a_c=reason_ac, reason_c_b=reason_cb,
            weight_a_c=weight_ac, weight_c_b=weight_cb,
        )
        conn.commit()
        return Result(status="ok", data=result)
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: update — modify fields on an existing edge
# =============================================================================
def handle_update(args: List[str], global_flags: Any) -> Any:
    """Update reason/weight on an existing edge.

    Args:
        args: [source_id, target_id, --type <text>, --weight <float>]
        global_flags: Parsed global flags.

    Returns:
        Result with updated edge record.
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_layered_connections
    from memory_cli.cli.noun_handlers.arg_parse_extract_positional_and_flags import (
        require_positional, extract_flag,
    )
    from memory_cli.cli.scoped_handle_format_and_parse import (
        parse_handle, resolve_connection_by_scope,
    )
    try:
        source_raw, rest = require_positional(list(args), "source_id")
        target_raw, rest = require_positional(rest, "target_id")
        handle_scope_s, source_id = parse_handle(source_raw)
        handle_scope_t, target_id = parse_handle(target_raw)
        handle_scope = handle_scope_s or handle_scope_t
        reason, rest = extract_flag(rest, "--type", default=None)
        weight, rest = extract_flag(rest, "--weight", type_fn=float, default=None)
        connections = get_layered_connections(global_flags)
        conn, scope = connections[0]
        if handle_scope is not None:
            match = resolve_connection_by_scope(handle_scope, connections)
            if match is not None:
                conn, scope = match
            else:
                return Result(status="not_found", error=f"No {handle_scope} store available")
        from memory_cli.edge import edge_update
        result = edge_update(conn, source_id, target_id, reason=reason, weight=weight)
        conn.commit()
        return Result(status="ok", data=result)
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# NOUN REGISTRATION
# =============================================================================
_VERB_MAP = {
    "add": handle_add,
    "list": handle_list,
    "remove": handle_remove,
    "splice": handle_splice,
    "update": handle_update,
}

_VERB_DESCRIPTIONS = {
    "add": "Create a directed edge between two neurons",
    "list": "List edges (filtered by neuron, direction, type)",
    "remove": "Remove an edge between two neurons",
    "splice": "Insert a neuron between an existing edge (A->B becomes A->C->B)",
    "update": "Update reason/weight on an existing edge",
}

_FLAG_DEFS = {
    "add": [
        {"name": "--type", "type": "str", "default": "related_to", "desc": "Relationship type"},
        {"name": "--weight", "type": "float", "default": 1.0, "desc": "Edge weight"},
    ],
    "list": [
        {"name": "--neuron", "type": "str", "default": None, "desc": "Filter by neuron ID"},
        {"name": "--direction", "type": "str", "default": "both", "desc": "in, out, or both"},
        {"name": "--type", "type": "str", "default": None, "desc": "Filter by relationship type"},
        {"name": "--limit", "type": "int", "default": 50, "desc": "Max results"},
        {"name": "--offset", "type": "int", "default": 0, "desc": "Skip first N"},
    ],
    "remove": [
        {"name": "--type", "type": "str", "default": None, "desc": "Relationship type (if ambiguous)"},
    ],
    "splice": [
        {"name": "--through", "type": "str", "default": None, "desc": "Neuron ID to insert between (required)"},
        {"name": "--type-ac", "type": "str", "default": None, "desc": "Reason for A->C edge (default: inherit)"},
        {"name": "--type-cb", "type": "str", "default": None, "desc": "Reason for C->B edge (default: inherit)"},
        {"name": "--weight-ac", "type": "float", "default": None, "desc": "Weight for A->C edge (default: inherit)"},
        {"name": "--weight-cb", "type": "float", "default": None, "desc": "Weight for C->B edge (default: inherit)"},
    ],
    "update": [
        {"name": "--type", "type": "str", "default": None, "desc": "New relationship type/reason"},
        {"name": "--weight", "type": "float", "default": None, "desc": "New edge weight"},
    ],
}


def register() -> None:
    """Register the edge noun with the CLI dispatch registry.

    Pseudo-logic:
    1. Call register_noun("edge", {
         "verb_map": _VERB_MAP,
         "description": "Edges — directed connections between neurons",
         "verb_descriptions": _VERB_DESCRIPTIONS,
         "flag_defs": _FLAG_DEFS,
       })
    """
    register_noun("edge", {
        "verb_map": _VERB_MAP,
        "description": "Edges — directed connections between neurons",
        "verb_descriptions": _VERB_DESCRIPTIONS,
        "flag_defs": _FLAG_DEFS,
    })

# --- Self-register on import ---
register()
