# =============================================================================
# meta_stats_db_summary.py — `memory meta stats` command implementation
# =============================================================================
# Purpose:     Gather and return a comprehensive summary of database state,
#              embedding configuration, drift status, and entity counts.
#              This is the read-only diagnostic command for operators and
#              agents to understand the current state of the memory store.
# Rationale:   Agents and operators need a single command to check DB health
#              without guessing. Stats include everything needed to diagnose
#              drift issues, stale vectors, and storage sizes — all in one
#              JSON-serializable dict that fits the output envelope format.
# Responsibility:
#   - Resolve and return db_path and db_size_bytes
#   - Read schema_version from DB
#   - Read embedding metadata (model name, dimensions) from DB meta table
#   - Read embedding config (model name, dimensions) from current config
#   - Compute drift_detected flag by comparing DB vs config
#   - Read vectors_stale flag and vectors_stale_since timestamp
#   - Count neurons, vectors, stale vectors, never-embedded neurons, tags, edges
#   - Read last_integrity_check_at timestamp
#   - Return all fields as a dict
# Organization:
#   Single public function: gather_meta_stats(conn, config, db_path) -> dict
#   Internal helpers for each category of stats.
# =============================================================================

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def gather_meta_stats(
    conn: sqlite3.Connection,
    config: dict,
    db_path: str | Path,
) -> dict:
    """Gather all stats for `memory meta stats` command.

    Args:
        conn: Open SQLite connection with all tables accessible.
        config: Resolved config dict with embedding_model and embedding_dimensions.
        db_path: Filesystem path to the SQLite database file.

    Returns:
        Dict with all stat fields, ready for JSON serialization:
            - db_path: str
            - db_size_bytes: int
            - schema_version: int
            - embedding_model_name: str | None (from DB)
            - embedding_dimensions: int | None (from DB)
            - config_model_name: str (from config)
            - config_dimensions: int (from config)
            - drift_detected: bool
            - vectors_stale: bool
            - vectors_stale_since: str | None (ISO 8601)
            - neuron_count: int
            - vector_count: int
            - stale_vector_count: int
            - never_embedded_count: int
            - tag_count: int
            - edge_count: int
            - last_integrity_check_at: str | None (ISO 8601)
    """
    # --- Step 1: File-level stats ---
    # Handle :memory: gracefully — return 0 for size
    db_path_str = str(db_path)
    if db_path_str == ":memory:":
        db_size_bytes = 0
    else:
        try:
            db_size_bytes = Path(db_path_str).stat().st_size
        except (OSError, FileNotFoundError):
            db_size_bytes = 0

    # --- Step 2: Schema version ---
    schema_version = _read_schema_version(conn)

    # --- Step 3: Embedding metadata from DB ---
    # Uses the key 'embedding_model' as seeded by v001 migration
    db_model_raw = _read_meta(conn, "embedding_model")
    # Treat 'default' as "not set" — no real vectors written yet
    embedding_model_name: str | None = db_model_raw if (db_model_raw and db_model_raw != "default") else None
    embedding_dimensions_str = _read_meta(conn, "embedding_dimensions")
    embedding_dimensions: int | None = int(embedding_dimensions_str) if embedding_dimensions_str else None

    # --- Step 4: Embedding config from current config ---
    config_model_name = os.path.basename(config["embedding"]["model_path"])
    config_dimensions = int(config["embedding"]["dimensions"])

    # --- Step 5: Drift detection ---
    # Only compare when embedding_model_name is set (vectors have been written)
    drift_detected = False
    if embedding_model_name is not None and embedding_model_name != config_model_name:
        drift_detected = True
    if embedding_dimensions is not None and embedding_dimensions != config_dimensions:
        drift_detected = True

    # --- Step 6: Stale vector status ---
    stale_since = _read_meta(conn, "vectors_marked_stale_at")
    vectors_stale = stale_since is not None

    # --- Step 7: Entity counts ---
    neuron_count = _count_rows(conn, "neurons")
    vector_count = _count_vectors(conn)
    stale_vector_count = _count_stale_vectors(conn, stale_since)
    never_embedded_count = _count_never_embedded(conn)
    tag_count = _count_rows(conn, "tags")
    edge_count = _count_rows(conn, "edges")

    # --- Step 8: Last integrity check ---
    last_integrity_check_at = _read_meta(conn, "last_integrity_check_at")

    # --- Step 9: Assemble and return dict with all 17 fields ---
    return {
        "db_path": db_path_str,
        "db_size_bytes": db_size_bytes,
        "schema_version": schema_version,
        "embedding_model_name": embedding_model_name,
        "embedding_dimensions": embedding_dimensions,
        "config_model_name": config_model_name,
        "config_dimensions": config_dimensions,
        "drift_detected": drift_detected,
        "vectors_stale": vectors_stale,
        "vectors_stale_since": stale_since,
        "neuron_count": neuron_count,
        "vector_count": vector_count,
        "stale_vector_count": stale_vector_count,
        "never_embedded_count": never_embedded_count,
        "tag_count": tag_count,
        "edge_count": edge_count,
        "last_integrity_check_at": last_integrity_check_at,
    }


def _read_meta(conn: sqlite3.Connection, key: str) -> str | None:
    """Read a single value from the meta key-value table.

    Args:
        conn: Open SQLite connection.
        key: The meta key to look up.

    Returns:
        The string value if found, None otherwise.
    """
    # SELECT value FROM meta WHERE key = ?
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row is not None else None


def _read_schema_version(conn: sqlite3.Connection) -> int:
    """Read the current schema version from the DB.

    Args:
        conn: Open SQLite connection.

    Returns:
        Integer schema version, or 0 if not found.
    """
    # Read schema_version from the meta table (seeded by v001 migration as '1')
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        return 0
    try:
        return int(row[0])
    except (ValueError, TypeError):
        return 0


def _count_rows(conn: sqlite3.Connection, table: str) -> int:
    """Count total rows in a given table.

    Args:
        conn: Open SQLite connection.
        table: Table name (must be a known safe value — not user input).

    Returns:
        Integer row count.
    """
    # SELECT COUNT(*) FROM {table}
    # Table name is NOT parameterized (SQL limitation) but is validated
    # against a whitelist of known table names
    _SAFE_TABLES = {"neurons", "edges", "tags", "neuron_tags", "attr_keys", "neuron_attrs"}
    if table not in _SAFE_TABLES:
        raise ValueError(f"Unknown table name: {table!r}")
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return row[0] if row is not None else 0


def _count_vectors(conn: sqlite3.Connection) -> int:
    """Count the number of neurons that have a vector in vec0 table.

    Returns:
        Number of non-null vectors.
    """
    # SELECT COUNT(*) FROM neurons_vec — the vec0 virtual table
    # Note: vec0 supports COUNT(*) via the shadow rowids table
    row = conn.execute("SELECT COUNT(*) FROM neurons_vec").fetchone()
    return row[0] if row is not None else 0


def _count_stale_vectors(conn: sqlite3.Connection, stale_since: str | None) -> int:
    """Count vectors that were written before the stale marker.

    If stale_since is None, returns 0 (no vectors are stale).
    If stale_since is set, ALL vectors are considered stale because
    model drift affects every vector equally.

    Args:
        conn: Open SQLite connection.
        stale_since: ISO 8601 timestamp when vectors were marked stale, or None.

    Returns:
        Count of stale vectors (0 or total vector count).
    """
    # If stale_since is None → return 0 (no stale condition active)
    # If stale_since is set → return _count_vectors(conn)
    #   (model drift makes ALL vectors stale, not just some)
    if stale_since is None:
        return 0
    return _count_vectors(conn)


def _count_never_embedded(conn: sqlite3.Connection) -> int:
    """Count neurons that have never had a vector generated.

    Returns:
        Number of neurons with no corresponding vector entry.
    """
    # Count neurons with no corresponding row in neurons_vec
    # Use a subquery since vec0 does not support standard JOINs
    row = conn.execute("""
        SELECT COUNT(*) FROM neurons
        WHERE id NOT IN (SELECT neuron_id FROM neurons_vec)
    """).fetchone()
    return row[0] if row is not None else 0
