# =============================================================================
# Module: registry_lookup_by_name_or_id.py
# Purpose: Shared lookup logic for both tag and attr registries — resolve a
#   user-provided identifier to a registry row by name (with normalization and
#   optional auto-create) or by integer ID (strict, no auto-create).
# Rationale: Both registries need the same two lookup modes: name-based (which
#   normalizes and can auto-create) and ID-based (which is strict). Extracting
#   this into a shared module avoids duplicating the dispatch logic and ensures
#   consistent behavior across tags and attrs. The caller specifies which table
#   and normalization function to use.
# Responsibility:
#   - lookup_by_name: normalize name, optionally auto-create, return row
#   - lookup_by_id: strict lookup by integer ID, not-found error if missing
#   - resolve_name_or_id: dispatcher that routes to name or ID lookup
# Organization:
#   1. Imports
#   2. RegistryLookupError — custom exception for not-found
#   3. lookup_by_name() — name-based resolution with normalization + auto-create
#   4. lookup_by_id() — strict ID-based resolution
#   5. resolve_name_or_id() — dispatch: detect int vs string, route accordingly
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import Any, Callable, Dict, Optional


class RegistryLookupError(Exception):
    """Raised when a registry lookup fails to find the requested entry.

    Attributes:
        registry: Which registry was queried ("tags" or "attr_keys").
        identifier: The name or ID that was not found.
    """

    pass


def lookup_by_name(
    conn: sqlite3.Connection,
    table: str,
    raw_name: str,
    normalize_fn: Callable[[str], str],
    autocreate: bool = True,
) -> Dict[str, Any]:
    """Look up a registry entry by name, with normalization and optional auto-create.

    Logic flow:
    1. Normalize the raw_name using the provided normalize_fn
       - normalize_fn raises on empty/invalid names
    2. SELECT id, name, created_at FROM <table> WHERE name = ?
    3. If found -> return row as dict {id, name, created_at}
    4. If not found AND autocreate is True:
       a. INSERT INTO <table> (name) VALUES (?)
       b. Get lastrowid
       c. SELECT the full row (to get created_at from DEFAULT)
       d. Return row as dict
    5. If not found AND autocreate is False:
       - Raise RegistryLookupError

    The auto-create path is used when neurons reference tags/attrs during
    `neuron add`. The non-auto-create path is used for explicit lookups
    where the user expects the entry to already exist.

    Args:
        conn: SQLite connection.
        table: Table name ("tags" or "attr_keys").
        raw_name: Raw name from user input (will be normalized).
        normalize_fn: Normalization function for this registry type.
        autocreate: If True, create entry when not found. If False, raise error.

    Returns:
        Dict with id (int), name (str), created_at (str).

    Raises:
        RegistryLookupError: If not found and autocreate is False.
        TagRegistryError/AttrRegistryError: If normalization fails (via normalize_fn).
    """
    pass


def lookup_by_id(
    conn: sqlite3.Connection,
    table: str,
    entry_id: int,
) -> Dict[str, Any]:
    """Look up a registry entry by integer ID. Strict — never auto-creates.

    Logic flow:
    1. SELECT id, name, created_at FROM <table> WHERE id = ?
    2. If found -> return row as dict {id, name, created_at}
    3. If not found -> raise RegistryLookupError
       - No auto-create for ID lookups: if the user passes an ID, they
         expect it to exist. Creating a new entry for a random int makes
         no sense.

    Args:
        conn: SQLite connection.
        table: Table name ("tags" or "attr_keys").
        entry_id: The integer ID to look up.

    Returns:
        Dict with id (int), name (str), created_at (str).

    Raises:
        RegistryLookupError: If no entry with this ID exists.
    """
    pass


def resolve_name_or_id(
    conn: sqlite3.Connection,
    table: str,
    name_or_id: str,
    normalize_fn: Callable[[str], str],
    autocreate: bool = False,
) -> Dict[str, Any]:
    """Dispatch a user-provided identifier to name or ID lookup.

    Detection logic:
    1. Try to parse name_or_id as int:
       - If it parses as int -> call lookup_by_id(conn, table, int_val)
       - ID lookups NEVER auto-create, regardless of autocreate param
    2. If it doesn't parse as int -> call lookup_by_name(conn, table,
       name_or_id, normalize_fn, autocreate)

    This is the main entry point for commands like `memory tag remove foo`
    or `memory tag remove 42` — the user can pass either form and this
    function routes to the correct lookup.

    Edge cases:
    - "42" -> parsed as int, looked up by ID
    - "42abc" -> not an int, looked up by name (normalized)
    - "  My Tag  " -> not an int, looked up by name (normalized to "my tag")
    - Negative IDs: "-1" -> parsed as int, looked up by ID (will not be found)

    Args:
        conn: SQLite connection.
        table: Table name ("tags" or "attr_keys").
        name_or_id: User-provided identifier (string).
        normalize_fn: Normalization function for name lookups.
        autocreate: Passed to lookup_by_name if dispatching to name lookup.

    Returns:
        Dict with id (int), name (str), created_at (str).

    Raises:
        RegistryLookupError: If the entry is not found.
    """
    pass
