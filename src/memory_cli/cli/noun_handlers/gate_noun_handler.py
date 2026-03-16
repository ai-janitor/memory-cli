# =============================================================================
# FILE: src/memory_cli/cli/noun_handlers/gate_noun_handler.py
# PURPOSE: Register the "gate" noun with the CLI dispatch registry.
#          Gate provides topology entry points and cross-store registration.
# RATIONALE: The gate is the densest node in a memory store — the natural
#            entry point into the knowledge graph. This noun exposes commands
#            to view the gate, register local stores in the global store, and
#            deregister them.
# RESPONSIBILITY:
#   - Define verb map: show, register, deregister
#   - Register with entrypoint dispatch via register_noun()
#   - Each verb handler: delegates to gate domain logic, returns Result
# ORGANIZATION:
#   1. Verb handler functions
#   2. Verb map, descriptions, flag defs
#   3. Noun registration at module level
# =============================================================================

from __future__ import annotations

import logging
from typing import Any, List

from memory_cli.cli.entrypoint_and_argv_dispatch import register_noun

logger = logging.getLogger(__name__)


# =============================================================================
# VERB: show — display current store's gate and all discoverable store gates
# =============================================================================
def handle_show(args: List[str], global_flags: Any) -> Any:
    """Display the current store's gate neuron and all discoverable local store gates.

    Computes:
    1. Current store's gate (densest node) and its top 10 neighbors (houses).
    2. All discoverable local memory stores (ancestor walk + global) and their gates.

    Output is a JSON envelope with:
    {
      "current_store": { "scope", "gate_neuron_id", "edge_count", "houses": [...] },
      "all_stores": [ { "store_path", "scope", "gate_neuron_id", "edge_count" }, ... ]
    }

    Args:
        args: Remaining CLI args after `memory gate show`.
              Supports: --top-n N (default 10)
        global_flags: Parsed global flags.

    Returns:
        Result with gate info data.
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_connection_and_scope
    from memory_cli.cli.noun_handlers.arg_parse_extract_positional_and_flags import extract_flag
    from memory_cli.gate.gate_compute_densest_node import compute_densest_node
    from memory_cli.gate.gate_neighborhood_discovery import discover_neighborhood
    from memory_cli.gate.store_discovery_all_local_gates import discover_all_local_gates

    try:
        rest = list(args)
        top_n, rest = extract_flag(rest, "--top-n", type_fn=int, default=10)

        # Get current store connection and scope
        conn, scope = get_connection_and_scope(global_flags)

        # Compute gate for current store
        gate = compute_densest_node(conn)

        # Discover neighborhood (houses) if gate exists
        houses = []
        if gate is not None:
            neighbors = discover_neighborhood(
                conn, gate.neuron_id, top_n=top_n,
            )
            houses = [
                {
                    "target_id": n.target_id,
                    "reason": n.reason,
                    "weight": n.weight,
                }
                for n in neighbors
            ]

        # Build current store dict
        current_store = {
            "scope": scope,
            "gate_neuron_id": gate.neuron_id if gate is not None else None,
            "edge_count": gate.edge_count if gate is not None else 0,
            "houses": houses,
        }

        # Discover all stores
        all_stores_raw = discover_all_local_gates()
        all_stores = [
            {
                "store_path": str(s.store_path),
                "scope": s.scope,
                "gate_neuron_id": s.gate_neuron_id,
                "edge_count": s.edge_count,
            }
            for s in all_stores_raw
        ]

        return Result(
            status="ok",
            data={
                "current_store": current_store,
                "all_stores": all_stores,
            },
        )
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: register — register local store in global store
# =============================================================================
def handle_register(args: List[str], global_flags: Any) -> Any:
    """Register the current LOCAL store in the GLOBAL memory store.

    Creates a representative neuron in the global store that encodes this
    project's path and gate info, then edges it to the global gate.

    Validation:
    - Must be run FROM a local store (not from global — use `memory` without --global).
    - Global store must exist at ~/.memory/.

    Args:
        args: Remaining CLI args (none expected).
        global_flags: Parsed global flags.

    Returns:
        Result with registration data.
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import (
        get_connection_and_config,
        _open_config_path,
    )
    from memory_cli.cli.scoped_handle_format_and_parse import detect_scope
    from memory_cli.config.config_path_resolution_ancestor_walk import _global_config_path
    from memory_cli.gate.gate_register_deregister import register, GateRegistrationError
    from pathlib import Path

    try:
        # Get local connection
        local_conn, local_config = get_connection_and_config(global_flags)

        # Check scope — must be LOCAL
        local_scope = detect_scope(local_config.db_path)
        if local_scope == "GLOBAL":
            return Result(
                status="error",
                error=(
                    "Cannot register from the global store. "
                    "Run `memory gate register` from within a project directory "
                    "that has a local .memory/ store."
                ),
            )

        # Check global store exists
        global_cfg_path = _global_config_path()
        if not global_cfg_path.is_file():
            return Result(
                status="error",
                error=(
                    "No global memory store found at ~/.memory/. "
                    "Run `memory init --global` to create one."
                ),
            )

        # Open global connection
        global_conn, _ = _open_config_path(global_cfg_path)

        # Compute local store path from config db_path
        local_db_path = Path(local_config.db_path)
        # Store path is parent of parent (db is at .memory/data/memory.db or .memory/memory.db)
        local_store_path = local_db_path.parent.parent

        # Do the registration
        result = register(local_conn, local_store_path, global_conn)
        global_conn.close()

        return Result(status="ok", data=result)
    except GateRegistrationError as e:
        return Result(status="error", error=str(e))
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: deregister — remove local store registration from global store
# =============================================================================
def handle_deregister(args: List[str], global_flags: Any) -> Any:
    """Remove the current LOCAL store's registration from the GLOBAL memory store.

    Finds and hard-deletes the representative neuron (and its edges) that was
    created by `memory gate register`.

    Validation:
    - Must be run FROM a local store (not from global).
    - Global store must exist.

    Args:
        args: Remaining CLI args (none expected).
        global_flags: Parsed global flags.

    Returns:
        Result with deregistration data.
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import (
        get_connection_and_config,
        _open_config_path,
    )
    from memory_cli.cli.scoped_handle_format_and_parse import detect_scope
    from memory_cli.config.config_path_resolution_ancestor_walk import _global_config_path
    from memory_cli.gate.gate_register_deregister import deregister, GateRegistrationError
    from pathlib import Path

    try:
        # Get local connection (just for config — we close immediately)
        local_conn, local_config = get_connection_and_config(global_flags)
        local_conn.close()

        # Check scope — must be LOCAL
        local_scope = detect_scope(local_config.db_path)
        if local_scope == "GLOBAL":
            return Result(
                status="error",
                error=(
                    "Cannot deregister from the global store. "
                    "Run `memory gate deregister` from within a project directory "
                    "that has a local .memory/ store."
                ),
            )

        # Check global store exists
        global_cfg_path = _global_config_path()
        if not global_cfg_path.is_file():
            return Result(
                status="error",
                error=(
                    "No global memory store found at ~/.memory/. "
                    "Nothing to deregister."
                ),
            )

        # Open global connection
        global_conn, _ = _open_config_path(global_cfg_path)

        # Compute local store path
        local_db_path = Path(local_config.db_path)
        local_store_path = local_db_path.parent.parent

        # Do the deregistration
        result = deregister(local_store_path, global_conn)
        global_conn.close()

        return Result(status="ok", data=result)
    except GateRegistrationError as e:
        return Result(status="error", error=str(e))
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB MAP, DESCRIPTIONS, FLAG DEFS
# =============================================================================
_VERB_MAP = {
    "show": handle_show,
    "register": handle_register,
    "deregister": handle_deregister,
}

_VERB_DESCRIPTIONS = {
    "show": "Display current store's gate and all discoverable store gates",
    "register": "Register this local store in the global memory store",
    "deregister": "Remove this local store's registration from the global store",
}

_FLAG_DEFS = {
    "--top-n": {"name": "--top-n", "type": "int", "default": 10, "desc": "Max neighbor houses to show"},
}


# =============================================================================
# NOUN REGISTRATION — auto-triggered on import
# =============================================================================
def register():
    """Register the gate noun with the CLI dispatch registry."""
    register_noun(
        "gate",
        {
            "verb_map": _VERB_MAP,
            "description": "Gate neurons — topology entry points and cross-store registration",
            "verb_descriptions": _VERB_DESCRIPTIONS,
            "flag_defs": _FLAG_DEFS,
            "default_verb": "show",
        },
    )


register()
