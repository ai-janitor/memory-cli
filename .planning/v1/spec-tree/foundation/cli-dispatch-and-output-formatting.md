# CLI Dispatch & Output Formatting

Covers: noun-verb routing (`memory <noun> <verb> [args]`), help system at three
levels (all nouns, verbs for a noun, flags for a verb), JSON and plain text output
formatting with configurable default, exit code contract (0=success, 1=not found,
2=error), --format flag override.

Requirements traced: §7.1 Grammar, §7.3 Help, §7.4 Output Format.
Dependencies: None (Tier 0). All noun handlers register into this dispatcher.
