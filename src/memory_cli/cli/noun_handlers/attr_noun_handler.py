# =============================================================================
# FILE: src/memory_cli/cli/noun_handlers/attr_noun_handler.py
# PURPOSE: Register the "attr" noun with the CLI dispatch registry.
#          Attrs are key-value metadata pairs attached to neurons.
# RATIONALE: Attributes provide flexible, schema-free metadata on neurons.
#            Unlike tags (labels), attrs carry values. Three verbs (add, list,
#            remove) — attrs are simple key=value pairs, update is just re-add.
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
# VERB: add — set a key-value attribute on a neuron
# =============================================================================
def handle_add(args: List[str], global_flags: Any) -> Any:
    """Set a key-value attribute on a neuron.

    Args:
        args: [neuron_id, key, value]
        global_flags: Parsed global flags.

    Returns:
        Result confirming attribute set.

    Pseudo-logic:
    1. Parse positional args: neuron_id, key, value (all required)
    2. Validate: neuron must exist, key must be non-empty string
    3. Delegate to storage: attr_store.set(neuron_id, key, value)
    4. Upsert semantics: if key already exists, overwrite value
    5. Return Result(status="ok", data={"neuron_id": id, "key": key, "value": value})
    6. If neuron not found: Result(status="not_found")
    """
    raise NotImplementedError


# =============================================================================
# VERB: list — list attributes for a neuron
# =============================================================================
def handle_list(args: List[str], global_flags: Any) -> Any:
    """List all attributes for a neuron.

    Args:
        args: [neuron_id]
        global_flags: Parsed global flags.

    Returns:
        Result with list of {key, value} dicts.

    Pseudo-logic:
    1. Parse positional arg: neuron_id (required)
    2. Validate: neuron must exist
    3. Delegate to storage: attr_store.list(neuron_id)
    4. Return Result(status="ok", data=attr_list)
    5. Empty list is success (exit 0)
    6. If neuron not found: Result(status="not_found")
    """
    raise NotImplementedError


# =============================================================================
# VERB: remove — delete an attribute from a neuron
# =============================================================================
def handle_remove(args: List[str], global_flags: Any) -> Any:
    """Remove an attribute by key from a neuron.

    Args:
        args: [neuron_id, key]
        global_flags: Parsed global flags.

    Returns:
        Result confirming attribute removed.

    Pseudo-logic:
    1. Parse positional args: neuron_id, key (both required)
    2. Validate: neuron must exist
    3. Delegate to storage: attr_store.remove(neuron_id, key)
    4. Idempotent: removing non-existent key is no-op, not error
    5. Return Result(status="ok", data={"neuron_id": id, "key": key, "removed": True})
    6. If neuron not found: Result(status="not_found")
    """
    raise NotImplementedError


# =============================================================================
# NOUN REGISTRATION
# =============================================================================
_VERB_MAP = {
    "add": handle_add,
    "list": handle_list,
    "remove": handle_remove,
}

_VERB_DESCRIPTIONS = {
    "add": "Set a key-value attribute on a neuron",
    "list": "List all attributes for a neuron",
    "remove": "Remove an attribute by key from a neuron",
}

_FLAG_DEFS = {
    "add": [],
    "list": [],
    "remove": [],
}


def register() -> None:
    """Register the attr noun with the CLI dispatch registry.

    Pseudo-logic:
    1. Call register_noun("attr", {
         "verb_map": _VERB_MAP,
         "description": "Attributes — key-value metadata on neurons",
         "verb_descriptions": _VERB_DESCRIPTIONS,
         "flag_defs": _FLAG_DEFS,
       })
    """
    register_noun("attr", {
        "verb_map": _VERB_MAP,
        "description": "Attributes — key-value metadata on neurons",
        "verb_descriptions": _VERB_DESCRIPTIONS,
        "flag_defs": _FLAG_DEFS,
    })

# --- Self-register on import ---
register()
