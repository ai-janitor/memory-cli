# =============================================================================
# Module: tag_registry_crud_normalize_autocreate.py
# Purpose: CRUD operations for the tag registry — add, list, remove — with
#   input normalization, idempotent add, and auto-creation on reference.
# Rationale: Tags are the primary classification axis for neurons. They need
#   stable integer IDs for efficient filtering, but human-friendly string names
#   for CLI usage. This module owns the full lifecycle of tag entries: creation,
#   enumeration, deletion (with referential integrity checks), and the auto-
#   create path used when `neuron add --tags` references a tag that doesn't
#   exist yet.
# Responsibility:
#   - tag_add: normalize name, insert-or-return-existing, idempotent
#   - tag_list: return all tags ordered by id
#   - tag_remove: remove by name or id, block if in use by neurons
#   - tag_autocreate: atomic create-if-not-exists (used by neuron add)
#   - normalize_tag_name: shared normalization logic
# Organization:
#   1. Imports
#   2. Constants (table name, column names)
#   3. normalize_tag_name() — normalization function
#   4. tag_add() — CLI `memory tag add <name>`
#   5. tag_list() — CLI `memory tag list`
#   6. tag_remove() — CLI `memory tag remove <name-or-id>`
#   7. tag_autocreate() — internal auto-create on reference
#   8. _count_tag_references() — helper to check neuron usage
#   9. TagRegistryError — custom exception
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Union


# -----------------------------------------------------------------------------
# Constants — table and column names for the tags table.
# Single source of truth; avoids string literals scattered through queries.
# -----------------------------------------------------------------------------
TAGS_TABLE = "tags"
# Schema: id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
#          created_at TEXT NOT NULL DEFAULT (datetime('now'))


class TagRegistryError(Exception):
    """Raised when a tag registry operation fails.

    Attributes:
        operation: Which operation failed (add, remove, list, autocreate).
        details: Human-readable description of what went wrong.
    """

    pass


def normalize_tag_name(raw_name: str) -> str:
    """Normalize a tag name for storage and lookup.

    Normalization rules:
    1. Strip leading and trailing whitespace
    2. Convert to lowercase
    3. Preserve internal whitespace (spaces between words are OK)
    4. Result must be non-empty after normalization

    Args:
        raw_name: The raw tag name from user input.

    Returns:
        Normalized tag name string.

    Raises:
        TagRegistryError: If the name is empty after normalization.
    """
    # --- Normalization logic ---
    # 1. Strip leading/trailing whitespace
    # 2. Lowercase the entire string
    # 3. Check length > 0; if empty, raise TagRegistryError
    # 4. Return normalized string
    normalized = raw_name.strip().lower()
    if not normalized:
        raise TagRegistryError(f"Tag name cannot be empty (got: {raw_name!r})")
    return normalized


def tag_add(conn: sqlite3.Connection, name: str) -> Dict[str, Any]:
    """Add a tag to the registry. Idempotent — returns existing if duplicate.

    CLI: `memory tag add <name>`

    Logic flow:
    1. Normalize the name via normalize_tag_name()
       - If empty after normalization -> raise TagRegistryError
    2. Attempt INSERT INTO tags (name) VALUES (?)
       - On UNIQUE constraint violation (name exists):
         a. SELECT id, name, created_at WHERE name = ?
         b. Return the existing row as dict
       - On success:
         a. Get lastrowid as the new tag's id
         b. SELECT the full row to get created_at
         c. Return the new row as dict
    3. Return dict with keys: id, name, created_at

    Edge cases:
    - Whitespace-only name -> rejected by normalization
    - Name that differs only by case/whitespace -> normalized to same,
      treated as duplicate (idempotent return)
    - Concurrent insert race -> UNIQUE constraint handles it; retry SELECT

    Args:
        conn: SQLite connection (must have tags table).
        name: Raw tag name from user input.

    Returns:
        Dict with id (int), name (str), created_at (str).

    Raises:
        TagRegistryError: If name is empty or DB error occurs.
    """
    # 1. Normalize name — raises TagRegistryError if empty
    name = normalize_tag_name(name)
    # 2. INSERT OR IGNORE to handle UNIQUE constraint atomically
    now = __import__("time").time()
    created_at = int(now * 1000)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO tags (name, created_at) VALUES (?, ?)",
            (name, created_at),
        )
    except Exception as exc:
        raise TagRegistryError(f"Failed to insert tag {name!r}: {exc}") from exc
    # 3. SELECT the row (exists whether newly inserted or pre-existing)
    row = conn.execute(
        "SELECT id, name, created_at FROM tags WHERE name = ?", (name,)
    ).fetchone()
    if row is None:
        raise TagRegistryError(f"Tag {name!r} not found after insert — unexpected state")
    return {"id": row[0], "name": row[1], "created_at": row[2]}


def tag_list(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """List all tags in the registry, ordered by id.

    CLI: `memory tag list`

    Logic flow:
    1. SELECT id, name, created_at FROM tags ORDER BY id ASC
    2. Convert each row to dict {id, name, created_at}
    3. Return list (may be empty — empty is success, not error)

    Output formats (handled by CLI layer, not this function):
    - JSON: array of {id, name} objects
    - Text: id<TAB>name per line

    Args:
        conn: SQLite connection.

    Returns:
        List of dicts, each with id, name, created_at. Empty list if no tags.
    """
    # 1. SELECT all tags ordered by id ASC
    rows = conn.execute(
        "SELECT id, name, created_at FROM tags ORDER BY id ASC"
    ).fetchall()
    # 2. Convert each row to dict and return
    return [{"id": row[0], "name": row[1], "created_at": row[2]} for row in rows]


def tag_remove(conn: sqlite3.Connection, name_or_id: Union[str, int]) -> bool:
    """Remove a tag from the registry by name or id.

    CLI: `memory tag remove <name-or-id>`

    Logic flow:
    1. Determine if name_or_id is an integer ID or a string name:
       - Try int(name_or_id) — if succeeds, treat as ID lookup
       - Otherwise, treat as name lookup (normalize first)
    2. Look up the tag:
       - By ID: SELECT id, name FROM tags WHERE id = ?
       - By name: SELECT id, name FROM tags WHERE name = ?
       - Not found -> return False (caller should exit 1)
    3. Check referential integrity:
       - Call _count_tag_references(conn, tag_id)
       - If count > 0 -> raise TagRegistryError with ref count
         (BLOCK removal — user must untag neurons first)
    4. DELETE FROM tags WHERE id = ?
    5. Return True (success)

    Edge cases:
    - name_or_id is "42" -> parsed as int, looked up by ID
    - name_or_id is "my-tag" -> normalized, looked up by name
    - Tag exists but is in use -> blocked, error with count
    - Tag not found -> return False (not an exception, just not-found)

    Args:
        conn: SQLite connection.
        name_or_id: Tag name (string) or tag id (int or string-of-int).

    Returns:
        True if tag was removed, False if tag not found.

    Raises:
        TagRegistryError: If tag is in use by neurons (with ref count).
    """
    # 1. Determine lookup mode: int ID or string name
    tag_row = None
    try:
        tag_id = int(name_or_id)
        # 2a. ID-based lookup
        row = conn.execute(
            "SELECT id, name FROM tags WHERE id = ?", (tag_id,)
        ).fetchone()
        if row:
            tag_row = {"id": row[0], "name": row[1]}
    except (ValueError, TypeError):
        # 2b. Name-based lookup — normalize first
        normalized = normalize_tag_name(str(name_or_id))
        row = conn.execute(
            "SELECT id, name FROM tags WHERE name = ?", (normalized,)
        ).fetchone()
        if row:
            tag_row = {"id": row[0], "name": row[1]}

    # 3. Not found → return False
    if tag_row is None:
        return False

    # 4. Check referential integrity — block if in use
    ref_count = _count_tag_references(conn, tag_row["id"])
    if ref_count > 0:
        raise TagRegistryError(
            f"Cannot remove tag {tag_row['name']!r} (id={tag_row['id']}): "
            f"referenced by {ref_count} neuron(s). Untag neurons first."
        )

    # 5. DELETE and return True
    conn.execute("DELETE FROM tags WHERE id = ?", (tag_row["id"],))
    return True


def tag_autocreate(conn: sqlite3.Connection, name: str) -> int:
    """Auto-create a tag if it doesn't exist. Returns the tag ID.

    Used internally when `neuron add --tags foo` references a tag that
    doesn't exist yet. Must be atomic — no window where the tag is
    partially created.

    Logic flow:
    1. Normalize the name
    2. INSERT OR IGNORE INTO tags (name) VALUES (?)
       - INSERT OR IGNORE is atomic: either inserts or silently skips
    3. SELECT id FROM tags WHERE name = ?
       - Always succeeds after step 2 (either newly inserted or pre-existing)
    4. Return the tag ID (int)

    This is the auto-create path — it never fails for valid names.
    Invalid (empty) names still raise TagRegistryError via normalization.

    Args:
        conn: SQLite connection.
        name: Raw tag name (will be normalized).

    Returns:
        Integer tag ID (existing or newly created).

    Raises:
        TagRegistryError: If name is empty after normalization.
    """
    # 1. Normalize — raises TagRegistryError if empty
    name = normalize_tag_name(name)
    # 2. INSERT OR IGNORE — atomic create-if-not-exists
    now = __import__("time").time()
    created_at = int(now * 1000)
    conn.execute(
        "INSERT OR IGNORE INTO tags (name, created_at) VALUES (?, ?)",
        (name, created_at),
    )
    # 3. SELECT the ID — always present after step 2
    row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
    return row[0]


def _count_tag_references(conn: sqlite3.Connection, tag_id: int) -> int:
    """Count how many neurons reference a given tag.

    Used by tag_remove to enforce referential integrity — tags in use
    by neurons cannot be removed.

    Logic flow:
    1. SELECT COUNT(*) FROM neuron_tags WHERE tag_id = ?
       (neuron_tags is the junction table linking neurons to tags)
    2. Return the count (0 means safe to delete)

    Args:
        conn: SQLite connection.
        tag_id: The tag's integer ID.

    Returns:
        Number of neurons referencing this tag.
    """
    # 1. COUNT(*) FROM neuron_tags WHERE tag_id = ?
    row = conn.execute(
        "SELECT COUNT(*) FROM neuron_tags WHERE tag_id = ?", (tag_id,)
    ).fetchone()
    return row[0]
