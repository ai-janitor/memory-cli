# =============================================================================
# FILE: src/memory_cli/cli/__init__.py
# PURPOSE: Package initializer for the CLI dispatch layer. Exposes the public
#          API surface that the console_scripts entry point and tests import.
# RATIONALE: Single import point keeps coupling low — callers do
#            `from memory_cli.cli import main` instead of reaching into
#            submodules. Also lets us control what leaks out of the package.
# RESPONSIBILITY: Re-export exactly the symbols that external code needs.
#                 Nothing else should be importable at this level.
# ORGANIZATION: Flat re-exports grouped by purpose (entry, formatting, codes).
# =============================================================================

# --- Public API exports ---
from memory_cli.cli.entrypoint_and_argv_dispatch import main
from memory_cli.cli.exit_codes_0_1_2 import EXIT_SUCCESS, EXIT_NOT_FOUND, EXIT_ERROR
from memory_cli.cli.output_envelope_json_and_text import format_output

# __all__ will gate `from memory_cli.cli import *`
__all__ = ["main", "EXIT_SUCCESS", "EXIT_NOT_FOUND", "EXIT_ERROR", "format_output"]
