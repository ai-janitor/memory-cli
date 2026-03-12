# =============================================================================
# dimension_drift_hard_block.py — Handle dimension drift: error and exit 2
# =============================================================================
# Purpose:     When the startup check detects that the configured embedding
#              dimensions differ from what is stored in DB metadata, this
#              module emits a fatal error and exits with code 2. Dimension
#              drift is MORE severe than model drift — there is no graceful
#              recovery path without wiping and re-embedding all vectors.
# Rationale:   Unlike model drift (where vectors are just semantically stale),
#              dimension drift means the vec0 virtual table was created with
#              a fixed column width. Inserting vectors of a different dimension
#              will either fail at the SQLite level or corrupt the index.
#              There is no "mark stale and continue" — we must hard-stop.
# Responsibility:
#   - Emit a clear error message to stderr explaining the mismatch
#   - Exit with code 2 (integrity/configuration error)
#   - Block ALL operations — not just vector-dependent ones
# Organization:
#   Single public function: handle_dimension_drift(db_dims, config_dims)
#   Never returns — always calls sys.exit(2).
# =============================================================================

from __future__ import annotations

import sys


def handle_dimension_drift(db_dimensions: int | str, config_dimensions: int | str) -> None:
    """Handle detected dimension drift: emit error and exit.

    This function NEVER RETURNS. It always calls sys.exit(2).

    Dimension drift is a hard block because the sqlite-vec virtual table
    is created with a fixed vector width. Mixing dimensions corrupts the
    index or causes insertion failures.

    Args:
        db_dimensions: The dimension count stored in DB meta (may be str).
        config_dimensions: The dimension count from current config (may be str).

    Raises:
        SystemExit: Always exits with code 2.
    """
    # --- Step 1: Normalize dimensions to int for display ---
    # db_dims_int = int(db_dimensions)
    # config_dims_int = int(config_dimensions)

    # --- Step 2: Format error message ---
    # error_msg = _format_dimension_error(db_dims_int, config_dims_int)

    # --- Step 3: Write to stderr and exit ---
    # sys.stderr.write(error_msg)
    # sys.exit(2)
    pass


def _format_dimension_error(db_dims: int, config_dims: int) -> str:
    """Format the dimension drift error message for stderr.

    Args:
        db_dims: Dimension count stored in database.
        config_dims: Dimension count from config.

    Returns:
        Multi-line error string explaining the mismatch and remediation.
    """
    # Build a clear error message:
    #   "ERROR: Embedding dimension mismatch"
    #   "  Database vectors: {db_dims} dimensions"
    #   "  Config model:     {config_dims} dimensions"
    #   ""
    #   "  The sqlite-vec index was created for {db_dims}-dimensional vectors."
    #   "  Vectors of {config_dims} dimensions cannot be stored or searched."
    #   ""
    #   "  To resolve:"
    #   "    1. Change config back to a {db_dims}-dimensional model, OR"
    #   "    2. Delete all vectors and re-embed: `memory batch reembed --force`"
    #   ""
    #   "  All operations are blocked until this is resolved."
    #
    # Return the formatted string with trailing newline
    pass
