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

from memory_cli.cli.global_flags_format_config_db import parse_global_flags, GlobalFlags
from memory_cli.cli.exit_codes_0_1_2 import EXIT_SUCCESS, EXIT_NOT_FOUND, EXIT_ERROR, exit_with
from memory_cli.cli.help_system_three_levels import show_top_level_help, show_noun_help, show_verb_help, has_help_flag
from memory_cli.cli.init_command_top_level_exception import handle_init
from memory_cli.cli.output_envelope_json_and_text import format_output, write_output, write_error, Result
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
_registry: Dict[str, Any] = {}


def register_noun(name: str, entry: Dict[str, Any]) -> None:
    """Register a noun handler in the dispatch registry.

    Called by each noun_handler module at import time.
    Validates that entry has required keys: verb_map, description.
    Raises ValueError if noun name already registered (no silent overwrite).
    """
    if "verb_map" not in entry:
        raise ValueError(f"Noun entry for '{name}' missing required key: verb_map")
    if "description" not in entry:
        raise ValueError(f"Noun entry for '{name}' missing required key: description")
    if name in _registry:
        raise ValueError(f"Noun '{name}' is already registered")
    _registry[name] = entry


def get_registry() -> Dict[str, Any]:
    """Return the current noun handler registry (read-only copy or reference).

    Used by help system to enumerate available nouns and verbs.
    """
    return _registry


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
    import memory_cli.cli.noun_handlers  # triggers self-registration of all noun handlers
    if argv is None:
        argv = sys.argv[1:]
    try:
        global_flags, remaining_tokens = parse_global_flags(argv)
    except ValueError as exc:
        write_error(str(exc))
        sys.exit(EXIT_ERROR)

    if not remaining_tokens:
        registry = get_registry()
        help_text = show_top_level_help(registry)
        write_output(help_text, stream=sys.stdout)
        sys.exit(EXIT_SUCCESS)

    first_token = remaining_tokens[0]

    if first_token == "init":
        try:
            result = handle_init(remaining_tokens[1:], global_flags)
        except ValueError as exc:
            result = Result(status="error", error=str(exc))
        formatted = format_output(result, global_flags.format)
        write_output(formatted, stream=sys.stdout)
        exit_with(result.status)
        return

    if has_help_flag(remaining_tokens):
        registry = get_registry()
        if len(remaining_tokens) == 1 or remaining_tokens[0] in ("--help", "-h"):
            help_text = show_top_level_help(registry)
        elif len(remaining_tokens) >= 2:
            noun_name = remaining_tokens[0]
            noun_entry = registry.get(noun_name)
            if noun_entry is None:
                help_text = show_top_level_help(registry)
            else:
                non_help = [t for t in remaining_tokens[1:] if t not in ("--help", "-h")]
                if non_help:
                    verb_name = non_help[0]
                    help_text = show_verb_help(noun_name, verb_name, noun_entry)
                else:
                    help_text = show_noun_help(noun_name, noun_entry)
        else:
            help_text = show_top_level_help(registry)
        write_output(help_text, stream=sys.stdout)
        sys.exit(EXIT_SUCCESS)
        return

    try:
        _dispatch(global_flags, remaining_tokens)
    except SystemExit:
        raise
    except Exception as exc:
        _handle_error(exc, global_flags)


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
    noun_name = tokens[0]
    noun_entry = _registry.get(noun_name)
    if noun_entry is None:
        write_error(f"Unknown noun: {noun_name}. Run `memory --help` to see available nouns.")
        sys.exit(EXIT_ERROR)

    if len(tokens) < 2:
        help_text = show_noun_help(noun_name, noun_entry)
        write_output(help_text, stream=sys.stdout)
        sys.exit(EXIT_SUCCESS)

    verb_name = tokens[1]
    verb_map = noun_entry.get("verb_map", {})
    verb_handler = verb_map.get(verb_name)
    if verb_handler is None:
        available = ", ".join(sorted(verb_map.keys()))
        write_error(
            f"Unknown verb '{verb_name}' for noun '{noun_name}'. "
            f"Available verbs: {available}"
        )
        sys.exit(EXIT_ERROR)

    remaining_args = tokens[2:]

    if has_help_flag(remaining_args):
        help_text = show_verb_help(noun_name, verb_name, noun_entry)
        write_output(help_text, stream=sys.stdout)
        sys.exit(EXIT_SUCCESS)

    result = verb_handler(remaining_args, global_flags)
    formatted = format_output(result, global_flags.format)
    write_output(formatted, stream=sys.stdout)
    exit_with(result.status)


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
    error_result = Result(status="error", error=str(exc))
    fmt = getattr(global_flags, "format", "json") if global_flags is not None else "json"
    try:
        formatted = format_output(error_result, fmt)
        write_output(formatted, stream=sys.stderr)
    except Exception:
        sys.stderr.write(f"memory: error: {exc}\n")
        sys.stderr.flush()
    sys.exit(EXIT_ERROR)
