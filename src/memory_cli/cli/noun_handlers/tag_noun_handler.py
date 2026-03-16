# =============================================================================
# FILE: src/memory_cli/cli/noun_handlers/tag_noun_handler.py
# PURPOSE: Register the "tag" noun with the CLI dispatch registry.
#          Tags are labels attached to neurons for categorical filtering.
# RATIONALE: Tags are a lightweight classification system. Three verbs only
#            (add, list, remove) — tags are simple by design. No update verb
#            because tags are atomic labels; you remove and re-add.
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
# VERB: add — attach tag(s) to a neuron
# =============================================================================
def handle_add(args: List[str], global_flags: Any) -> Any:
    """Attach one or more tags to a neuron.

    Args:
        args: [neuron_id, tag_name, ...] or [neuron_id, --tags <comma-sep>]
        global_flags: Parsed global flags.

    Returns:
        Result confirming tags added.

    Pseudo-logic:
    1. Parse positional args: neuron_id (required), tag_names (one or more)
    2. Validate: neuron_id must exist, tag names must be non-empty strings
    3. Normalize tag names: lowercase, strip whitespace, reject special chars
    4. Delegate to storage: tag_store.add(neuron_id, tag_names)
    5. Idempotent: adding an existing tag is a no-op, not an error
    6. Return Result(status="ok", data={"neuron_id": id, "tags_added": [...]})
    7. If neuron not found: Result(status="not_found")
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_layered_connections
    from memory_cli.cli.noun_handlers.arg_parse_extract_positional_and_flags import (
        require_positional, extract_flag,
    )
    from memory_cli.cli.scoped_handle_format_and_parse import (
        parse_handle, format_handle, resolve_connection_by_scope,
    )
    try:
        nid_raw, rest = require_positional(list(args), "neuron_id")
        handle_scope, nid = parse_handle(nid_raw)
        # Collect tag names from remaining positional args or --tags flag
        tags_flag, rest = extract_flag(rest, "--tags")
        tag_names = []
        if tags_flag:
            tag_names.extend([t.strip() for t in tags_flag.split(",") if t.strip()])
        # Remaining positional args are also tag names
        tag_names.extend([t for t in rest if not t.startswith("--")])
        if not tag_names:
            return Result(status="error", error="At least one tag name is required")
        # Route by handle scope; default to first (local-preferred) connection
        connections = get_layered_connections(global_flags)
        conn, scope = connections[0]
        if handle_scope is not None:
            match = resolve_connection_by_scope(handle_scope, connections)
            if match is not None:
                conn, scope = match
            else:
                return Result(status="not_found", error=f"No {handle_scope} store available for {nid_raw}")
        from memory_cli.neuron import neuron_get, neuron_update, NeuronUpdateError
        neuron = neuron_get(conn, nid)
        if neuron is None:
            return Result(status="not_found", error=f"Neuron {nid_raw} not found")
        neuron_update(conn, nid, tags_add=tag_names)
        return Result(status="ok", data={"neuron_id": format_handle(nid, scope), "tags_added": tag_names})
    except (ValueError, Exception) as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: list — list tags for a neuron or all tags in the database
# =============================================================================
def handle_list(args: List[str], global_flags: Any) -> Any:
    """List tags, optionally filtered by neuron ID.

    Args:
        args: [--neuron <id>] or [] for all tags
        global_flags: Parsed global flags.

    Returns:
        Result with list of tag strings or tag objects.

    Pseudo-logic:
    1. Parse optional flag: --neuron <id>
    2. If --neuron provided:
       a. Validate neuron exists
       b. Delegate: tag_store.list_for_neuron(neuron_id)
       c. If neuron not found: Result(status="not_found")
    3. If no --neuron:
       a. Delegate: tag_store.list_all()
       b. Optionally include counts per tag
    4. Return Result(status="ok", data=tag_list)
    5. Empty list is success (exit 0)
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_layered_connections
    from memory_cli.cli.noun_handlers.arg_parse_extract_positional_and_flags import extract_flag
    from memory_cli.cli.scoped_handle_format_and_parse import parse_handle, resolve_connection_by_scope
    try:
        neuron_id_raw, rest = extract_flag(list(args), "--neuron")
        sort_value, rest = extract_flag(rest, "--sort")
        limit_value, rest = extract_flag(rest, "--limit")
        limit = int(limit_value) if limit_value else 0
        sort_by_count = sort_value == "count" if sort_value else False
        connections = get_layered_connections(global_flags)
        if neuron_id_raw is not None:
            # Neuron-scoped: route to matching store by scope, then look up the neuron
            handle_scope, neuron_id = parse_handle(neuron_id_raw)
            if handle_scope is not None:
                match = resolve_connection_by_scope(handle_scope, connections)
                if match is None:
                    return Result(status="not_found", error=f"No {handle_scope} store available for {neuron_id_raw}")
                connections = [match]
            from memory_cli.neuron import neuron_get
            for conn, scope in connections:
                neuron = neuron_get(conn, neuron_id)
                if neuron is not None:
                    return Result(status="ok", data=neuron.get("tags", []))
            return Result(status="not_found", error=f"Neuron {neuron_id_raw} not found")
        elif sort_by_count:
            # Tag list with counts, sorted by most common
            from memory_cli.registries import tag_list_with_counts
            merged: dict = {}
            for conn, scope in connections:
                tags = tag_list_with_counts(conn)
                for t in tags:
                    name = t["name"]
                    merged[name] = merged.get(name, 0) + t["count"]
            result_list = [{"name": k, "count": v} for k, v in merged.items()]
            result_list.sort(key=lambda x: x["count"], reverse=True)
            if limit > 0:
                result_list = result_list[:limit]
            return Result(status="ok", data=result_list)
        else:
            # Global tag list: merge from all stores, deduplicate
            from memory_cli.registries import tag_list
            all_tags = []
            seen = set()
            for conn, scope in connections:
                tags = tag_list(conn)
                for t in tags:
                    tag_name = t.get("name", t.get("tag", t)) if isinstance(t, dict) else t
                    if tag_name not in seen:
                        seen.add(tag_name)
                        all_tags.append(t)
            if limit > 0:
                all_tags = all_tags[:limit]
            return Result(status="ok", data=all_tags)
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: remove — detach tag(s) from a neuron
# =============================================================================
def handle_remove(args: List[str], global_flags: Any) -> Any:
    """Remove one or more tags from a neuron.

    Args:
        args: [neuron_id, tag_name, ...]
        global_flags: Parsed global flags.

    Returns:
        Result confirming tags removed.

    Pseudo-logic:
    1. Parse positional args: neuron_id (required), tag_names (one or more)
    2. Validate: neuron_id must exist
    3. Delegate to storage: tag_store.remove(neuron_id, tag_names)
    4. Idempotent: removing a non-existent tag is a no-op, not an error
    5. Return Result(status="ok", data={"neuron_id": id, "tags_removed": [...]})
    6. If neuron not found: Result(status="not_found")
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_layered_connections
    from memory_cli.cli.noun_handlers.arg_parse_extract_positional_and_flags import require_positional
    from memory_cli.cli.scoped_handle_format_and_parse import (
        parse_handle, format_handle, resolve_connection_by_scope,
    )
    try:
        nid_raw, rest = require_positional(list(args), "neuron_id")
        handle_scope, nid = parse_handle(nid_raw)
        tag_names = [t for t in rest if not t.startswith("--")]
        if not tag_names:
            return Result(status="error", error="At least one tag name is required")
        # Route by handle scope; default to first (local-preferred) connection
        connections = get_layered_connections(global_flags)
        conn, scope = connections[0]
        if handle_scope is not None:
            match = resolve_connection_by_scope(handle_scope, connections)
            if match is not None:
                conn, scope = match
            else:
                return Result(status="not_found", error=f"No {handle_scope} store available for {nid_raw}")
        from memory_cli.neuron import neuron_get, neuron_update
        neuron = neuron_get(conn, nid)
        if neuron is None:
            return Result(status="not_found", error=f"Neuron {nid_raw} not found")
        neuron_update(conn, nid, tags_remove=tag_names)
        return Result(status="ok", data={"neuron_id": format_handle(nid, scope), "tags_removed": tag_names})
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: audit — report tag usage statistics and noise candidates
# =============================================================================
def handle_audit(args: List[str], global_flags: Any) -> Any:
    """Audit tag usage: counts per tag, type patterns, noise candidates.

    Args:
        args: [] (no arguments required)
        global_flags: Parsed global flags.

    Returns:
        Result with audit report dict.
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_layered_connections
    try:
        connections = get_layered_connections(global_flags)
        from memory_cli.registries import tag_audit
        # Merge audit data across layered connections
        merged_tags: dict = {}  # name -> {count, type_pattern}
        total_neurons = 0
        for conn, scope in connections:
            report = tag_audit(conn)
            total_neurons += report["total_neurons"]
            for t in report["tags"]:
                name = t["name"]
                if name in merged_tags:
                    merged_tags[name]["count"] += t["count"]
                else:
                    merged_tags[name] = {"count": t["count"], "type_pattern": t["type_pattern"]}

        tags = [
            {"name": k, "count": v["count"], "type_pattern": v["type_pattern"]}
            for k, v in merged_tags.items()
        ]
        tags.sort(key=lambda x: (-x["count"], x["name"]))

        noise_candidates = [t["name"] for t in tags if t["count"] == 1]

        result = {
            "tags": tags,
            "total_tags": len(tags),
            "total_neurons": total_neurons,
            "noise_candidates": noise_candidates,
        }
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
    "audit": handle_audit,
}

_VERB_DESCRIPTIONS = {
    "add": "Attach tag(s) to a neuron",
    "list": "List tags (all or per neuron)",
    "remove": "Remove tag(s) from a neuron",
    "audit": "Report tag usage statistics and noise candidates",
}

_FLAG_DEFS = {
    "add": [
        {"name": "--tags", "type": "str", "default": None, "desc": "Comma-separated tags"},
    ],
    "list": [
        {"name": "--neuron", "type": "str", "default": None, "desc": "Filter by neuron ID"},
    ],
    "remove": [],
    "audit": [],
}


def register() -> None:
    """Register the tag noun with the CLI dispatch registry.

    Pseudo-logic:
    1. Call register_noun("tag", {
         "verb_map": _VERB_MAP,
         "description": "Tags — categorical labels for neurons",
         "verb_descriptions": _VERB_DESCRIPTIONS,
         "flag_defs": _FLAG_DEFS,
       })
    """
    register_noun("tag", {
        "verb_map": _VERB_MAP,
        "description": "Tags — categorical labels for neurons",
        "verb_descriptions": _VERB_DESCRIPTIONS,
        "flag_defs": _FLAG_DEFS,
    })

# --- Self-register on import ---
register()
