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

from memory_cli.cli.entrypoint_and_argv_dispatch import register_noun


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
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_connection_and_config
    try:
        conn, config = get_connection_and_config(global_flags)
        from memory_cli.db import read_schema_version
        from memory_cli.db.store_fingerprint_read_and_cache import get_fingerprint
        version = read_schema_version(conn)
        # Read fingerprint and store identity from meta table
        try:
            fingerprint = get_fingerprint(conn)
        except ValueError:
            fingerprint = None
        meta_project = conn.execute(
            "SELECT value FROM meta WHERE key = 'project'"
        ).fetchone()
        meta_db_path = conn.execute(
            "SELECT value FROM meta WHERE key = 'db_path'"
        ).fetchone()
        info = {
            "db_path": config.db_path,
            "schema_version": version,
            "fingerprint": fingerprint,
            "project": meta_project[0] if meta_project else None,
            "store_db_path": meta_db_path[0] if meta_db_path else None,
            "embedding_model": config.embedding.model_path,
            "embedding_dimensions": config.embedding.dimensions,
        }
        return Result(status="ok", data=info)
    except Exception as e:
        return Result(status="error", error=str(e))


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
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_connection_and_config
    try:
        conn, config = get_connection_and_config(global_flags)
        from memory_cli.integrity import gather_meta_stats
        config_dict = {
            "embedding": {
                "model_path": config.embedding.model_path,
                "dimensions": config.embedding.dimensions,
            },
        }
        stats = gather_meta_stats(conn, config_dict, config.db_path)
        return Result(status="ok", data=stats)
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: manifesto — show or update the store's memory manifesto
# =============================================================================
def handle_manifesto(args: List[str], global_flags: Any) -> Any:
    """Show or update the memory manifesto for the active store.

    The manifesto is a USAGE GUIDE — it tells agents how to use this memory
    store: how to store, extract, judge value, and handle provenance.

    It is NOT a repository of rules, preferences, or project-specific data.
    Those belong as neurons in the graph where they can have edges, fan out,
    and participate in activation. The manifesto may point agents to search
    for those neurons (e.g., "search for user-rule tags before scaffolding")
    but should not contain the rules themselves.

    Subcommands:
        memory meta manifesto          — show the current manifesto
        memory meta manifesto set "…"  — replace the manifesto with new text
        memory meta manifesto set --file <path> — replace from file content

    Args:
        args: Remaining tokens after "manifesto" (e.g., [], ["set", "new text"],
              ["set", "--file", "path"]).
        global_flags: Parsed global flags.

    Returns:
        Result with manifesto text or update confirmation.

    Pseudo-logic:
    1. If args is empty: read manifesto from meta table, return it
    2. If args[0] == "set":
       a. If "--file" flag present: read file content, use as new manifesto
       b. Else: use next positional arg as new manifesto text
       c. UPDATE meta SET value = new_text WHERE key = 'manifesto'
       d. Return Result(status="ok", data={"manifesto": new_text, "updated": True})
    3. Otherwise: error — unknown subcommand
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_connection_and_config

    try:
        conn, config = get_connection_and_config(global_flags)

        # --- Subcommand dispatch ---
        if not args:
            # Show manifesto
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'manifesto'"
            ).fetchone()
            if row is None:
                return Result(
                    status="not_found",
                    error="No manifesto found. Run `memory init` or set one with `memory meta manifesto set`.",
                )
            return Result(status="ok", data={"manifesto": row[0]})

        subcmd = args[0]

        if subcmd == "set":
            sub_args = args[1:]
            new_text = None

            # Check for --file flag
            if "--file" in sub_args:
                idx = sub_args.index("--file")
                if idx + 1 >= len(sub_args):
                    return Result(status="error", error="--file requires a path argument.")
                file_path = sub_args[idx + 1]
                try:
                    from pathlib import Path
                    new_text = Path(file_path).read_text(encoding="utf-8")
                except FileNotFoundError:
                    return Result(status="error", error=f"File not found: {file_path}")
                except OSError as e:
                    return Result(status="error", error=f"Cannot read file: {e}")
            elif sub_args:
                # Positional text argument
                new_text = sub_args[0]
            else:
                return Result(
                    status="error",
                    error='Usage: memory meta manifesto set "<text>" or memory meta manifesto set --file <path>',
                )

            if new_text is not None:
                # Upsert manifesto
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('manifesto', ?)",
                    (new_text,),
                )
                conn.commit()
                return Result(status="ok", data={"manifesto": new_text, "updated": True})

        return Result(status="error", error=f"Unknown manifesto subcommand: {subcmd}")

    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: fingerprint — show this store's identity
# =============================================================================
def handle_fingerprint(args: List[str], global_flags: Any) -> Any:
    """Show the current store's fingerprint, project name, and db_path.

    Output:
        {"fingerprint": "a3f2b7c1", "project": "my-project", "db_path": "/path/to/memory.db"}

    Args:
        args: [] (no arguments).
        global_flags: Parsed global flags.

    Returns:
        Result with fingerprint identity dict.
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_connection_and_config

    try:
        conn, config = get_connection_and_config(global_flags)
        from memory_cli.db.store_fingerprint_read_and_cache import get_fingerprint

        fingerprint = get_fingerprint(conn)
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'project'"
        ).fetchone()
        project_name = row[0] if row else None

        return Result(status="ok", data={
            "fingerprint": fingerprint,
            "project": project_name,
            "db_path": config.db_path,
        })
    except ValueError as e:
        from memory_cli.cli.output_envelope_json_and_text import Result
        return Result(
            status="error",
            error=str(e),
        )
    except Exception as e:
        from memory_cli.cli.output_envelope_json_and_text import Result
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: stores — list all registered stores from ~/.memory/stores.json
# =============================================================================
def handle_stores(args: List[str], global_flags: Any) -> Any:
    """List all stores registered in the global ~/.memory/stores.json registry.

    Output:
        List of {"fingerprint": ..., "db_path": ..., "project": ..., "registered_at": ...}

    Args:
        args: [] (no arguments).
        global_flags: Parsed global flags.

    Returns:
        Result with list of store entries.
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.config.store_registry import list_stores

    try:
        stores = list_stores()
        return Result(status="ok", data=stores)
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: consolidate — extract entities/facts from unconsolidated neurons
# =============================================================================
def handle_consolidate(args: List[str], global_flags: Any) -> Any:
    """Run entity extraction consolidation on neurons using Haiku.

    Extracts entities, facts, and relationships from unconsolidated neuron
    content blobs. Creates sub-neurons with provenance metadata and wires
    edges with confidence < 1.0.

    Subcommands:
        memory meta consolidate                  — consolidate all unconsolidated neurons
        memory meta consolidate --neuron-id <id> — consolidate a single neuron
        memory meta consolidate --dry-run        — show what would be consolidated
        memory meta consolidate --limit <n>      — limit batch to n neurons
        memory meta consolidate --force          — re-consolidate already-consolidated neurons

    Args:
        args: Remaining tokens after "consolidate".
        global_flags: Parsed global flags.

    Returns:
        Result with consolidation summary.
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_connection_and_config

    try:
        conn, config = get_connection_and_config(global_flags)

        # --- Parse flags ---
        neuron_id = None
        dry_run = False
        limit = None
        force = False

        i = 0
        while i < len(args):
            if args[i] == "--neuron-id" and i + 1 < len(args):
                try:
                    neuron_id = int(args[i + 1])
                except ValueError:
                    return Result(status="error", error=f"Invalid neuron ID: {args[i + 1]}")
                i += 2
            elif args[i] == "--dry-run":
                dry_run = True
                i += 1
            elif args[i] == "--limit" and i + 1 < len(args):
                try:
                    limit = int(args[i + 1])
                except ValueError:
                    return Result(status="error", error=f"Invalid limit: {args[i + 1]}")
                i += 2
            elif args[i] == "--force":
                force = True
                i += 1
            else:
                return Result(status="error", error=f"Unknown argument: {args[i]}")

        from memory_cli.ingestion.consolidation_orchestrator import (
            consolidate_neuron,
            consolidate_all,
            find_unconsolidated_neurons,
        )

        # --- Dry run: just show what would be consolidated ---
        if dry_run:
            if neuron_id is not None:
                from memory_cli.ingestion.consolidation_orchestrator import _is_consolidated
                is_done = _is_consolidated(conn, neuron_id)
                return Result(status="ok", data={
                    "dry_run": True,
                    "neuron_id": neuron_id,
                    "already_consolidated": is_done,
                    "would_process": not is_done or force,
                })
            else:
                ids = find_unconsolidated_neurons(conn, limit=limit)
                return Result(status="ok", data={
                    "dry_run": True,
                    "unconsolidated_count": len(ids),
                    "neuron_ids": ids,
                })

        # --- Single neuron consolidation ---
        if neuron_id is not None:
            result = consolidate_neuron(conn, neuron_id, force=force)
            return Result(
                status="ok",
                data={
                    "neurons_processed": result.neurons_processed,
                    "neurons_skipped": result.neurons_skipped,
                    "sub_neurons_created": result.sub_neurons_created,
                    "edges_created": result.edges_created,
                    "errors": result.errors,
                },
                warnings=result.warnings,
            )

        # --- Batch consolidation ---
        result = consolidate_all(conn, limit=limit)
        return Result(
            status="ok",
            data={
                "neurons_processed": result.neurons_processed,
                "neurons_skipped": result.neurons_skipped,
                "sub_neurons_created": result.sub_neurons_created,
                "edges_created": result.edges_created,
                "errors": result.errors,
            },
            warnings=result.warnings,
        )

    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# NOUN REGISTRATION
# =============================================================================
_VERB_MAP = {
    "info": handle_info,
    "stats": handle_stats,
    "manifesto": handle_manifesto,
    "fingerprint": handle_fingerprint,
    "stores": handle_stores,
    "consolidate": handle_consolidate,
}

_VERB_DESCRIPTIONS = {
    "info": "Show database identity and configuration",
    "stats": "Show database statistics (counts, sizes)",
    "manifesto": "Show or update the store's memory manifesto (usage guide, not data — rules belong as neurons)",
    "fingerprint": "Show this store's fingerprint, project name, and db_path",
    "stores": "List all known stores from ~/.memory/stores.json",
    "consolidate": "Extract entities/facts from neurons via Haiku (--neuron-id <id>, --dry-run, --limit <n>, --force)",
}

_FLAG_DEFS = {
    "info": [],
    "stats": [],
    "manifesto": [
        {"name": "set", "type": "subcommand", "default": None, "desc": "Replace manifesto: memory meta manifesto set \"<text>\""},
        {"name": "--file", "type": "str", "default": None, "desc": "Read new manifesto from file: memory meta manifesto set --file <path>"},
    ],
    "fingerprint": [],
    "stores": [],
    "consolidate": [
        {"name": "--neuron-id", "type": "int", "default": None, "desc": "Consolidate a single neuron by ID"},
        {"name": "--dry-run", "type": "bool", "default": False, "desc": "Show what would be consolidated without making changes"},
        {"name": "--limit", "type": "int", "default": None, "desc": "Max number of neurons to process in batch mode"},
        {"name": "--force", "type": "bool", "default": False, "desc": "Re-consolidate already-consolidated neurons"},
    ],
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
    register_noun("meta", {
        "verb_map": _VERB_MAP,
        "description": "Meta — database introspection and statistics",
        "verb_descriptions": _VERB_DESCRIPTIONS,
        "flag_defs": _FLAG_DEFS,
    })

# --- Self-register on import ---
register()
