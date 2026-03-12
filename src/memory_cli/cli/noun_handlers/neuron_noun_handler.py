# =============================================================================
# FILE: src/memory_cli/cli/noun_handlers/neuron_noun_handler.py
# PURPOSE: Register the "neuron" noun with the CLI dispatch registry.
#          Neurons are the primary memory unit — content nodes in the graph.
# RATIONALE: Neuron is the core entity. It supports the most verbs because
#            neurons are created, retrieved, listed, updated, archived,
#            restored, and searched. Each verb stub delegates to the storage
#            and embedding layers.
# RESPONSIBILITY:
#   - Define verb map: add, get, list, update, archive, restore, search
#   - Define flag/arg specs for each verb
#   - Register with entrypoint dispatch via register_noun()
#   - Each verb handler: parse args, validate, call storage, return Result
# ORGANIZATION:
#   1. Verb handler stubs (one function per verb)
#   2. Noun registration at module level
# =============================================================================

from __future__ import annotations

from typing import List, Any

# from memory_cli.cli.entrypoint_and_argv_dispatch import register_noun
# from memory_cli.cli.output_envelope_json_and_text import Result


# =============================================================================
# VERB: add — create a new neuron
# =============================================================================
def handle_add(args: List[str], global_flags: Any) -> Any:
    """Create a new neuron with content and optional metadata.

    Args:
        args: [content, --type <type>, --source <source>, --tags <t1,t2>]
        global_flags: Parsed global flags.

    Returns:
        Result with status="ok", data={"id": uuid, "type": type, ...}

    Pseudo-logic:
    1. Parse positional arg: content (required, first arg or --content flag)
    2. Parse optional flags:
       - --type <type>: neuron type (default "memory")
       - --source <source>: origin identifier
       - --tags <comma-separated>: initial tags to attach
    3. Validate: content must be non-empty string
    4. Delegate to storage layer: neuron_store.create(content, type, source)
    5. If --tags provided, delegate to tag_store.add_tags(neuron_id, tags)
    6. Trigger embedding generation (async or sync based on config)
    7. Return Result(status="ok", data={"id": neuron_id, ...})
    8. Error path: storage failure -> Result(status="error", error=str(e))
    """
    pass


# =============================================================================
# VERB: get — retrieve a single neuron by ID
# =============================================================================
def handle_get(args: List[str], global_flags: Any) -> Any:
    """Retrieve a neuron by its ID.

    Args:
        args: [neuron_id]
        global_flags: Parsed global flags.

    Returns:
        Result with neuron data, or status="not_found" if ID doesn't exist.

    Pseudo-logic:
    1. Parse positional arg: neuron_id (required)
    2. Validate: neuron_id must be non-empty
    3. Delegate to storage: neuron_store.get(neuron_id)
    4. If not found: return Result(status="not_found", error="Neuron {id} not found")
    5. If found: return Result(status="ok", data=neuron_dict)
    """
    pass


# =============================================================================
# VERB: list — list neurons with optional filters
# =============================================================================
def handle_list(args: List[str], global_flags: Any) -> Any:
    """List neurons with optional filtering and pagination.

    Args:
        args: [--type <type>, --tag <tag>, --limit N, --offset N, --archived]
        global_flags: Parsed global flags.

    Returns:
        Result with data=list of neuron dicts, meta with pagination.

    Pseudo-logic:
    1. Parse optional flags:
       - --type <type>: filter by neuron type
       - --tag <tag>: filter by tag
       - --limit <N>: max results (default 50)
       - --offset <N>: skip first N results (default 0)
       - --archived: include archived neurons (default: exclude)
    2. Delegate to storage: neuron_store.list(filters, limit, offset)
    3. Get total count for pagination meta
    4. Return Result(status="ok", data=neuron_list,
                     meta={"total": total, "limit": limit, "offset": offset})
    5. Empty results are success (exit 0), not "not_found"
    """
    pass


# =============================================================================
# VERB: update — update a neuron's content or metadata
# =============================================================================
def handle_update(args: List[str], global_flags: Any) -> Any:
    """Update an existing neuron's content or metadata fields.

    Args:
        args: [neuron_id, --content <text>, --type <type>, --source <source>]
        global_flags: Parsed global flags.

    Returns:
        Result with updated neuron data, or not_found/error.

    Pseudo-logic:
    1. Parse positional arg: neuron_id (required)
    2. Parse optional flags: --content, --type, --source
    3. At least one update flag must be present, else error
    4. Delegate to storage: neuron_store.update(neuron_id, changes)
    5. If neuron not found: return Result(status="not_found")
    6. If --content changed: trigger re-embedding
    7. Return Result(status="ok", data=updated_neuron_dict)
    """
    pass


# =============================================================================
# VERB: archive — soft-delete a neuron
# =============================================================================
def handle_archive(args: List[str], global_flags: Any) -> Any:
    """Archive (soft-delete) a neuron by ID.

    Args:
        args: [neuron_id]
        global_flags: Parsed global flags.

    Returns:
        Result confirming archive, or not_found.

    Pseudo-logic:
    1. Parse positional arg: neuron_id (required)
    2. Delegate to storage: neuron_store.archive(neuron_id)
    3. If not found: return Result(status="not_found")
    4. Return Result(status="ok", data={"id": neuron_id, "archived": True})
    """
    pass


# =============================================================================
# VERB: restore — un-archive a neuron
# =============================================================================
def handle_restore(args: List[str], global_flags: Any) -> Any:
    """Restore an archived neuron by ID.

    Args:
        args: [neuron_id]
        global_flags: Parsed global flags.

    Returns:
        Result confirming restore, or not_found.

    Pseudo-logic:
    1. Parse positional arg: neuron_id (required)
    2. Delegate to storage: neuron_store.restore(neuron_id)
    3. If not found: return Result(status="not_found")
    4. If not archived: return Result(status="error", error="Neuron is not archived")
    5. Return Result(status="ok", data={"id": neuron_id, "archived": False})
    """
    pass


# =============================================================================
# VERB: search — find neurons by content similarity or keyword
# =============================================================================
def handle_search(args: List[str], global_flags: Any) -> Any:
    """Search neurons using spreading activation / vector similarity.

    Args:
        args: [query_text, --limit N, --threshold F, --type <type>]
        global_flags: Parsed global flags.

    Returns:
        Result with ranked list of matching neurons and scores.

    Pseudo-logic:
    1. Parse positional arg: query_text (required)
    2. Parse optional flags:
       - --limit <N>: max results (default 10)
       - --threshold <F>: minimum similarity score (default 0.0)
       - --type <type>: filter by neuron type
    3. Generate query embedding via embedding engine
    4. Delegate to search layer: search.find(query_embedding, filters, limit)
    5. Filter results below threshold
    6. Return Result(status="ok", data=ranked_results,
                     meta={"total": len(results), "query": query_text})
    7. Empty results are success (exit 0), data=[]
    """
    pass


# =============================================================================
# NOUN REGISTRATION — executed at import time
# =============================================================================
# Verb map: verb name -> handler function
_VERB_MAP = {
    "add": handle_add,
    "get": handle_get,
    "list": handle_list,
    "update": handle_update,
    "archive": handle_archive,
    "restore": handle_restore,
    "search": handle_search,
}

# Verb descriptions for help system
_VERB_DESCRIPTIONS = {
    "add": "Create a new neuron with content",
    "get": "Retrieve a neuron by ID",
    "list": "List neurons with optional filters",
    "update": "Update a neuron's content or metadata",
    "archive": "Soft-delete (archive) a neuron",
    "restore": "Restore an archived neuron",
    "search": "Search neurons by similarity or keyword",
}

# Flag definitions for help system (verb -> list of flag specs)
_FLAG_DEFS = {
    "add": [
        {"name": "--type", "type": "str", "default": "memory", "desc": "Neuron type"},
        {"name": "--source", "type": "str", "default": None, "desc": "Origin identifier"},
        {"name": "--tags", "type": "str", "default": None, "desc": "Comma-separated tags"},
    ],
    "get": [],
    "list": [
        {"name": "--type", "type": "str", "default": None, "desc": "Filter by type"},
        {"name": "--tag", "type": "str", "default": None, "desc": "Filter by tag"},
        {"name": "--limit", "type": "int", "default": 50, "desc": "Max results"},
        {"name": "--offset", "type": "int", "default": 0, "desc": "Skip first N"},
        {"name": "--archived", "type": "bool", "default": False, "desc": "Include archived"},
    ],
    "update": [
        {"name": "--content", "type": "str", "default": None, "desc": "New content"},
        {"name": "--type", "type": "str", "default": None, "desc": "New type"},
        {"name": "--source", "type": "str", "default": None, "desc": "New source"},
    ],
    "archive": [],
    "restore": [],
    "search": [
        {"name": "--limit", "type": "int", "default": 10, "desc": "Max results"},
        {"name": "--threshold", "type": "float", "default": 0.0, "desc": "Min similarity"},
        {"name": "--type", "type": "str", "default": None, "desc": "Filter by type"},
    ],
}


def register() -> None:
    """Register the neuron noun with the CLI dispatch registry.

    Pseudo-logic:
    1. Call register_noun("neuron", {
         "verb_map": _VERB_MAP,
         "description": "Memory neurons — content nodes in the graph",
         "verb_descriptions": _VERB_DESCRIPTIONS,
         "flag_defs": _FLAG_DEFS,
       })
    """
    pass

# --- Self-register on import ---
# register()
