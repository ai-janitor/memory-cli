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
    # Read embedding_model from meta table (key used by migration)
    # If it is not None and not 'default' → metadata already seeded, return False
    if _meta_key_exists(conn, "embedding_model"):
        return False

    # --- Step 2: Seed both values atomically ---
    # The v001 migration pre-seeds embedding_model='default' as a placeholder.
    # First vector write must atomically update the 'default' placeholder to the
    # real model name. We use a conditional UPDATE that only fires if value is
    # still 'default' (concurrent-safe: if another agent updated it first, our
    # UPDATE affects 0 rows and we return False).
    #
    # For embedding_dimensions, we similarly update only if still at default.
    cursor1 = conn.execute(
        "UPDATE meta SET value = ? WHERE key = 'embedding_model' AND value = 'default'",
        (model_name,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('embedding_dimensions', ?)",
        (str(dimensions),),
    )

    # --- Step 3: Return whether we actually seeded ---
    # cursor1.rowcount == 1 means we successfully updated from 'default'
    # If another agent already updated it, rowcount == 0
    return cursor1.rowcount == 1


def _meta_key_exists(conn: sqlite3.Connection, key: str) -> bool:
    """Check if a key exists in the meta table.

    Args:
        conn: Open SQLite connection.
        key: Meta key to check.

    Returns:
        True if the key exists, False otherwise.
    """
    # SELECT value FROM meta WHERE key = ? LIMIT 1
    # Return True if key exists AND value != 'default' (default means not yet seeded)
    row = conn.execute(
        "SELECT value FROM meta WHERE key = ? LIMIT 1", (key,)
    ).fetchone()
    if row is None:
        return False
    return row[0] != "default"
