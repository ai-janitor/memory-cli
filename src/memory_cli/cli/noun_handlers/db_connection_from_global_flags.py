# =============================================================================
# Module: db_connection_from_global_flags.py
# Purpose: Shared utility to get a DB connection from global flags. Every verb
#   handler needs a DB connection — this centralizes config resolution, DB open,
#   and migration execution so handlers stay thin.
# Rationale: Without this, every handler would duplicate the same 5-line pattern
#   of config loading + DB connection. Centralizing also ensures migrations run
#   consistently before any handler touches the DB.
# Responsibility:
#   - Resolve config from global flags (--config and --db overrides)
#   - Open DB connection via open_connection()
#   - Run pending migrations to ensure schema is current
#   - Return (conn, config) tuple for handlers that need config
# Organization: Two public functions — get_connection_and_config, get_connection
# =============================================================================

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, List, Tuple

from memory_cli.config import load_config, MemoryConfig, ConfigLoadError
from memory_cli.db import open_connection, run_pending_migrations, read_schema_version

# Target schema version — must match MIGRATION_REGISTRY in db/migrations/__init__.py
_TARGET_VERSION = 5


def get_connection_and_config(global_flags: Any) -> Tuple[sqlite3.Connection, MemoryConfig]:
    """Load config respecting --config, --db, and --global overrides, open DB, run migrations.

    Args:
        global_flags: Parsed GlobalFlags with .config, .db, and .global_only attributes.

    Returns:
        Tuple of (sqlite3.Connection, MemoryConfig).

    Raises:
        ConfigLoadError: If config cannot be loaded.
        sqlite3.Error: If DB connection fails.
    """
    config_override = getattr(global_flags, "config", None)
    db_override = getattr(global_flags, "db", None)
    global_only = getattr(global_flags, "global_only", False)
    # If --global flag set, force loading from the global store
    if global_only and config_override is None and db_override is None:
        from memory_cli.config.config_path_resolution_ancestor_walk import _global_config_path
        config_override = str(_global_config_path())
    config = load_config(config_override=config_override, db_override=db_override)
    conn = open_connection(config.db_path)
    # Load sqlite-vec extension before migrations (vec0 virtual tables need it)
    from memory_cli.db.extension_loader_sqlite_vec import load_sqlite_vec
    load_sqlite_vec(conn)
    current = read_schema_version(conn)
    if current < _TARGET_VERSION:
        run_pending_migrations(conn, current, _TARGET_VERSION)
    return conn, config


def get_connection(global_flags: Any) -> sqlite3.Connection:
    """Shortcut when config object is not needed by the handler.

    Args:
        global_flags: Parsed GlobalFlags with .config and .db attributes.

    Returns:
        sqlite3.Connection ready for queries.
    """
    conn, _ = get_connection_and_config(global_flags)
    return conn


def get_connection_and_scope(global_flags: Any) -> Tuple[sqlite3.Connection, str]:
    """Get DB connection and scope string ("LOCAL" or "GLOBAL").

    Determines scope from the resolved config.db_path:
    - If db_path starts with ~/.memory/ (expanded) -> "GLOBAL"
    - Otherwise -> "LOCAL"

    Args:
        global_flags: Parsed GlobalFlags with .config and .db attributes.

    Returns:
        Tuple of (sqlite3.Connection, scope_str).
    """
    conn, config = get_connection_and_config(global_flags)
    from memory_cli.cli.scoped_handle_format_and_parse import detect_scope
    scope = detect_scope(config.db_path)
    return conn, scope


def _open_config_path(config_path: Path, db_override: str | None = None) -> Tuple[sqlite3.Connection, str]:
    """Open a DB connection from a specific config path and return (conn, scope).

    Internal helper for get_layered_connections(). Loads the config from the
    given path, opens the DB, runs migrations, and detects scope.

    Args:
        config_path: Absolute path to a config.json file.
        db_override: Optional --db override (only applied if provided).

    Returns:
        Tuple of (sqlite3.Connection, scope_str).
    """
    config = load_config(config_override=str(config_path), db_override=db_override)
    conn = open_connection(config.db_path)
    from memory_cli.db.extension_loader_sqlite_vec import load_sqlite_vec
    load_sqlite_vec(conn)
    current = read_schema_version(conn)
    if current < _TARGET_VERSION:
        run_pending_migrations(conn, current, _TARGET_VERSION)
    from memory_cli.cli.scoped_handle_format_and_parse import detect_scope
    scope = detect_scope(config.db_path)
    return conn, scope


def get_layered_connections(global_flags: Any) -> List[Tuple[sqlite3.Connection, str]]:
    """Get layered DB connections for PATH-style search: local first, then global.

    When both a local .memory/ store and a global ~/.memory/ store exist,
    returns connections to BOTH stores. Local is always first in the list
    (higher priority). When only one exists, returns just that one.

    The --global flag overrides: if set, only the global store is returned
    even if local exists. --config and --db overrides bypass layering entirely
    (single connection, like the old behavior).

    Args:
        global_flags: Parsed GlobalFlags with .config, .db, .global_only attributes.

    Returns:
        List of (sqlite3.Connection, scope_str) tuples.
        Order: LOCAL first (if exists), GLOBAL second (if exists).
        At least one entry if any store exists.

    Raises:
        ConfigLoadError: If no store can be found at all.
    """
    config_override = getattr(global_flags, "config", None)
    db_override = getattr(global_flags, "db", None)
    global_only = getattr(global_flags, "global_only", False)

    # If explicit --config or --db override provided, fall back to single-connection
    # behavior — the user is explicitly targeting a specific store.
    if config_override is not None or db_override is not None:
        conn, scope = get_connection_and_scope(global_flags)
        return [(conn, scope)]

    # If --global flag set, only return the global store
    if global_only:
        from memory_cli.config.config_path_resolution_ancestor_walk import _global_config_path
        global_path = _global_config_path()
        if not global_path.is_file():
            raise ConfigLoadError(
                stage="resolve",
                details="No global memory store found at ~/.memory/. Run `memory init --global`.",
            )
        conn, scope = _open_config_path(global_path)
        return [(conn, scope)]

    # Layered mode: resolve all config paths and open each
    from memory_cli.config.config_path_resolution_ancestor_walk import resolve_all_config_paths
    config_paths = resolve_all_config_paths()

    if not config_paths:
        raise ConfigLoadError(
            stage="resolve",
            details="No memory config found. Run `memory init` to create a new memory store.",
        )

    connections: List[Tuple[sqlite3.Connection, str]] = []
    for config_path, scope in config_paths:
        conn, resolved_scope = _open_config_path(config_path)
        connections.append((conn, resolved_scope))

    return connections
