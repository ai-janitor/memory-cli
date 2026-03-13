# =============================================================================
# FILE: src/memory_cli/cli/global_flags_format_config_db.py
# PURPOSE: Parse and strip global flags (--format, --config, --db) from the
#          argv token stream before noun/verb dispatch.
# RATIONALE: Global flags must be removed before the noun handler sees argv,
#            otherwise "--format json" looks like an unknown positional arg to
#            the noun handler. Parsing them first also means every handler gets
#            a clean, uniform GlobalFlags object.
# RESPONSIBILITY:
#   - Define the GlobalFlags dataclass (format, config path, db path)
#   - Parse --format, --config, --db from anywhere in the token stream
#   - Return (GlobalFlags, remaining_tokens) with flags stripped out
#   - Apply defaults: format="json", config=None, db=None
# ORGANIZATION:
#   1. GlobalFlags dataclass
#   2. parse_global_flags() — the main function
#   3. _consume_flag() — helper to extract a --key value pair from token list
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


# =============================================================================
# GLOBAL FLAGS DATA CLASS
# =============================================================================
@dataclass
class GlobalFlags:
    """Parsed global flags available to all handlers.

    Attributes:
        format: Output format — "json" or "text". Default "json".
        config: Path to config file override. None means use default location.
        db: Path to SQLite database override. None means use default location.
        global_only: When True, only query/write the global ~/.memory/ store.
            Skips local .memory/ even if it exists. The escape hatch for
            layered PATH-style search.
    """
    format: str = "json"
    config: Optional[str] = None
    db: Optional[str] = None
    global_only: bool = False


# =============================================================================
# MAIN PARSER
# =============================================================================
def parse_global_flags(argv: List[str]) -> Tuple[GlobalFlags, List[str]]:
    """Extract global flags from argv and return cleaned token list.

    Args:
        argv: Raw token list (sys.argv[1:] or override).

    Returns:
        Tuple of (GlobalFlags with parsed values, remaining tokens).

    Pseudo-logic:
    1. Make a mutable copy of argv
    2. Call _consume_flag(tokens, "--format") -> (format_value, tokens)
       - If format_value not in ("json", "text", None):
         raise error "Invalid --format value: {format_value}"
       - If None, default to "json"
    3. Call _consume_flag(tokens, "--config") -> (config_value, tokens)
    4. Call _consume_flag(tokens, "--db") -> (db_value, tokens)
    5. Build GlobalFlags(format=..., config=..., db=...)
    6. Return (flags, remaining_tokens)

    Edge cases:
    - E-8: --format without a value (next token is another flag or end of list)
      -> treat as error, not as boolean flag
    - --format appears multiple times: last one wins (or error — TBD)
    - Flag values that look like nouns (e.g., --format neuron) are consumed
      as the flag value — user error, but we parse greedily
    """
    tokens = list(argv)
    format_value, tokens = _consume_flag(tokens, "--format")
    if format_value is not None and format_value not in ("json", "text"):
        raise ValueError(f"Invalid --format value: {format_value}")
    if format_value is None:
        format_value = "json"
    config_value, tokens = _consume_flag(tokens, "--config")
    db_value, tokens = _consume_flag(tokens, "--db")
    # --global is a boolean flag (no value) — consume it manually
    global_only = False
    if "--global" in tokens:
        tokens = [t for t in tokens if t != "--global"]
        global_only = True
    flags = GlobalFlags(format=format_value, config=config_value, db=db_value, global_only=global_only)
    return flags, tokens


# =============================================================================
# HELPER: CONSUME A SINGLE FLAG + VALUE PAIR
# =============================================================================
def _consume_flag(tokens: List[str], flag_name: str) -> Tuple[Optional[str], List[str]]:
    """Remove a --flag value pair from the token list.

    Args:
        tokens: Mutable list of tokens.
        flag_name: The flag to look for (e.g., "--format").

    Returns:
        Tuple of (value or None if flag not present, tokens with flag removed).

    Pseudo-logic:
    1. Scan tokens for flag_name
    2. If not found, return (None, tokens unchanged)
    3. If found at index i:
       a. If i+1 >= len(tokens), raise error "Flag {flag_name} requires a value"
       b. value = tokens[i+1]
       c. If value starts with "--", raise error (looks like another flag, not a value)
       d. Remove tokens[i] and tokens[i+1] from list
       e. Return (value, modified tokens)
    4. Handle --flag=value syntax (split on first "="):
       a. If token starts with flag_name + "=", split and extract value
       b. Remove that single token from list
       c. Return (value, modified tokens)
    """
    result = list(tokens)
    prefix = flag_name + "="
    for i, token in enumerate(result):
        if token == flag_name:
            if i + 1 >= len(result):
                raise ValueError(f"Flag {flag_name} requires a value")
            value = result[i + 1]
            if value.startswith("--"):
                raise ValueError(f"Flag {flag_name} requires a value, got another flag: {value}")
            result.pop(i + 1)
            result.pop(i)
            return value, result
        if token.startswith(prefix):
            value = token[len(prefix):]
            result.pop(i)
            return value, result
    return None, result
