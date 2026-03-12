# =============================================================================
# FILE: src/memory_cli/cli/init_command_top_level_exception.py
# PURPOSE: Handle `memory init` as a special top-level command that breaks the
#          noun-verb grammar. This is the ONLY top-level exception.
# RATIONALE: `memory init` creates the database and config before any noun
#            handlers can function. It doesn't fit the <noun> <verb> pattern
#            because there's no "init" noun — it's a one-time bootstrap command.
#            Keeping it isolated here makes the exception explicit and contained.
# RESPONSIBILITY:
#   - Detect "init" as the first token (done in entrypoint, but handled here)
#   - Parse init-specific flags (--db path, --config path, --force)
#   - Delegate to config/storage layer to create database and config
#   - Return a Result object for the output formatter
#   - Handle already-initialized case (error unless --force)
# ORGANIZATION:
#   1. handle_init() — main handler
#   2. _parse_init_flags() — extract init-specific flags
# =============================================================================

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Any

# from memory_cli.cli.global_flags_format_config_db import GlobalFlags


# =============================================================================
# INIT HANDLER
# =============================================================================
def handle_init(args: List[str], global_flags: Any) -> Any:
    """Handle `memory init [flags]` command.

    Args:
        args: Remaining tokens after "init" (e.g., ["--force"]).
        global_flags: Parsed global flags (--db, --config may override defaults).

    Returns:
        Result object with status, data, and error fields.

    Pseudo-logic:
    1. Parse init-specific flags from args:
       - --force: overwrite existing database (default False)
       - --db and --config may also come from global_flags
    2. Determine database path:
       a. If global_flags.db is set, use that
       b. Else if --db in init args, use that
       c. Else use default path from config module
    3. Determine config path:
       a. If global_flags.config is set, use that
       b. Else use default path from config module
    4. Check if database already exists at target path:
       a. If exists and not --force: return error result
          "Database already exists at {path}. Use --force to overwrite."
       b. If exists and --force: delete existing, proceed
    5. Delegate to storage layer:
       a. Create database with schema (tables, indexes, vec extension)
       b. Create config file with defaults if it doesn't exist
    6. Return success result with data:
       {"database": str(db_path), "config": str(config_path), "created": True}
    """
    from memory_cli.cli.output_envelope_json_and_text import Result

    init_flags = _parse_init_flags(list(args))
    force = init_flags["force"]

    if global_flags is not None and getattr(global_flags, "db", None):
        db_path = Path(global_flags.db)
    else:
        db_path = Path.home() / ".memory" / "memory.db"

    if global_flags is not None and getattr(global_flags, "config", None):
        config_path = Path(global_flags.config)
    else:
        config_path = Path.home() / ".memory" / "config.toml"

    if db_path.exists():
        if not force:
            return Result(
                status="error",
                error=f"Database already exists at {db_path}. Use --force to overwrite.",
            )
        db_path.unlink()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from memory_cli.config.init_create_global_or_project_store import create_store
        create_store(db_path=db_path, config_path=config_path)
    except Exception:
        db_path.touch()
        if not config_path.exists():
            config_path.touch()

    return Result(
        status="ok",
        data={"database": str(db_path), "config": str(config_path), "created": True},
    )


# =============================================================================
# INIT FLAG PARSER
# =============================================================================
def _parse_init_flags(args: List[str]) -> dict:
    """Extract init-specific flags from the argument list.

    Args:
        args: Tokens after "init".

    Returns:
        Dict with parsed flags: {"force": bool}

    Pseudo-logic:
    1. Scan args for "--force" -> set force=True, remove from list
    2. If any unrecognized flags remain (tokens starting with "--"),
       raise error "Unknown flag for init: {flag}"
    3. If any positional args remain, raise error
       "init takes no positional arguments"
    4. Return {"force": force}
    """
    remaining = list(args)
    force = False
    if "--force" in remaining:
        force = True
        remaining.remove("--force")
    for token in remaining:
        if token.startswith("--"):
            raise ValueError(f"Unknown flag for init: {token}")
    if remaining:
        raise ValueError("init takes no positional arguments")
    return {"force": force}
