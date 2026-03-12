# =============================================================================
# FILE: src/memory_cli/cli/entrypoint_and_argv_dispatch.py
# PURPOSE: Main entry point for `memory` CLI. Parses sys.argv, strips global
#          flags, resolves noun/verb pair, dispatches to the correct handler.
# RATIONALE: All routing lives here so noun handlers stay pure — they receive
#            validated args and never touch argv directly. This is the only
#            module that imports sys.argv.
# RESPONSIBILITY:
#   - Parse raw argv into (global_flags, noun, verb, remaining_args)
#   - Handle special cases: `memory init`, `memory --help`, `memory <noun> --help`
#   - Look up noun in handler registry, look up verb in noun's verb map
#   - Invoke handler, catch exceptions, format output, set exit code
#   - Print to stdout (data) or stderr (diagnostics), then sys.exit
# ORGANIZATION:
#   1. Imports and type aliases
#   2. Noun handler registry (populated by noun_handlers package)
#   3. main() — the console_scripts entry point
#   4. _dispatch() — internal routing logic
#   5. _handle_error() — unhandled exception fallback
# =============================================================================

from __future__ import annotations

import sys
from typing import Dict, List, Optional, Any, Callable

# from memory_cli.cli.global_flags_format_config_db import parse_global_flags, GlobalFlags
# from memory_cli.cli.exit_codes_0_1_2 import EXIT_SUCCESS, EXIT_NOT_FOUND, EXIT_ERROR, exit_with
# from memory_cli.cli.help_system_three_levels import show_top_level_help, show_noun_help, show_verb_help
# from memory_cli.cli.init_command_top_level_exception import handle_init
# from memory_cli.cli.output_envelope_json_and_text import format_output, write_output
# NOTE: get_registry() is defined in THIS module (line 65), not imported from noun_handlers.
# Importing noun_handlers triggers self-registration of all noun handlers into _registry.


# -----------------------------------------------------------------------------
# Type alias for a noun handler's verb map
# -----------------------------------------------------------------------------
# VerbHandler = Callable taking (remaining_args: List[str], global_flags: GlobalFlags) -> Result
# NounEntry = dict with keys: verb_map, description, flag_defs
# Registry = Dict[str, NounEntry]


# =============================================================================
# NOUN HANDLER REGISTRY
# =============================================================================
# — Populated at import time by noun_handlers package
# — Maps noun name (str) -> NounEntry
# — Each NounEntry contains:
#     "verb_map": Dict[str, VerbHandler]   — verb name -> callable
#     "description": str                    — one-line noun description for help
#     "flag_defs": Dict[str, FlagDef]       — verb-specific flag definitions
# _registry: Registry = {}


def register_noun(name: str, entry: Dict[str, Any]) -> None:
    """Register a noun handler in the dispatch registry.

    Called by each noun_handler module at import time.
    Validates that entry has required keys: verb_map, description.
    Raises ValueError if noun name already registered (no silent overwrite).
    """
    pass


def get_registry() -> Dict[str, Any]:
    """Return the current noun handler registry (read-only copy or reference).

    Used by help system to enumerate available nouns and verbs.
    """
    pass


# =============================================================================
# MAIN ENTRY POINT — console_scripts target
# =============================================================================
def main(argv: Optional[List[str]] = None) -> None:
    """Entry point for `memory` CLI. Called by console_scripts or directly.

    Args:
        argv: Override for sys.argv[1:]. None means use sys.argv[1:].

    Pseudo-logic:
    1. If argv is None, use sys.argv[1:]
    2. Call parse_global_flags(argv) -> (global_flags, remaining_tokens)
    3. If remaining_tokens is empty:
       a. registry = get_registry()   (defined in this module, line 65)
       b. If --help in global_flags, show_top_level_help(registry), exit 0
       c. Else show_top_level_help(registry) (no args = help), exit 0
    4. Extract first token as candidate noun
    5. SPECIAL CASE: if first token is "init", delegate to handle_init()
    6. SPECIAL CASE: if --help anywhere in remaining_tokens, route to help
    7. Call _dispatch(global_flags, remaining_tokens)
    8. Catch all exceptions in _handle_error(), format, exit 2
    """
    pass


# =============================================================================
# INTERNAL DISPATCH — noun/verb resolution and handler invocation
# =============================================================================
def _dispatch(global_flags: Any, tokens: List[str]) -> None:
    """Resolve noun and verb from tokens, invoke the handler, format output.

    Args:
        global_flags: Parsed global flags (format, config, db).
        tokens: Remaining argv tokens after global flag stripping.

    Pseudo-logic:
    1. noun_name = tokens[0]
    2. Look up noun_name in _registry
       - If not found: print error "Unknown noun: {noun_name}", suggest --help, exit 2
    3. If len(tokens) < 2:
       - Show noun-level help for this noun, exit 0
    4. verb_name = tokens[1]
    5. Look up verb_name in noun_entry["verb_map"]
       - If not found: print error "Unknown verb '{verb_name}' for noun '{noun_name}'",
         list available verbs, exit 2
    6. remaining_args = tokens[2:]
    7. Check if --help in remaining_args:
       - If yes: show verb-level help, exit 0
    8. result = verb_handler(remaining_args, global_flags)
    9. formatted = format_output(result, global_flags.format)
    10. write_output(formatted, stream=sys.stdout)
    11. exit_with(result.status)
    """
    pass


# =============================================================================
# ERROR HANDLING — unhandled exception fallback
# =============================================================================
def _handle_error(exc: Exception, global_flags: Any) -> None:
    """Last-resort handler for unhandled exceptions during dispatch.

    Pseudo-logic:
    1. Build error result with status="error", error=str(exc)
    2. Format according to global_flags.format (default json)
       - If format itself fails, fall back to plain text on stderr
    3. Write to stderr
    4. Exit 2
    """
    pass
