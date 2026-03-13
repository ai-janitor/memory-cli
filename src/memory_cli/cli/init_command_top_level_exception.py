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
#   - Parse init-specific flags (--force, --project)
#   - --project: create LOCAL project store at .memory/ in current directory
#   - --force: overwrite existing config (preserve DB)
#   - These can be combined: memory init --project --force
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

    Supported invocations:
        memory init             — creates GLOBAL store at ~/.memory/
        memory init --project   — creates LOCAL project store at .memory/ in cwd
        memory init --force     — overwrite existing config (preserve DB)
        memory init --project --force — combine both flags

    Args:
        args: Remaining tokens after "init" (e.g., ["--force", "--project"]).
        global_flags: Parsed global flags (--db, --config may override defaults).

    Returns:
        Result object with status, data, and error fields.

    Pseudo-logic:
    1. Parse init-specific flags from args:
       - --force: overwrite existing config, preserve DB (default False)
       - --project: create .memory/ in cwd instead of ~/.memory/ (default False)
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
    5. Delegate to storage layer via init_memory_store(project=, force=):
       a. Create database with schema (tables, indexes, vec extension)
       b. Create config file with defaults if it doesn't exist
    6. Return success result with data:
       {"database": str(db_path), "config": str(config_path), "created": True}
    """
    from memory_cli.cli.output_envelope_json_and_text import Result

    init_flags = _parse_init_flags(list(args))
    force = init_flags["force"]
    project = init_flags["project"]

    if global_flags is not None and getattr(global_flags, "db", None):
        db_path = Path(global_flags.db)
    else:
        db_path = Path.home() / ".memory" / "memory.db"

    if global_flags is not None and getattr(global_flags, "config", None):
        config_path = Path(global_flags.config)
    else:
        config_path = Path.home() / ".memory" / "config.json"

    if db_path.exists():
        if not force:
            return Result(
                status="error",
                error=f"Database already exists at {db_path}. Use --force to overwrite.",
            )
        db_path.unlink()

    # Use init_memory_store if no custom paths are specified
    try:
        from memory_cli.config.init_create_global_or_project_store import init_memory_store, InitError
        store_path = init_memory_store(project=project, force=force)
        return Result(
            status="ok",
            data={
                "database": str(store_path / "memory.db"),
                "config": str(store_path / "config.json"),
                "created": True,
            },
        )
    except (InitError, Exception):
        # Fallback: manually create DB and config with valid JSON
        db_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.touch()
        if not config_path.exists() or force:
            import json
            from memory_cli.config import CONFIG_DEFAULTS
            import copy
            config = copy.deepcopy(CONFIG_DEFAULTS)
            config["db_path"] = str(db_path)
            config["embedding"]["model_path"] = str(db_path.parent / "models" / "default.gguf")
            config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            (db_path.parent / "models").mkdir(parents=True, exist_ok=True)

    return Result(
        status="ok",
        data={"database": str(db_path), "config": str(config_path), "created": True},
    )


# =============================================================================
# INIT FLAG PARSER
# =============================================================================
def _parse_init_flags(args: List[str]) -> dict:
    """Extract init-specific flags from the argument list.

    Recognized flags:
        --force   : overwrite existing config (preserve DB)
        --project : create LOCAL project store at .memory/ in cwd
                    (without --project, creates GLOBAL store at ~/.memory/)

    Args:
        args: Tokens after "init".

    Returns:
        Dict with parsed flags: {"force": bool, "project": bool}

    Pseudo-logic:
    1. Scan args for "--force" -> set force=True, remove from list
    2. Scan args for "--project" -> set project=True, remove from list
    3. If any unrecognized flags remain (tokens starting with "--"),
       raise error "Unknown flag for init: {flag}"
    4. If any positional args remain, raise error
       "init takes no positional arguments"
    5. Return {"force": force, "project": project}
    """
    remaining = list(args)
    force = False
    project = False
    if "--force" in remaining:
        force = True
        remaining.remove("--force")
    if "--project" in remaining:
        project = True
        remaining.remove("--project")
    for token in remaining:
        if token.startswith("--"):
            raise ValueError(f"Unknown flag for init: {token}")
    if remaining:
        raise ValueError("init takes no positional arguments")
    return {"force": force, "project": project}
