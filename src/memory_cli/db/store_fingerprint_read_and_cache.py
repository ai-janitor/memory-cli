# =============================================================================
# store_fingerprint_read_and_cache.py — Read, cache, and resolve store identity
# =============================================================================
# Purpose:     Provide the public API for store fingerprint operations:
#              reading the local store's fingerprint, caching foreign store
#              locations, and resolving a fingerprint to a filesystem path.
# Rationale:   Federation requires each store to have a unique identity and
#              the ability to discover other stores by fingerprint. The meta
#              table stores both local identity (key='fingerprint') and a
#              registry of known foreign stores (key='store:<fingerprint>').
# Responsibility:
#   - get_fingerprint(conn) -> str: Read this store's fingerprint from meta
#   - cache_foreign_store(conn, fingerprint, path): Register a foreign store
#   - resolve_foreign_store(conn, fingerprint) -> str | None: Lookup foreign
# Organization:
#   Three public functions. All operate on the meta table.
# =============================================================================

from __future__ import annotations

import sqlite3


def get_fingerprint(conn: sqlite3.Connection) -> str:
    """Read this store's fingerprint from the meta table.

    Args:
        conn: An open sqlite3.Connection to the local store.

    Returns:
        The 8-char hex fingerprint string.

    Raises:
        ValueError: If no fingerprint is found in the meta table.
    """
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'fingerprint'"
    ).fetchone()
    if row is None:
        raise ValueError(
            "No fingerprint found in meta table. "
            "Run `memory init` or upgrade the database."
        )
    return row[0]


def cache_foreign_store(
    conn: sqlite3.Connection,
    fingerprint: str,
    path: str,
) -> None:
    """Register a foreign store's fingerprint and filesystem path.

    Writes (or updates) a meta entry with key='store:<fingerprint>'
    and value=path. This allows future lookups by fingerprint without
    requiring the user to specify the path again.

    Args:
        conn: An open sqlite3.Connection to the local store.
        fingerprint: The 8-char hex fingerprint of the foreign store.
        path: Absolute filesystem path to the foreign store's DB file.
    """
    key = f"store:{fingerprint}"
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        (key, path),
    )
    conn.commit()


def resolve_foreign_store(
    conn: sqlite3.Connection,
    fingerprint: str,
) -> str | None:
    """Look up a foreign store's filesystem path by its fingerprint.

    Args:
        conn: An open sqlite3.Connection to the local store.
        fingerprint: The 8-char hex fingerprint of the foreign store.

    Returns:
        The absolute path to the foreign store's DB file, or None if
        the fingerprint is not registered.
    """
    key = f"store:{fingerprint}"
    row = conn.execute(
        "SELECT value FROM meta WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    return row[0]
