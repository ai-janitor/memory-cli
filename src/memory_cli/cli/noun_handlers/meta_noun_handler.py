# =============================================================================
# FILE: src/memory_cli/cli/noun_handlers/meta_noun_handler.py
# PURPOSE: Register the "meta" noun with the CLI dispatch registry.
#          Meta provides introspection into the database: info and stats.
# RATIONALE: Agents and users need to inspect database state without browsing
#            raw tables (opaque storage principle). Meta exposes curated views:
#            database version, counts, embedding model info, disk usage.
# RESPONSIBILITY:
#   - Define verb map: info, stats
#   - Register with entrypoint dispatch via register_noun()
#   - Each verb handler: query storage layer for metadata, return Result
# ORGANIZATION:
#   1. Verb handler stubs
#   2. Noun registration at module level
# =============================================================================

from __future__ import annotations

from typing import List, Any

# from memory_cli.cli.entrypoint_and_argv_dispatch import register_noun
# from memory_cli.cli.output_envelope_json_and_text import Result


# =============================================================================
# VERB: info — database identity and configuration
# =============================================================================
def handle_info(args: List[str], global_flags: Any) -> Any:
    """Show database identity and configuration metadata.

    Args:
        args: [] (no arguments)
        global_flags: Parsed global flags.

    Returns:
        Result with database info dict.

    Pseudo-logic:
    1. If args has unexpected positional args, error
    2. Delegate to storage: meta_store.get_info()
    3. Build info dict:
       - "db_path": absolute path to database file
       - "db_version": schema version string
       - "embedding_model": model name and dimensions
       - "config_path": absolute path to config file
       - "created_at": database creation timestamp
    4. Return Result(status="ok", data=info_dict)
    5. Error path: DB not initialized -> Result(status="error",
       error="Database not initialized. Run `memory init`.")
    """
    pass


# =============================================================================
# VERB: stats — database statistics
# =============================================================================
def handle_stats(args: List[str], global_flags: Any) -> Any:
    """Show database statistics: counts, sizes, health.

    Args:
        args: [] (no arguments)
        global_flags: Parsed global flags.

    Returns:
        Result with stats dict.

    Pseudo-logic:
    1. If args has unexpected positional args, error
    2. Delegate to storage: meta_store.get_stats()
    3. Build stats dict:
       - "neuron_count": total neurons (active + archived)
       - "active_neuron_count": non-archived neurons
       - "archived_neuron_count": archived neurons
       - "edge_count": total edges
       - "tag_count": unique tags
       - "attr_count": total attributes
       - "embedding_count": neurons with embeddings
       - "db_size_bytes": database file size
    4. Return Result(status="ok", data=stats_dict)
    5. Error path: DB not initialized -> error result
    """
    pass


# =============================================================================
# NOUN REGISTRATION
# =============================================================================
_VERB_MAP = {
    "info": handle_info,
    "stats": handle_stats,
}

_VERB_DESCRIPTIONS = {
    "info": "Show database identity and configuration",
    "stats": "Show database statistics (counts, sizes)",
}

_FLAG_DEFS = {
    "info": [],
    "stats": [],
}


def register() -> None:
    """Register the meta noun with the CLI dispatch registry.

    Pseudo-logic:
    1. Call register_noun("meta", {
         "verb_map": _VERB_MAP,
         "description": "Meta — database introspection and statistics",
         "verb_descriptions": _VERB_DESCRIPTIONS,
         "flag_defs": _FLAG_DEFS,
       })
    """
    pass

# --- Self-register on import ---
# register()
