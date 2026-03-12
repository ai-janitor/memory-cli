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
    pass


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
    pass
