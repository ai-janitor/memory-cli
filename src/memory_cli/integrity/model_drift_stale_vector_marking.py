# =============================================================================
# model_drift_stale_vector_marking.py — Handle model drift: warn, mark, block
# =============================================================================
# Purpose:     When the startup check detects that the configured embedding
#              model differs from what is stored in DB metadata, this module
#              handles the consequences: warn the user, mark all existing
#              vectors as stale, update DB metadata to the new model, and
#              block vector-dependent operations for this invocation.
# Rationale:   Vectors from model A are semantically incompatible with vectors
#              from model B. Searching across mixed models produces garbage.
#              We don't delete vectors (they can be re-embedded), but we must
#              prevent search until the user acknowledges the situation.
#              Non-vector operations (neuron add, tag, edge, etc.) still work.
# Responsibility:
#   - Emit a clear warning to stderr about the model change
#   - Set vectors_marked_stale_at in meta table (ISO 8601 UTC)
#   - Update embedding_model_name in meta table to new config value
#   - Update embedding_dimensions in meta table to new config value
#   - Signal that vector-dependent ops should be blocked (exit 2)
# Organization:
#   Single public function: handle_model_drift(conn, old_model, new_model, new_dims)
#   Helper: is_vector_dependent_operation(noun, verb) -> bool
#   Internal helpers for meta writes and warning formatting.
# =============================================================================

from __future__ import annotations

import sqlite3
import sys
# from datetime import datetime, timezone


def handle_model_drift(
    conn: sqlite3.Connection,
    old_model_name: str,
    new_model_name: str,
    new_dimensions: int,
) -> None:
    """Handle detected model drift: warn, mark stale, update meta.

    This function is called by the startup drift check when the config's
    embedding model basename does not match the DB's stored model name.

    Args:
        conn: Open SQLite connection (will be written to).
        old_model_name: The model name currently stored in DB meta.
        new_model_name: The model basename from the current config.
        new_dimensions: The dimensions value from the current config.

    Side effects:
        - Writes warning to stderr
        - Updates meta table: embedding_model_name, embedding_dimensions,
          vectors_marked_stale_at
        - Does NOT call sys.exit — the caller decides whether to block
          based on whether the current operation is vector-dependent
    """
    # --- Step 1: Emit warning to stderr ---
    # Format a multi-line warning:
    #   "WARNING: Embedding model changed"
    #   "  Previous: {old_model_name}"
    #   "  Current:  {new_model_name}"
    #   "  All existing vectors are now marked stale."
    #   "  Run `memory batch reembed` to re-embed with the new model."
    #   "  Vector search is blocked until re-embedding is complete."
    # Use sys.stderr.write() — not print() — for CLI stderr convention

    # --- Step 2: Mark all vectors as stale ---
    # Set vectors_marked_stale_at = current UTC time in ISO 8601 format
    # Use _upsert_meta(conn, "vectors_marked_stale_at", now_iso)
    # This is idempotent — if already stale, we update the timestamp

    # --- Step 3: Update DB metadata to new config values ---
    # _upsert_meta(conn, "embedding_model_name", new_model_name)
    # _upsert_meta(conn, "embedding_dimensions", str(new_dimensions))

    # --- Step 4: Commit the transaction ---
    # conn.commit() to persist the meta changes
    pass


def is_vector_dependent_operation(noun: str, verb: str) -> bool:
    """Check if a CLI operation depends on vector search.

    Used by the CLI dispatch layer to decide whether to exit 2 after
    model drift is detected.

    Args:
        noun: The CLI noun (e.g., "neuron", "meta", "edge").
        verb: The CLI verb (e.g., "search", "add", "stats").

    Returns:
        True if the operation requires working vectors.
    """
    # --- Vector-dependent operations ---
    # neuron search (uses vector retrieval)
    # neuron find (alias for search)
    # batch reembed (needs model loaded, but should be ALLOWED — it fixes drift)
    # Everything else is non-vector: add, get, list, update, tag ops, edge ops, meta ops
    #
    # Special case: "batch reembed" should NOT be blocked — it's the fix
    # Return True for search/find operations, False for everything else
    pass


def _upsert_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Insert or update a key-value pair in the meta table.

    Args:
        conn: Open SQLite connection.
        key: Meta key to set.
        value: Value to store.
    """
    # INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)
    # This handles both first-time insert and update cases
    pass


def _format_drift_warning(old_model: str, new_model: str) -> str:
    """Format the model drift warning message for stderr.

    Args:
        old_model: Previous model name from DB.
        new_model: New model name from config.

    Returns:
        Multi-line warning string.
    """
    # Build the warning message with clear instructions
    # Include both model names for debugging
    # Include the remediation command: `memory batch reembed`
    pass
