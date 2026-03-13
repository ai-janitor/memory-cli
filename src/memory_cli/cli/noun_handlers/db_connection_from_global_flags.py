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
from typing import Any, Tuple

from memory_cli.config import load_config, MemoryConfig, ConfigLoadError
from memory_cli.db import open_connection, run_pending_migrations, read_schema_version

# Target schema version — must match MIGRATION_REGISTRY in db/migrations/__init__.py
_TARGET_VERSION = 3


def get_connection_and_config(global_flags: Any) -> Tuple[sqlite3.Connection, MemoryConfig]:
    """Load config respecting --config and --db overrides, open DB, run migrations.

    Args:
        global_flags: Parsed GlobalFlags with .config and .db attributes.

    Returns:
        Tuple of (sqlite3.Connection, MemoryConfig).

    Raises:
        ConfigLoadError: If config cannot be loaded.
        sqlite3.Error: If DB connection fails.
    """
    config_override = getattr(global_flags, "config", None)
    db_override = getattr(global_flags, "db", None)
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
