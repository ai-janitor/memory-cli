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
    return "--help" in tokens or "-h" in tokens


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
    lines = [
        "memory — graph-based memory CLI for AI agents",
        "",
        "Usage: memory <noun> <verb> [args] [flags]",
        "",
        "Quick capture:  memory neuron add \"deploy script is in scripts/deploy.sh\"",
        "Structured:     memory batch load graph.yaml",
        "",
        "neuron add is the inbox — fast, one fact, no structure.",
        "batch load is the filing cabinet — multiple facts with edges between them.",
        "Edges make search work: spreading activation traverses connections.",
        "",
        "Graph navigation:",
        "  Your memory graph is a mansion. The gate neuron is the front door —",
        "  the most connected neuron, your entry point to navigate the graph.",
        "  Run `memory gate show` to find your front door.",
        "  Run `memory manpage front-door` to learn the mansion pattern.",
        "",
    ]
    special_section = _format_section(
        "Special commands:",
        [("memory init", "Initialize a new memory database")],
    )
    lines.append(special_section)
    lines.append("")
    noun_items = [
        (noun, entry.get("description", ""))
        for noun, entry in sorted(registry.items())
    ]
    nouns_section = _format_section("Nouns:", noun_items)
    lines.append(nouns_section)
    lines.append("")
    flags_section = _format_section(
        "Global flags:",
        [
            ("--format <json|text>", "Output format (default: json)"),
            ("--config <path>", "Config file path"),
            ("--db <path>", "Database file path"),
            ("--help", "Show help"),
            ("--version", "Show version"),
        ],
    )
    lines.append(flags_section)
    return "\n".join(lines)


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
    description = noun_entry.get("description", "")
    verb_descriptions = noun_entry.get("verb_descriptions", {})
    verb_map = noun_entry.get("verb_map", {})
    lines = [
        f"memory {noun_name} — {description}",
        "",
        f"Usage: memory {noun_name} <verb> [args] [flags]",
        "",
    ]
    verb_items = [
        (verb, verb_descriptions.get(verb, ""))
        for verb in sorted(verb_map.keys())
    ]
    verbs_section = _format_section("Verbs:", verb_items)
    lines.append(verbs_section)
    lines.append("")
    lines.append(f"Run `memory {noun_name} <verb> --help` for verb-specific help.")
    return "\n".join(lines)


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
    verb_descriptions = noun_entry.get("verb_descriptions", {})
    flag_defs = noun_entry.get("flag_defs", {})
    description = verb_descriptions.get(verb_name, "")
    verb_flags = flag_defs.get(verb_name, [])
    lines = [
        f"memory {noun_name} {verb_name}",
        "",
    ]
    if description:
        lines.append(description)
        lines.append("")
    lines.append(f"Usage: memory {noun_name} {verb_name} [args] [flags]")
    if verb_flags:
        lines.append("")
        flag_items = []
        for fd in verb_flags:
            flag_type = fd.get("type", "str")
            flag_name = fd.get("name", "")
            flag_desc = fd.get("desc", "")
            default = fd.get("default")
            if default is not None:
                flag_desc = f"{flag_desc} (default: {default})"
            flag_items.append((f"{flag_name} <{flag_type}>", flag_desc))
        flags_section = _format_section("Flags:", flag_items)
        lines.append(flags_section)
    return "\n".join(lines)


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
    if not items:
        return title
    col_width = max(len(name) for name, _ in items)
    lines = [title]
    for name, desc in items:
        lines.append(f"  {name:<{col_width}}  {desc}")
    return "\n".join(lines)
