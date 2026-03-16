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
# VERB: consolidate — mark unconsolidated neurons as consolidated
# =============================================================================
def handle_consolidate(args: List[str], global_flags: Any) -> Any:
    """Process unconsolidated neurons and mark them with a consolidated timestamp.

    Queries active neurons where consolidated IS NULL, ordered by created_at ASC
    (FIFO). Sets consolidated = current timestamp (ms UTC) for each.

    Also detects stale neurons: already-consolidated neurons whose updated_at
    is greater than their consolidated timestamp (modified since last consolidation).

    Args:
        args: [] (no arguments).
        global_flags: Parsed global flags.

    Returns:
        Result with consolidation report dict:
        - consolidated_count: number of neurons newly consolidated
        - stale_count: number of already-consolidated neurons that are stale
        - stale_ids: list of neuron IDs that are stale
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_connection_and_config
    import time

    try:
        conn, config = get_connection_and_config(global_flags)
        now_ms = int(time.time() * 1000)

        # --- Step 1: Find and mark unconsolidated neurons (FIFO) ---
        unconsolidated = conn.execute(
            "SELECT id FROM neurons WHERE status = 'active' AND consolidated IS NULL ORDER BY created_at ASC"
        ).fetchall()

        for row in unconsolidated:
            conn.execute(
                "UPDATE neurons SET consolidated = ? WHERE id = ?",
                (now_ms, row[0]),
            )

        consolidated_count = len(unconsolidated)

        # --- Step 2: Detect stale neurons (updated after consolidation) ---
        stale_rows = conn.execute(
            "SELECT id FROM neurons WHERE status = 'active' AND consolidated IS NOT NULL AND updated_at > consolidated"
        ).fetchall()

        stale_ids = [r[0] for r in stale_rows]

        if consolidated_count > 0 or stale_ids:
            conn.commit()

        return Result(status="ok", data={
            "consolidated_count": consolidated_count,
            "stale_count": len(stale_ids),
            "stale_ids": stale_ids,
        })
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: health — search latency statistics and degradation warnings
# =============================================================================
def handle_health(args: List[str], global_flags: Any) -> Any:
    """Report search latency statistics (p50/p95/p99) and suggest pruning.

    Reads the last N search latency records (default 100, configurable via
    --window flag) and computes percentile statistics. If p95 exceeds the
    configured threshold (search.latency_threshold_ms), emits a warning
    and suggests running `memory neuron prune`.

    Args:
        args: [--window N] optional window size for latency records.
        global_flags: Parsed global flags.

    Returns:
        Result with latency stats dict and optional warning.
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_connection_and_config

    try:
        conn, config = get_connection_and_config(global_flags)

        # Parse --window flag
        window = 100
        rest = list(args)
        if "--window" in rest:
            idx = rest.index("--window")
            if idx + 1 < len(rest):
                window = int(rest[idx + 1])

        # Check if search_latency table exists
        table_check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='search_latency'"
        ).fetchone()
        if not table_check:
            return Result(
                status="ok",
                data={
                    "message": "No search latency data available. Run some searches first.",
                    "sample_count": 0,
                },
            )

        # Fetch recent latency records
        rows = conn.execute(
            "SELECT total_ms, retrieval_ms, scoring_ms, output_ms, result_count "
            "FROM search_latency ORDER BY recorded_at DESC LIMIT ?",
            (window,),
        ).fetchall()

        if not rows:
            return Result(
                status="ok",
                data={
                    "message": "No search latency data recorded yet.",
                    "sample_count": 0,
                },
            )

        # Compute percentiles
        totals = sorted(r[0] for r in rows)
        retrievals = sorted(r[1] for r in rows)
        scorings = sorted(r[2] for r in rows)
        outputs = sorted(r[3] for r in rows)

        def percentile(sorted_vals: list, pct: float) -> float:
            idx = int(len(sorted_vals) * pct / 100)
            idx = min(idx, len(sorted_vals) - 1)
            return round(sorted_vals[idx], 2)

        threshold_ms = config.search.latency_threshold_ms
        p50 = percentile(totals, 50)
        p95 = percentile(totals, 95)
        p99 = percentile(totals, 99)

        stats = {
            "sample_count": len(rows),
            "total_ms": {"p50": p50, "p95": p95, "p99": p99},
            "retrieval_ms": {
                "p50": percentile(retrievals, 50),
                "p95": percentile(retrievals, 95),
                "p99": percentile(retrievals, 99),
            },
            "scoring_ms": {
                "p50": percentile(scorings, 50),
                "p95": percentile(scorings, 95),
                "p99": percentile(scorings, 99),
            },
            "output_ms": {
                "p50": percentile(outputs, 50),
                "p95": percentile(outputs, 95),
                "p99": percentile(outputs, 99),
            },
            "threshold_ms": threshold_ms,
        }

        # Check for degradation
        warning = None
        if p95 > threshold_ms:
            warning = (
                f"WARNING: p95 search latency ({p95:.1f}ms) exceeds threshold "
                f"({threshold_ms:.1f}ms). Consider running `memory neuron prune` "
                f"to archive unused neurons and improve search performance."
            )
            stats["warning"] = warning
            stats["degraded"] = True
        else:
            stats["degraded"] = False

        return Result(status="ok", data=stats)

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
    "health": handle_health,
}

_VERB_DESCRIPTIONS = {
    "info": "Show database identity and configuration",
    "stats": "Show database statistics (counts, sizes)",
    "manifesto": "Show or update the store's memory manifesto (usage guide, not data — rules belong as neurons)",
    "fingerprint": "Show this store's fingerprint, project name, and db_path",
    "stores": "List all known stores from ~/.memory/stores.json",
    "consolidate": "Mark unconsolidated neurons as consolidated (lifecycle trigger)",
    "health": "Search latency stats (p50/p95/p99) with degradation warnings",
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
    "consolidate": [],
    "health": [
        {"name": "--window", "type": "int", "default": 100, "desc": "Number of recent searches to analyze (default 100)"},
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
