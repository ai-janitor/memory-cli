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

# from memory_cli.cli.entrypoint_and_argv_dispatch import register_noun
# from memory_cli.cli.output_envelope_json_and_text import Result


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
    pass


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
    pass


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
    "add": "Attach tag(s) to a neuron",
    "list": "List tags (all or per neuron)",
    "remove": "Remove tag(s) from a neuron",
}

_FLAG_DEFS = {
    "add": [
        {"name": "--tags", "type": "str", "default": None, "desc": "Comma-separated tags"},
    ],
    "list": [
        {"name": "--neuron", "type": "str", "default": None, "desc": "Filter by neuron ID"},
    ],
    "remove": [],
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
    pass

# --- Self-register on import ---
# register()
