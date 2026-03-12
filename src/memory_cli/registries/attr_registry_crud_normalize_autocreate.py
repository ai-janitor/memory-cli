# =============================================================================
# Module: attr_registry_crud_normalize_autocreate.py
# Purpose: CRUD operations for the attribute key registry — add, list, remove —
#   with input normalization, idempotent add, and auto-creation on reference.
# Rationale: Attribute keys follow the identical pattern to tags: managed-enum
#   with stable integer IDs, normalization at boundary, and auto-create on
#   reference. The registry manages KEYS only — values are free-form text
#   stored with neurons in a separate table. Keeping keys in a registry ensures
#   consistency (no "Color" vs "color" vs " color " drift) and enables
#   enumeration of what attributes exist in the store.
# Responsibility:
#   - attr_add: normalize key name, insert-or-return-existing, idempotent
#   - attr_list: return all attr keys ordered by id
#   - attr_remove: remove by name or id, block if in use by neurons
#   - attr_autocreate: atomic create-if-not-exists (used by neuron add)
#   - normalize_attr_name: shared normalization logic
# Organization:
#   1. Imports
#   2. Constants (table name, column names)
#   3. normalize_attr_name() — normalization function
#   4. attr_add() — CLI `memory attr add <name>`
#   5. attr_list() — CLI `memory attr list`
#   6. attr_remove() — CLI `memory attr remove <name-or-id>`
#   7. attr_autocreate() — internal auto-create on reference
#   8. _count_attr_references() — helper to check neuron usage
#   9. AttrRegistryError — custom exception
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Union


# -----------------------------------------------------------------------------
# Constants — table and column names for the attr_keys table.
# Single source of truth; avoids string literals scattered through queries.
# -----------------------------------------------------------------------------
ATTR_KEYS_TABLE = "attr_keys"
# Schema: id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
#          created_at TEXT NOT NULL DEFAULT (datetime('now'))


class AttrRegistryError(Exception):
    """Raised when an attr registry operation fails.

    Attributes:
        operation: Which operation failed (add, remove, list, autocreate).
        details: Human-readable description of what went wrong.
    """

    pass


def normalize_attr_name(raw_name: str) -> str:
    """Normalize an attribute key name for storage and lookup.

    Normalization rules (identical to tag normalization):
    1. Strip leading and trailing whitespace
    2. Convert to lowercase
    3. Preserve internal whitespace (spaces between words are OK)
    4. Result must be non-empty after normalization

    Note: Cross-registry collision is OK — a tag named "status" and an
    attr key named "status" can coexist. They are in separate tables.

    Args:
        raw_name: The raw attr key name from user input.

    Returns:
        Normalized attr key name string.

    Raises:
        AttrRegistryError: If the name is empty after normalization.
    """
    # --- Normalization logic ---
    # 1. Strip leading/trailing whitespace
    # 2. Lowercase the entire string
    # 3. Check length > 0; if empty, raise AttrRegistryError
    # 4. Return normalized string
    normalized = raw_name.strip().lower()
    if not normalized:
        raise AttrRegistryError(f"Attr key name cannot be empty (got: {raw_name!r})")
    return normalized


def attr_add(conn: sqlite3.Connection, name: str) -> Dict[str, Any]:
    """Add an attribute key to the registry. Idempotent — returns existing if duplicate.

    CLI: `memory attr add <name>`

    Logic flow:
    1. Normalize the name via normalize_attr_name()
       - If empty after normalization -> raise AttrRegistryError
    2. Attempt INSERT INTO attr_keys (name) VALUES (?)
       - On UNIQUE constraint violation (name exists):
         a. SELECT id, name, created_at WHERE name = ?
         b. Return the existing row as dict
       - On success:
         a. Get lastrowid as the new attr key's id
         b. SELECT the full row to get created_at
         c. Return the new row as dict
    3. Return dict with keys: id, name, created_at

    Edge cases:
    - Whitespace-only name -> rejected by normalization
    - Name that differs only by case/whitespace -> normalized to same,
      treated as duplicate (idempotent return)
    - Concurrent insert race -> UNIQUE constraint handles it; retry SELECT

    Args:
        conn: SQLite connection (must have attr_keys table).
        name: Raw attr key name from user input.

    Returns:
        Dict with id (int), name (str), created_at (str).

    Raises:
        AttrRegistryError: If name is empty or DB error occurs.
    """
    # 1. Normalize name — raises AttrRegistryError if empty
    name = normalize_attr_name(name)
    # 2. INSERT OR IGNORE to handle UNIQUE constraint atomically
    now = __import__("time").time()
    created_at = int(now * 1000)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO attr_keys (name, created_at) VALUES (?, ?)",
            (name, created_at),
        )
    except Exception as exc:
        raise AttrRegistryError(f"Failed to insert attr key {name!r}: {exc}") from exc
    # 3. SELECT the row (exists whether newly inserted or pre-existing)
    row = conn.execute(
        "SELECT id, name, created_at FROM attr_keys WHERE name = ?", (name,)
    ).fetchone()
    if row is None:
        raise AttrRegistryError(f"Attr key {name!r} not found after insert — unexpected state")
    return {"id": row[0], "name": row[1], "created_at": row[2]}


def attr_list(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """List all attribute keys in the registry, ordered by id.

    CLI: `memory attr list`

    Logic flow:
    1. SELECT id, name, created_at FROM attr_keys ORDER BY id ASC
    2. Convert each row to dict {id, name, created_at}
    3. Return list (may be empty — empty is success, not error)

    Output formats (handled by CLI layer, not this function):
    - JSON: array of {id, name} objects
    - Text: id<TAB>name per line

    Args:
        conn: SQLite connection.

    Returns:
        List of dicts, each with id, name, created_at. Empty list if no attr keys.
    """
    # 1. SELECT all attr keys ordered by id ASC
    rows = conn.execute(
        "SELECT id, name, created_at FROM attr_keys ORDER BY id ASC"
    ).fetchall()
    # 2. Convert each row to dict and return
    return [{"id": row[0], "name": row[1], "created_at": row[2]} for row in rows]


def attr_remove(conn: sqlite3.Connection, name_or_id: Union[str, int]) -> bool:
    """Remove an attribute key from the registry by name or id.

    CLI: `memory attr remove <name-or-id>`

    Logic flow:
    1. Determine if name_or_id is an integer ID or a string name:
       - Try int(name_or_id) — if succeeds, treat as ID lookup
       - Otherwise, treat as name lookup (normalize first)
    2. Look up the attr key:
       - By ID: SELECT id, name FROM attr_keys WHERE id = ?
       - By name: SELECT id, name FROM attr_keys WHERE name = ?
       - Not found -> return False (caller should exit 1)
    3. Check referential integrity:
       - Call _count_attr_references(conn, attr_id)
       - If count > 0 -> raise AttrRegistryError with ref count
         (BLOCK removal — user must remove attrs from neurons first)
    4. DELETE FROM attr_keys WHERE id = ?
    5. Return True (success)

    Edge cases:
    - name_or_id is "42" -> parsed as int, looked up by ID
    - name_or_id is "priority" -> normalized, looked up by name
    - Attr key exists but is in use -> blocked, error with count
    - Attr key not found -> return False (not an exception, just not-found)

    Args:
        conn: SQLite connection.
        name_or_id: Attr key name (string) or attr key id (int or string-of-int).

    Returns:
        True if attr key was removed, False if not found.

    Raises:
        AttrRegistryError: If attr key is in use by neurons (with ref count).
    """
    # 1. Determine lookup mode: int ID or string name
    attr_row = None
    try:
        attr_id = int(name_or_id)
        # 2a. ID-based lookup
        row = conn.execute(
            "SELECT id, name FROM attr_keys WHERE id = ?", (attr_id,)
        ).fetchone()
        if row:
            attr_row = {"id": row[0], "name": row[1]}
    except (ValueError, TypeError):
        # 2b. Name-based lookup — normalize first
        normalized = normalize_attr_name(str(name_or_id))
        row = conn.execute(
            "SELECT id, name FROM attr_keys WHERE name = ?", (normalized,)
        ).fetchone()
        if row:
            attr_row = {"id": row[0], "name": row[1]}

    # 3. Not found → return False
    if attr_row is None:
        return False

    # 4. Check referential integrity — block if in use
    ref_count = _count_attr_references(conn, attr_row["id"])
    if ref_count > 0:
        raise AttrRegistryError(
            f"Cannot remove attr key {attr_row['name']!r} (id={attr_row['id']}): "
            f"referenced by {ref_count} neuron(s). Remove attrs from neurons first."
        )

    # 5. DELETE and return True
    conn.execute("DELETE FROM attr_keys WHERE id = ?", (attr_row["id"],))
    return True


def attr_autocreate(conn: sqlite3.Connection, name: str) -> int:
    """Auto-create an attribute key if it doesn't exist. Returns the attr key ID.

    Used internally when `neuron add --attr key=value` references an attr key
    that doesn't exist yet. Must be atomic — no window where the key is
    partially created.

    Logic flow:
    1. Normalize the name
    2. INSERT OR IGNORE INTO attr_keys (name) VALUES (?)
       - INSERT OR IGNORE is atomic: either inserts or silently skips
    3. SELECT id FROM attr_keys WHERE name = ?
       - Always succeeds after step 2 (either newly inserted or pre-existing)
    4. Return the attr key ID (int)

    This is the auto-create path — it never fails for valid names.
    Invalid (empty) names still raise AttrRegistryError via normalization.

    Args:
        conn: SQLite connection.
        name: Raw attr key name (will be normalized).

    Returns:
        Integer attr key ID (existing or newly created).

    Raises:
        AttrRegistryError: If name is empty after normalization.
    """
    # 1. Normalize — raises AttrRegistryError if empty
    name = normalize_attr_name(name)
    # 2. INSERT OR IGNORE — atomic create-if-not-exists
    now = __import__("time").time()
    created_at = int(now * 1000)
    conn.execute(
        "INSERT OR IGNORE INTO attr_keys (name, created_at) VALUES (?, ?)",
        (name, created_at),
    )
    # 3. SELECT the ID — always present after step 2
    row = conn.execute("SELECT id FROM attr_keys WHERE name = ?", (name,)).fetchone()
    return row[0]


def _count_attr_references(conn: sqlite3.Connection, attr_id: int) -> int:
    """Count how many neurons reference a given attribute key.

    Used by attr_remove to enforce referential integrity — attr keys in use
    by neurons cannot be removed.

    Logic flow:
    1. SELECT COUNT(*) FROM neuron_attrs WHERE attr_key_id = ?
       (neuron_attrs is the table storing key-value pairs on neurons)
    2. Return the count (0 means safe to delete)

    Args:
        conn: SQLite connection.
        attr_id: The attr key's integer ID.

    Returns:
        Number of neurons referencing this attr key.
    """
    # 1. COUNT(*) FROM neuron_attrs WHERE attr_key_id = ?
    row = conn.execute(
        "SELECT COUNT(*) FROM neuron_attrs WHERE attr_key_id = ?", (attr_id,)
    ).fetchone()
    return row[0]
