# =============================================================================
# Module: arg_parse_extract_positional_and_flags.py
# Purpose: Shared argument parsing utilities for verb handlers. Extracts
#   positional args and --flag values from the args list without pulling in
#   argparse (keeps the CLI hand-rolled and consistent with global flag parsing).
# Rationale: Every verb handler needs to parse a mix of positional args and
#   optional flags from List[str]. Duplicating this logic 20+ times is fragile.
#   These helpers mirror the _consume_flag pattern in global_flags_format_config_db.py.
# Responsibility:
#   - extract_flag: pull --name <value> pair from args
#   - extract_bool_flag: pull --name presence flag from args
#   - require_positional: extract one required positional arg with error message
# Organization: Three stateless functions, no side effects
# =============================================================================

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple, TypeVar

T = TypeVar("T")


def extract_flag(
    args: List[str],
    name: str,
    type_fn: Callable[[str], T] = str,
    default: Optional[T] = None,
) -> Tuple[Optional[T], List[str]]:
    """Extract a --name <value> flag pair from args.

    Args:
        args: Token list to scan.
        name: Flag name including -- prefix (e.g., "--limit").
        type_fn: Conversion function for the value (e.g., int, float).
        default: Value to return if flag not found.

    Returns:
        Tuple of (parsed_value_or_default, remaining_args).

    Raises:
        ValueError: If flag is present but value is missing or type conversion fails.
    """
    remaining = list(args)
    if name not in remaining:
        return default, remaining

    idx = remaining.index(name)
    if idx + 1 >= len(remaining):
        raise ValueError(f"Flag {name} requires a value")

    raw_value = remaining[idx + 1]
    remaining.pop(idx)  # remove flag name
    remaining.pop(idx)  # remove flag value (now at same index)

    try:
        return type_fn(raw_value), remaining
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid value for {name}: {raw_value} ({e})")


def extract_bool_flag(args: List[str], name: str) -> Tuple[bool, List[str]]:
    """Extract a boolean --name flag (presence = True).

    Args:
        args: Token list to scan.
        name: Flag name including -- prefix (e.g., "--archived").

    Returns:
        Tuple of (True_if_present, remaining_args).
    """
    remaining = list(args)
    if name not in remaining:
        return False, remaining

    remaining.remove(name)
    return True, remaining


def require_positional(args: List[str], name: str) -> Tuple[str, List[str]]:
    """Extract one required positional argument from the front.

    Args:
        args: Token list — first non-flag token is consumed.
        name: Human-readable name for error messages (e.g., "content", "neuron_id").

    Returns:
        Tuple of (value, remaining_args).

    Raises:
        ValueError: If no positional argument is available.
    """
    if not args or args[0].startswith("--"):
        raise ValueError(f"Missing required argument: {name}")

    return args[0], args[1:]
