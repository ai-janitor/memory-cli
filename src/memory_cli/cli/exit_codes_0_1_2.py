# =============================================================================
# FILE: src/memory_cli/cli/exit_codes_0_1_2.py
# PURPOSE: Define the three exit codes used by memory-cli and provide a helper
#          to call sys.exit with the correct code.
# RATIONALE: Exit codes are a contract with calling processes (scripts, agents,
#            CI). Centralizing them prevents magic numbers scattered across the
#            codebase and makes the contract explicit and testable.
# RESPONSIBILITY:
#   - Define EXIT_SUCCESS (0), EXIT_NOT_FOUND (1), EXIT_ERROR (2)
#   - Provide exit_with() helper that maps result status to exit code
#   - Provide status_to_exit_code() for cases where we need the code without exiting
# ORGANIZATION:
#   1. Constants
#   2. Mapping from status string to exit code
#   3. Helper functions
# =============================================================================

from __future__ import annotations

import sys

# =============================================================================
# EXIT CODE CONSTANTS
# =============================================================================
# 0 = success — command completed, data returned (including empty result sets)
# 1 = not found — explicit lookup by ID/key found nothing
# 2 = error — bad input, unknown noun/verb, unhandled exception, DB error
EXIT_SUCCESS: int = 0
EXIT_NOT_FOUND: int = 1
EXIT_ERROR: int = 2

# =============================================================================
# STATUS STRING -> EXIT CODE MAPPING
# =============================================================================
# Maps the "status" field in the JSON envelope to the correct exit code.
# "ok"        -> 0  (includes empty list results — empty is still success)
# "not_found" -> 1  (explicit ID lookup returned nothing)
# "error"     -> 2  (something went wrong)
_STATUS_TO_CODE = {
    "ok": EXIT_SUCCESS,
    "not_found": EXIT_NOT_FOUND,
    "error": EXIT_ERROR,
}


def status_to_exit_code(status: str) -> int:
    """Convert a result status string to its exit code.

    Args:
        status: One of "ok", "not_found", "error".

    Returns:
        The integer exit code (0, 1, or 2).

    Pseudo-logic:
    1. Look up status in _STATUS_TO_CODE
    2. If status not recognized, default to EXIT_ERROR (2)
       — unknown status is itself an error condition
    3. Return the code
    """
    return _STATUS_TO_CODE.get(status, EXIT_ERROR)


def exit_with(status: str) -> None:
    """Call sys.exit with the exit code corresponding to the given status.

    Args:
        status: One of "ok", "not_found", "error".

    Pseudo-logic:
    1. code = status_to_exit_code(status)
    2. sys.exit(code)

    Note: This function never returns (sys.exit raises SystemExit).
    """
    code = status_to_exit_code(status)
    sys.exit(code)
