# =============================================================================
# Module: __main__.py
# Purpose: Enable `python -m memory_cli` invocation (standard Python pattern).
# Rationale: Complements the console_scripts entry point so the CLI is reachable
#   via both `memory` (after install) and `python -m memory_cli` (no install).
# Responsibility: Import and call the main() entry point.
# =============================================================================

from memory_cli.cli.entrypoint_and_argv_dispatch import main

main()
