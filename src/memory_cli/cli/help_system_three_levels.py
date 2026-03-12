# =============================================================================
# FILE: src/memory_cli/cli/help_system_three_levels.py
# PURPOSE: Generate help text at three levels: top-level (all nouns), noun-level
#          (all verbs for a noun), and verb-level (flags/args for a specific verb).
# RATIONALE: Help is always plain text regardless of --format flag, always exits 0.
#            Three levels match the noun-verb grammar depth. The help system reads
#            from the noun handler registry so it stays in sync automatically.
# RESPONSIBILITY:
#   - Top-level help: list all nouns with descriptions, show global flags
#   - Noun-level help: list all verbs for a noun with descriptions
#   - Verb-level help: show usage, flags, args for a specific verb
#   - Always output plain text to stdout
#   - Always exit 0 after displaying help
# ORGANIZATION:
#   1. show_top_level_help() — `memory --help` or `memory` with no args
#   2. show_noun_help() — `memory <noun> --help` or `memory <noun>` with no verb
#   3. show_verb_help() — `memory <noun> <verb> --help`
#   4. _format_section() — helper to format aligned columns
#   5. has_help_flag() — detect --help anywhere in token stream
# =============================================================================

from __future__ import annotations

import sys
from typing import Dict, List, Any


# =============================================================================
# HELP DETECTION
# =============================================================================
def has_help_flag(tokens: List[str]) -> bool:
    """Check if --help or -h appears anywhere in the token stream.

    Args:
        tokens: Remaining argv tokens (after global flag stripping).

    Returns:
        True if --help or -h is present.

    Pseudo-logic:
    1. Scan tokens for "--help" or "-h"
    2. Return True if found, False otherwise
    Note: --help is checked BEFORE noun/verb resolution, so it takes priority
    """
    pass


# =============================================================================
# TOP-LEVEL HELP — `memory` or `memory --help`
# =============================================================================
def show_top_level_help(registry: Dict[str, Any]) -> str:
    """Generate top-level help text listing all nouns and global flags.

    Args:
        registry: The noun handler registry from entrypoint.

    Returns:
        Formatted help string (plain text, no ANSI).

    Pseudo-logic:
    1. Build header: "memory — graph-based memory CLI for AI agents"
    2. Build usage line: "Usage: memory <noun> <verb> [args] [flags]"
    3. Build special commands section:
       - "memory init" — initialize a new memory database
    4. Build nouns section:
       - For each noun in registry (sorted alphabetically):
         - Show noun name and its description, aligned in columns
    5. Build global flags section:
       - --format <json|text>  Output format (default: json)
       - --config <path>       Config file path
       - --db <path>           Database file path
       - --help                Show help
    6. Return assembled string
    """
    pass


# =============================================================================
# NOUN-LEVEL HELP — `memory <noun>` or `memory <noun> --help`
# =============================================================================
def show_noun_help(noun_name: str, noun_entry: Dict[str, Any]) -> str:
    """Generate noun-level help text listing all verbs for a noun.

    Args:
        noun_name: The noun (e.g., "neuron").
        noun_entry: The registry entry for this noun.

    Returns:
        Formatted help string (plain text, no ANSI).

    Pseudo-logic:
    1. Build header: "memory {noun_name} — {noun_entry.description}"
    2. Build usage line: "Usage: memory {noun_name} <verb> [args] [flags]"
    3. Build verbs section:
       - For each verb in noun_entry["verb_map"] (sorted alphabetically):
         - Show verb name and its description, aligned in columns
    4. Build "Run `memory {noun_name} <verb> --help` for verb-specific help"
    5. Return assembled string
    """
    pass


# =============================================================================
# VERB-LEVEL HELP — `memory <noun> <verb> --help`
# =============================================================================
def show_verb_help(noun_name: str, verb_name: str, noun_entry: Dict[str, Any]) -> str:
    """Generate verb-level help text showing usage, flags, and args.

    Args:
        noun_name: The noun (e.g., "neuron").
        verb_name: The verb (e.g., "add").
        noun_entry: The registry entry for this noun.

    Returns:
        Formatted help string (plain text, no ANSI).

    Pseudo-logic:
    1. Look up verb in noun_entry["verb_map"] for metadata
    2. Look up flag_defs for this verb from noun_entry["flag_defs"]
    3. Build header: "memory {noun_name} {verb_name}"
    4. Build description from verb metadata
    5. Build usage line with positional args and optional flags
    6. Build flags section:
       - For each flag_def: show --flag <type>, description, default
    7. Build examples section if verb has examples in metadata
    8. Return assembled string
    """
    pass


# =============================================================================
# HELPER: FORMAT ALIGNED COLUMNS
# =============================================================================
def _format_section(title: str, items: List[tuple]) -> str:
    """Format a section with a title and aligned two-column items.

    Args:
        title: Section header (e.g., "Nouns:", "Verbs:").
        items: List of (name, description) tuples.

    Returns:
        Formatted section string.

    Pseudo-logic:
    1. Find max width of first column for alignment
    2. Pad to at least 2 spaces between columns
    3. Build lines: "  {name:<width}  {description}"
    4. Prepend title line
    5. Return joined string
    """
    pass
