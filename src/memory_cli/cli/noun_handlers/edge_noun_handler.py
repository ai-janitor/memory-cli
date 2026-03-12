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

# from memory_cli.cli.entrypoint_and_argv_dispatch import register_noun
# from memory_cli.cli.output_envelope_json_and_text import Result


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
    pass


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
    pass


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
    pass


# =============================================================================
# NOUN REGISTRATION
# =============================================================================
_VERB_MAP = {
    "add": handle_add,
    "list": handle_list,
    "remove": handle_remove,
}

_VERB_DESCRIPTIONS = {
    "add": "Create a directed edge between two neurons",
    "list": "List edges (filtered by neuron, direction, type)",
    "remove": "Remove an edge between two neurons",
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
    pass

# --- Self-register on import ---
# register()
