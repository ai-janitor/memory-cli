# =============================================================================
# startup_drift_check_model_and_dims.py — Automatic startup integrity check
# =============================================================================
# Purpose:     Run on every CLI invocation (read-only). Compares the current
#              config's embedding model and dimensions against what is stored
#              in the DB meta table. Detects model drift and dimension drift.
# Rationale:   If a user changes their embedding model between invocations,
#              existing vectors become semantically meaningless. We must detect
#              this early — before any search or write uses stale vectors — and
#              either warn (model drift) or hard-block (dimension drift).
# Responsibility:
#   - Read embedding_model_name and embedding_dimensions from DB meta table
#   - If both absent → skip (no vectors ever written, nothing to check)
#   - Compare config model basename vs DB model name → model drift
#   - Compare config dimensions vs DB dimensions → dimension drift
#   - Check if vectors_marked_stale_at is already set → warn
#   - Delegate to model_drift or dimension_drift handlers as needed
#   - Return a DriftCheckResult indicating what was found
# Organization:
#   Single public function: run_startup_drift_check(conn, config) -> DriftCheckResult
#   Internal helpers for reading meta values and comparing.
#   DriftCheckResult dataclass for structured return.
# =============================================================================

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
# from pathlib import Path
# from typing import Optional

# from memory_cli.integrity.model_drift_stale_vector_marking import handle_model_drift
# from memory_cli.integrity.dimension_drift_hard_block import handle_dimension_drift


@dataclass
class DriftCheckResult:
    """Result of the startup drift check.

    Attributes:
        model_drift: True if the config model differs from DB model.
        dimension_drift: True if the config dimensions differ from DB dimensions.
        vectors_already_stale: True if vectors_marked_stale_at was already set.
        skipped: True if no vectors have ever been written (nothing to check).
    """
    model_drift: bool = False
    dimension_drift: bool = False
    vectors_already_stale: bool = False
    skipped: bool = False


def run_startup_drift_check(conn: sqlite3.Connection, config: dict) -> DriftCheckResult:
    """Run the startup integrity check: compare config vs DB metadata.

    Called on every CLI invocation before dispatching to noun handlers.
    This function is READ-ONLY on the database — it does not modify anything.
    If drift is detected, it delegates to the appropriate handler which
    may write (model drift) or exit (dimension drift).

    Args:
        conn: Open SQLite connection with meta table accessible.
        config: Resolved config dict containing at minimum:
                - embedding_model: str (path or basename of GGUF file)
                - embedding_dimensions: int

    Returns:
        DriftCheckResult with flags indicating what was found.

    Raises:
        SystemExit: exit code 2 if dimension drift is detected (via handler).
    """
    # --- Step 1: Read DB metadata ---
    # Query meta table for embedding_model_name and embedding_dimensions
    # These are key-value pairs: SELECT value FROM meta WHERE key = ?
    # db_model_name = _read_meta_value(conn, "embedding_model_name")
    # db_dimensions = _read_meta_value(conn, "embedding_dimensions")

    # --- Step 2: Check if vectors have ever been written ---
    # If both db_model_name and db_dimensions are None → no vectors exist
    # Return DriftCheckResult(skipped=True) — nothing to validate against

    # --- Step 3: Extract config values for comparison ---
    # config_model_basename = extract basename from config["embedding_model"]
    #   e.g., "/path/to/nomic-embed-v1.5.Q8_0.gguf" → "nomic-embed-v1.5.Q8_0.gguf"
    # config_dimensions = int(config["embedding_dimensions"])

    # --- Step 4: Check for dimension drift (most severe — check first) ---
    # If db_dimensions is not None and int(db_dimensions) != config_dimensions:
    #   handle_dimension_drift(db_dimensions, config_dimensions)
    #   This function does NOT return — it calls sys.exit(2)

    # --- Step 5: Check for model drift ---
    # If db_model_name is not None and db_model_name != config_model_basename:
    #   handle_model_drift(conn, db_model_name, config_model_basename, config_dimensions)
    #   Set result.model_drift = True

    # --- Step 6: Check if vectors are already marked stale ---
    # stale_at = _read_meta_value(conn, "vectors_marked_stale_at")
    # If stale_at is not None:
    #   Emit warning to stderr: vectors have been stale since {stale_at}
    #   Set result.vectors_already_stale = True

    # --- Step 7: Return result ---
    pass


def _read_meta_value(conn: sqlite3.Connection, key: str) -> str | None:
    """Read a single value from the meta key-value table.

    Args:
        conn: Open SQLite connection.
        key: The meta key to look up.

    Returns:
        The string value if found, None otherwise.
    """
    # Execute: SELECT value FROM meta WHERE key = ?
    # Return row[0] if row exists, else None
    pass


def _extract_model_basename(model_path: str) -> str:
    """Extract the filename (basename) from a model path.

    Args:
        model_path: Full or relative path to GGUF file.

    Returns:
        Just the filename portion, e.g., "nomic-embed-v1.5.Q8_0.gguf".
    """
    # Use Path(model_path).name to get basename
    # Handle edge case where model_path is already just a basename
    pass
