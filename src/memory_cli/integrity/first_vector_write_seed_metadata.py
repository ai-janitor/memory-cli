# =============================================================================
# first_vector_write_seed_metadata.py — Seed meta on first vector write
# =============================================================================
# Purpose:     On the very first vector insertion into the database, record
#              the embedding model name and dimensions in the meta table.
#              This establishes the baseline that all future startup drift
#              checks compare against.
# Rationale:   We cannot seed metadata at `memory init` time because the user
#              may change their config before writing any vectors. The only
#              trustworthy moment is when the first actual vector is written —
#              that locks in what model produced it. If metadata is already
#              present, we do NOT overwrite (concurrent agent safety).
# Responsibility:
#   - Check if embedding_model_name and embedding_dimensions are already set
#   - If not set, write both values from the current config
#   - If already set, do nothing (another agent may have seeded first)
#   - This must be atomic — use a single transaction to avoid races
# Organization:
#   Single public function: seed_metadata_on_first_vector(conn, model_name, dimensions)
#   Called from vector_storage_vec0_write.py before/after the first INSERT.
# =============================================================================

from __future__ import annotations

import sqlite3


def seed_metadata_on_first_vector(
    conn: sqlite3.Connection,
    model_name: str,
    dimensions: int,
) -> bool:
    """Seed embedding metadata on the first vector write.

    Called by the vector storage layer every time a vector is written.
    Only actually writes metadata if it does not already exist (first time).
    Uses INSERT OR IGNORE to handle concurrent agents safely.

    Args:
        conn: Open SQLite connection (within an active transaction).
        model_name: Basename of the GGUF model file, e.g.,
                    "nomic-embed-v1.5.Q8_0.gguf".
        dimensions: Integer dimension count, e.g., 768.

    Returns:
        True if metadata was seeded (first time), False if already present.
    """
    # --- Step 1: Check if metadata already exists ---
    # Read embedding_model_name from meta table
    # If it is not None → metadata already seeded, return False

    # --- Step 2: Seed both values atomically ---
    # Use INSERT OR IGNORE to handle race condition where another agent
    # seeds between our check and our write
    # INSERT OR IGNORE INTO meta (key, value) VALUES ('embedding_model_name', ?)
    # INSERT OR IGNORE INTO meta (key, value) VALUES ('embedding_dimensions', ?)
    #
    # We use INSERT OR IGNORE (not INSERT OR REPLACE) because:
    #   - If another agent inserted between our check and our write,
    #     we want to keep THEIR values (they won the race)
    #   - REPLACE would overwrite, violating concurrent safety

    # --- Step 3: Return whether we actually seeded ---
    # Check rowcount or re-read to confirm we were the ones who wrote
    # Return True if we seeded, False if another agent beat us
    pass


def _meta_key_exists(conn: sqlite3.Connection, key: str) -> bool:
    """Check if a key exists in the meta table.

    Args:
        conn: Open SQLite connection.
        key: Meta key to check.

    Returns:
        True if the key exists, False otherwise.
    """
    # SELECT 1 FROM meta WHERE key = ? LIMIT 1
    # Return True if row found, False otherwise
    pass
