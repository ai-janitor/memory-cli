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
#   - Parse init-specific flags (--force, --global)
#   - Default (no flags): create LOCAL project store at .memory/ in cwd
#   - --global: create GLOBAL store at ~/.memory/
#   - --force: overwrite existing config (preserve DB)
#   - These can be combined: memory init --global --force
#   - Delegate to config/storage layer to create database and config
#   - Return a Result object for the output formatter
#   - Handle already-initialized case (error unless --force)
# ORGANIZATION:
#   1. handle_init() — main handler
#   2. _parse_init_flags() — extract init-specific flags
# =============================================================================

from __future__ import annotations

from pathlib import Path
from typing import List, Any

# from memory_cli.cli.global_flags_format_config_db import GlobalFlags


# =============================================================================
# INIT HANDLER
# =============================================================================
def handle_init(args: List[str], global_flags: Any) -> Any:
    """Handle `memory init [flags]` command.

    Supported invocations:
        memory init             — creates LOCAL project store at .memory/ in cwd
        memory init --global    — creates GLOBAL store at ~/.memory/
        memory init --force     — overwrite existing config (preserve DB)
        memory init --global --force — combine both flags

    Args:
        args: Remaining tokens after "init" (e.g., ["--force", "--global"]).
        global_flags: Parsed global flags (--db, --config may override defaults).

    Returns:
        Result object with status, data, and error fields.

    Pseudo-logic:
    1. Parse init-specific flags from args:
       - --force: overwrite existing config, preserve DB (default False)
       - --global: create ~/.memory/ instead of .memory/ in cwd (default False)
       - --db and --config may also come from global_flags
    2. Determine whether this is a local (project) or global init:
       a. Default (no --global flag): project=True -> .memory/ in cwd (LOCAL)
       b. With --global flag: project=False -> ~/.memory/ (GLOBAL)
    3. Delegate to init_memory_store(project=, force=):
       a. Create database with schema (tables, indexes, vec extension)
       b. Create config file with defaults if it doesn't exist
    4. Return success result with data:
       {"database": str(db_path), "config": str(config_path), "created": True}
    """
    from memory_cli.cli.output_envelope_json_and_text import Result

    init_flags = _parse_init_flags(list(args))
    force = init_flags["force"]
    global_store = init_flags["global_store"]

    # --global may also come from global_flags (parsed at top level before init sees args)
    if getattr(global_flags, "global_only", False):
        global_store = True

    # Default is LOCAL (project=True). --global flips to GLOBAL (project=False).
    project = not global_store

    # Delegate to init_memory_store — it handles path resolution, directory
    # creation, config writing, DB creation, and post-init instructions.
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
    except Exception as exc:
        return Result(
            status="error",
            error=str(exc),
        )


# =============================================================================
# INIT FLAG PARSER
# =============================================================================
def _parse_init_flags(args: List[str]) -> dict:
    """Extract init-specific flags from the argument list.

    Recognized flags:
        --force        : overwrite existing config (preserve DB)
        --global       : create GLOBAL store at ~/.memory/
                         (without --global, creates LOCAL store at .memory/ in cwd)

    Args:
        args: Tokens after "init".

    Returns:
        Dict with parsed flags: {"force": bool, "global_store": bool}
        (Uses "global_store" because "global" is a Python keyword.)

    Pseudo-logic:
    1. Scan args for "--force" -> set force=True, remove from list
    2. Scan args for "--global" -> set global_store=True, remove from list
    3. If any unrecognized flags remain (tokens starting with "--"),
       raise error "Unknown flag for init: {flag}"
    4. If any positional args remain, raise error
       "init takes no positional arguments"
    5. Return {"force": force, "global_store": global_store}
    """
    remaining = list(args)
    force = False
    global_store = False
    if "--force" in remaining:
        force = True
        remaining.remove("--force")
    if "--global" in remaining:
        global_store = True
        remaining.remove("--global")
    for token in remaining:
        if token.startswith("--"):
            raise ValueError(f"Unknown flag for init: {token}")
    if remaining:
        raise ValueError("init takes no positional arguments")
    return {"force": force, "global_store": global_store}
