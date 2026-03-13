# =============================================================================
# v002_add_store_fingerprint.py — Add store fingerprint to meta table
# =============================================================================
# Purpose:     For existing databases that were created before the fingerprint
#              feature, generate a UUID4 fingerprint and insert it into the
#              meta table along with the db_path.
# Rationale:   Each memory store needs a unique identity (fingerprint) for
#              federation — cross-store edge resolution and store discovery.
#              The fingerprint is an 8-char hex prefix of a UUID4 (~4 billion
#              possible values), written once and never changed.
# Responsibility:
#   - Generate a UUID4 fingerprint (first 8 hex chars)
#   - INSERT OR IGNORE fingerprint into meta (idempotent)
#   - INSERT OR IGNORE db_path placeholder (callers fill real path)
#   - Does NOT update schema_version — the migration runner handles that
# Organization:
#   Public function: apply(conn) -> None
# =============================================================================

from __future__ import annotations

import sqlite3
import uuid


def apply(conn: sqlite3.Connection) -> None:
    """Apply the v1->v2 migration: add store fingerprint to meta table.

    This function executes within the caller's transaction. It must NOT
    call BEGIN, COMMIT, or ROLLBACK. If any step fails, it raises an
    exception and the caller rolls back the entire migration batch.

    Args:
        conn: An open sqlite3.Connection inside an active transaction.

    Raises:
        sqlite3.Error: If any INSERT fails.
    """
    # =========================================================================
    # STEP 1: Generate a UUID4 fingerprint — first 8 hex chars
    # =========================================================================
    # Format: 8 hex chars (e.g., "a3f2b7c1")
    # ~4 billion possible values — sufficient for store identity
    fingerprint = uuid.uuid4().hex[:8]

    # =========================================================================
    # STEP 2: Insert fingerprint into meta table (idempotent via OR IGNORE)
    # =========================================================================
    # If fingerprint already exists (e.g., DB was already fingerprinted by
    # a newer init), this is a no-op.
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('fingerprint', ?)",
        (fingerprint,),
    )

    # =========================================================================
    # STEP 3: Insert db_path placeholder into meta table
    # =========================================================================
    # The real path is set by the init command or by the caller. For migrated
    # databases we insert 'unknown' — the connection helper will update it
    # on next open if needed.
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('db_path', 'unknown')",
    )

    # =========================================================================
    # STEP 4: Insert project placeholder into meta table
    # =========================================================================
    # For migrated databases, project is unknown until the caller provides it.
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('project', 'unknown')",
    )
