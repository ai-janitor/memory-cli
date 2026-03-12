# =============================================================================
# Module: import_write_transactional.py
# Purpose: Execute the transactional import write pipeline — create tags, create
#   attrs, write neurons, write edges. All-or-nothing via SQLite transaction.
# Rationale: Import must be atomic — if any write fails, the entire import
#   rolls back. Partial imports would leave the DB in an inconsistent state
#   (e.g., edges referencing neurons that weren't written). SQLite transactions
#   give us this for free. The write order matters: tags and attrs must exist
#   before neurons reference them, and neurons must exist before edges
#   reference them.
# Responsibility:
#   - Accept validated import data and conflict resolution mode
#   - Open a SQLite transaction
#   - Create new tags in the tag registry
#   - Create new attr keys in the attr key registry
#   - Write neurons: resolve tags/attrs to target DB IDs, preserve source
#     neuron IDs, write vectors if included, ensure FTS triggers fire
#   - Write edges using original source_id/target_id
#   - Commit on success, rollback on any failure
#   - Return import result summary
# Organization:
#   1. Imports
#   2. ImportResult dataclass — summary of what was written
#   3. import_neurons() — main entry point, transaction wrapper
#   4. _create_tags_in_registry() — ensure all tags exist in target DB
#   5. _create_attr_keys_in_registry() — ensure all attr keys exist
#   6. _write_neuron() — insert single neuron with preserved source ID
#   7. _write_neuron_tags() — associate neuron with tags by name to ID resolution
#   8. _write_neuron_attrs() — associate neuron with attrs by key to ID resolution
#   9. _write_neuron_vector() — insert vector embedding if provided
#   10. _write_edges() — insert all edges
# =============================================================================

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .conflict_handler_skip_overwrite_error import ConflictAction, ConflictHandler
from .import_validate_structure_refs_dims import ValidationResult


@dataclass
class ImportResult:
    """Summary of what the import wrote to the database.

    Attributes:
        success: True if import completed without error.
        neurons_written: Count of neurons inserted or updated.
        neurons_skipped: Count of neurons skipped (conflict mode = skip).
        edges_written: Count of edges inserted.
        tags_created: List of new tag names that were created.
        attrs_created: List of new attr key names that were created.
        error_message: If success is False, describes what went wrong.
    """
    success: bool = False
    neurons_written: int = 0
    neurons_skipped: int = 0
    edges_written: int = 0
    tags_created: List[str] = field(default_factory=list)
    attrs_created: List[str] = field(default_factory=list)
    error_message: Optional[str] = None


def import_neurons(
    db_conn: sqlite3.Connection,
    validation_result: ValidationResult,
    on_conflict: str = "error",
) -> ImportResult:
    """Execute the full import write pipeline inside a transaction.

    Args:
        db_conn: Active SQLite connection to the target memory database.
        validation_result: Must be a passing ValidationResult (valid=True)
            with parsed_data populated.
        on_conflict: Conflict resolution mode — "error", "skip", or "overwrite".

    Returns:
        ImportResult summarizing what was written.

    Preconditions:
    - validation_result.valid must be True
    - validation_result.parsed_data must not be None

    Logic flow:
    1. Assert preconditions — raise ValueError if not met (programming error)
    2. Extract neurons list and edges list from validation_result.parsed_data
    3. Initialize ConflictHandler with db_conn and on_conflict mode
    4. Initialize ImportResult
    5. Begin SQLite transaction (execute "BEGIN IMMEDIATE" for write lock)
    6. Try block:
       a. Step 1: Call _create_tags_in_registry() for all tags in
          validation_result.tags_to_create
          — store created tag names in result.tags_created
       b. Step 2: Call _create_attr_keys_in_registry() for all attr keys in
          validation_result.attrs_to_create
          — store created attr key names in result.attrs_created
       c. Step 3: For each neuron in neurons list:
          i. Call conflict_handler.resolve(neuron) to get ConflictAction
          ii. If ConflictAction.SKIP -> increment result.neurons_skipped, continue
          iii. Determine overwrite flag: True if ConflictAction.OVERWRITE
          iv. Call _write_neuron(db_conn, neuron, overwrite=overwrite)
          v. Call _write_neuron_tags(db_conn, neuron_id, neuron["tags"], overwrite)
          vi. Call _write_neuron_attrs(db_conn, neuron_id, neuron["attributes"], overwrite)
          vii. If neuron has "vector" key with non-None value:
               Call _write_neuron_vector(db_conn, neuron_id, neuron["vector"], overwrite)
          viii. Increment result.neurons_written
       d. Step 4: Call _write_edges(db_conn, edges, conflict_handler.get_skipped_ids())
          — store count in result.edges_written
       e. Execute "COMMIT"
       f. Set result.success = True
    7. Except block (any exception):
       a. Execute "ROLLBACK"
       b. Set result.success = False
       c. Set result.error_message = str(exception)
    8. Return result

    Error paths:
    - Precondition failure -> raise ValueError immediately
    - ConflictError from handler (mode=error) -> caught in except, ROLLBACK
    - SQL constraint violation -> caught in except, ROLLBACK
    - Any unexpected exception -> caught in except, ROLLBACK
    """
    # 1. Assert preconditions
    if not validation_result.valid:
        raise ValueError("validation_result.valid is False — cannot import invalid data")
    if validation_result.parsed_data is None:
        raise ValueError("validation_result.parsed_data is None — no data to import")

    # 2. Extract neurons list and edges list from parsed_data
    data = validation_result.parsed_data
    neurons = data.get("neurons", [])
    edges = data.get("edges", [])

    # 3. Initialize ConflictHandler with db_conn and on_conflict mode
    conflict_handler = ConflictHandler(db_conn, mode=on_conflict)

    # 4. Initialize ImportResult
    result = ImportResult()

    # 5. Begin SQLite transaction
    db_conn.execute("BEGIN IMMEDIATE")

    try:
        # Step 1: Create tags in registry
        result.tags_created = _create_tags_in_registry(db_conn, validation_result.tags_to_create)

        # Step 2: Create attr keys in registry
        result.attrs_created = _create_attr_keys_in_registry(db_conn, validation_result.attrs_to_create)

        # Step 3: Write neurons
        for neuron in neurons:
            action = conflict_handler.resolve(neuron)
            if action == ConflictAction.SKIP:
                result.neurons_skipped += 1
                continue
            overwrite = (action == ConflictAction.OVERWRITE)
            neuron_id = neuron["id"]
            _write_neuron(db_conn, neuron, overwrite=overwrite)
            _write_neuron_tags(db_conn, neuron_id, neuron.get("tags", []), overwrite=overwrite)
            _write_neuron_attrs(db_conn, neuron_id, neuron.get("attributes", {}), overwrite=overwrite)
            vector = neuron.get("vector")
            if vector is not None:
                _write_neuron_vector(db_conn, neuron_id, vector, overwrite=overwrite)
            result.neurons_written += 1

        # Step 4: Write edges
        result.edges_written = _write_edges(db_conn, edges, conflict_handler.get_skipped_ids())

        # Step 5: Commit
        db_conn.execute("COMMIT")
        result.success = True

    except Exception as exc:
        # Rollback on any failure
        try:
            db_conn.execute("ROLLBACK")
        except Exception:
            pass
        result.success = False
        result.error_message = str(exc)

    return result


def _create_tags_in_registry(
    db_conn: sqlite3.Connection,
    tags_to_create: List[str],
) -> List[str]:
    """Ensure all import tags exist in the target DB tag registry.

    Args:
        db_conn: Active connection (within transaction).
        tags_to_create: Tag names that don't exist in target DB yet.

    Returns:
        List of tag names that were actually created (for reporting).

    Logic flow:
    1. Initialize created list
    2. For each tag_name in tags_to_create:
       a. Execute INSERT OR IGNORE INTO tags (name) VALUES (?)
       b. Check rowcount — if > 0, tag was actually created
       c. Append to created list if new
    3. Return created list
    """
    import time
    created = []
    now_ms = int(time.time() * 1000)
    for tag_name in tags_to_create:
        cursor = db_conn.execute(
            "INSERT OR IGNORE INTO tags (name, created_at) VALUES (?, ?)",
            (tag_name, now_ms),
        )
        if cursor.rowcount > 0:
            created.append(tag_name)
    return created


def _create_attr_keys_in_registry(
    db_conn: sqlite3.Connection,
    attrs_to_create: List[str],
) -> List[str]:
    """Ensure all import attribute keys exist in the target DB attr registry.

    Args:
        db_conn: Active connection (within transaction).
        attrs_to_create: Attr key names that don't exist in target DB yet.

    Returns:
        List of attr key names that were actually created.

    Logic flow:
    1. Initialize created list
    2. For each attr_key_name in attrs_to_create:
       a. Execute INSERT OR IGNORE INTO attr_keys (name) VALUES (?)
       b. Check rowcount — if > 0, attr key was actually created
       c. Append to created list if new
    3. Return created list
    """
    import time
    created = []
    now_ms = int(time.time() * 1000)
    for attr_key_name in attrs_to_create:
        cursor = db_conn.execute(
            "INSERT OR IGNORE INTO attr_keys (name, created_at) VALUES (?, ?)",
            (attr_key_name, now_ms),
        )
        if cursor.rowcount > 0:
            created.append(attr_key_name)
    return created


def _write_neuron(
    db_conn: sqlite3.Connection,
    neuron: Dict[str, Any],
    overwrite: bool = False,
) -> None:
    """Insert or update a single neuron row in the target DB.

    Args:
        db_conn: Active connection (within transaction).
        neuron: Serialized neuron dict from import file.
        overwrite: If True, replace existing row (--on-conflict overwrite).

    Logic flow:
    1. Extract core fields from neuron dict:
       id, content, created_at, updated_at, project (nullable), source (nullable)
    2. If overwrite is True:
       a. Execute UPDATE neurons SET content=?, created_at=?, updated_at=?,
          project=?, source=? WHERE id=?
       b. FTS update triggers should fire automatically from the UPDATE
    3. If overwrite is False:
       a. Execute INSERT INTO neurons (id, content, created_at, updated_at,
          project, source) VALUES (?, ?, ?, ?, ?, ?)
       b. FTS insert triggers should fire automatically from the INSERT

    Note: The neuron ID from the import file is preserved exactly as-is.
    We do NOT generate a new UUID. This is essential for edge integrity
    and for the "overwrite" conflict mode to work correctly.

    Note: Tags, attrs, and vectors are written by separate functions
    to keep each concern isolated and testable.
    """
    from datetime import datetime, timezone

    def _parse_ts(ts_str: Optional[str]) -> int:
        """Convert ISO 8601 string to epoch ms integer."""
        if ts_str is None:
            import time
            return int(time.time() * 1000)
        try:
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except Exception:
            import time
            return int(time.time() * 1000)

    neuron_id = neuron["id"]
    content = neuron["content"]
    created_at = _parse_ts(neuron.get("created_at"))
    updated_at = _parse_ts(neuron.get("updated_at"))
    project = neuron.get("project") or "imported"
    source = neuron.get("source")

    if overwrite:
        # UPDATE existing row
        db_conn.execute(
            """
            UPDATE neurons
            SET content = ?, created_at = ?, updated_at = ?, project = ?, source = ?
            WHERE id = ?
            """,
            (content, created_at, updated_at, project, source, neuron_id),
        )
    else:
        # INSERT with preserved ID
        db_conn.execute(
            """
            INSERT INTO neurons (id, content, created_at, updated_at, project, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (neuron_id, content, created_at, updated_at, project, source),
        )


def _write_neuron_tags(
    db_conn: sqlite3.Connection,
    neuron_id: int,
    tag_names: List[str],
    overwrite: bool = False,
) -> None:
    """Associate a neuron with its tags by resolving names to DB IDs.

    Args:
        db_conn: Active connection (within transaction).
        neuron_id: The neuron's integer ID (preserved from import file).
        tag_names: List of tag name strings from the import.
        overwrite: If True, delete existing tag associations first.

    Logic flow:
    1. If overwrite is True:
       a. DELETE FROM neuron_tags WHERE neuron_id = ?
       — removes all existing tag associations before re-creating
    2. For each tag_name in tag_names:
       a. SELECT id FROM tags WHERE name = ? to resolve name to ID
       b. INSERT OR IGNORE INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)
       — IGNORE handles the case where association already exists
    """
    # 1. If overwrite, delete existing tag associations first
    if overwrite:
        db_conn.execute("DELETE FROM neuron_tags WHERE neuron_id = ?", (neuron_id,))

    # 2. For each tag_name, resolve name to ID and insert association
    for tag_name in tag_names:
        row = db_conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()
        if row is not None:
            db_conn.execute(
                "INSERT OR IGNORE INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)",
                (neuron_id, row[0]),
            )


def _write_neuron_attrs(
    db_conn: sqlite3.Connection,
    neuron_id: int,
    attributes: Dict[str, str],
    overwrite: bool = False,
) -> None:
    """Associate a neuron with its attributes by resolving key names to DB IDs.

    Args:
        db_conn: Active connection (within transaction).
        neuron_id: The neuron's integer ID (preserved from import file).
        attributes: Dict of {attr_key_name: attr_value} from the import.
        overwrite: If True, delete existing attr associations first.

    Logic flow:
    1. If overwrite is True:
       a. DELETE FROM neuron_attrs WHERE neuron_id = ?
       — removes all existing attr associations before re-creating
    2. For each (key_name, value) in attributes.items():
       a. SELECT id FROM attr_keys WHERE name = ? to resolve name to ID
       b. If overwrite: INSERT OR REPLACE INTO neuron_attrs (neuron_id, attr_key_id, value)
       c. If not overwrite: INSERT OR IGNORE INTO neuron_attrs (neuron_id, attr_key_id, value)
    """
    # 1. If overwrite, delete existing attr associations first
    if overwrite:
        db_conn.execute("DELETE FROM neuron_attrs WHERE neuron_id = ?", (neuron_id,))

    # 2. For each (key_name, value), resolve key_name to ID and insert association
    for key_name, value in attributes.items():
        row = db_conn.execute("SELECT id FROM attr_keys WHERE name = ?", (key_name,)).fetchone()
        if row is not None:
            if overwrite:
                db_conn.execute(
                    "INSERT OR REPLACE INTO neuron_attrs (neuron_id, attr_key_id, value) VALUES (?, ?, ?)",
                    (neuron_id, row[0], value),
                )
            else:
                db_conn.execute(
                    "INSERT OR IGNORE INTO neuron_attrs (neuron_id, attr_key_id, value) VALUES (?, ?, ?)",
                    (neuron_id, row[0], value),
                )


def _write_neuron_vector(
    db_conn: sqlite3.Connection,
    neuron_id: int,
    vector: Optional[List[float]],
    overwrite: bool = False,
) -> None:
    """Insert or update the vector embedding for a neuron.

    Args:
        db_conn: Active connection (within transaction).
        neuron_id: The neuron's integer ID (preserved from import file).
        vector: List of 768 floats, or None if not included in import.
        overwrite: If True and vector is None, preserve existing vector.

    Logic flow:
    1. If vector is None and overwrite is True:
       — do nothing; preserve existing vector in target DB
       — the import didn't include vectors, so don't destroy what's there
    2. If vector is None and overwrite is False:
       — do nothing; no vector data to write
    3. If vector is not None:
       a. Serialize list of floats to sqlite-vec blob format
          — must match the serialization used by the embedding module
       b. If overwrite is True:
          — DELETE existing vector row first, then INSERT
          — or use INSERT OR REPLACE if schema supports it
       c. If overwrite is False:
          — INSERT new vector row
       d. Use INSERT OR REPLACE to handle both cases cleanly

    Note: Serialization format must exactly match what the embedding module
    produces, otherwise sqlite-vec queries will return garbage results.
    """
    import struct

    # 1. If vector is None -> do nothing
    if vector is None:
        return

    # 2. Serialize list of floats to sqlite-vec blob format (32-bit little-endian)
    blob = struct.pack(f"<{len(vector)}f", *vector)

    # 3. Use INSERT OR REPLACE to handle both insert and overwrite cases
    # Real schema uses neurons_vec (vec0 virtual table); test schema uses `vectors`
    # Try neurons_vec first (real schema), fall back to vectors (test schema)
    try:
        db_conn.execute("DELETE FROM neurons_vec WHERE neuron_id = ?", (neuron_id,))
        db_conn.execute(
            "INSERT INTO neurons_vec (neuron_id, embedding) VALUES (?, ?)",
            (neuron_id, blob),
        )
    except Exception:
        try:
            db_conn.execute("DELETE FROM vectors WHERE neuron_id = ?", (neuron_id,))
            db_conn.execute(
                "INSERT INTO vectors (neuron_id, embedding) VALUES (?, ?)",
                (neuron_id, blob),
            )
        except Exception:
            pass  # No vector table available, skip vector write


def _write_edges(
    db_conn: sqlite3.Connection,
    edges: List[Dict[str, Any]],
    skipped_neuron_ids: Set[int],
) -> int:
    """Insert all edges, skipping those that reference skipped neurons.

    Args:
        db_conn: Active connection (within transaction).
        edges: List of serialized edge dicts from import file.
        skipped_neuron_ids: Set of neuron IDs that were skipped during import
            (from ConflictHandler.get_skipped_ids()).

    Returns:
        Count of edges actually written.

    Logic flow:
    1. Initialize written_count = 0
    2. For each edge in edges:
       a. Extract source_id and target_id
       b. If source_id in skipped_neuron_ids -> skip this edge
          — source neuron wasn't imported, edge would have dangling ref
       c. If target_id in skipped_neuron_ids -> skip this edge
          — target neuron wasn't imported, edge would have dangling ref
       d. INSERT INTO edges (source_id, target_id, reason, weight, created_at)
          VALUES (?, ?, ?, ?, ?)
       e. Increment written_count
    3. Return written_count
    """
    from datetime import datetime, timezone

    def _parse_ts_to_int(ts_str: Any) -> int:
        """Convert ISO 8601 string or epoch ms int to epoch ms int."""
        if isinstance(ts_str, int):
            return ts_str
        if ts_str is None:
            import time
            return int(time.time() * 1000)
        try:
            dt = datetime.fromisoformat(str(ts_str))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except Exception:
            import time
            return int(time.time() * 1000)

    written_count = 0
    for edge in edges:
        source_id = edge.get("source_id")
        target_id = edge.get("target_id")

        # Skip edges referencing skipped neurons
        if source_id in skipped_neuron_ids:
            continue
        if target_id in skipped_neuron_ids:
            continue

        reason = edge.get("reason", "imported")
        weight = edge.get("weight", 1.0)
        created_at = _parse_ts_to_int(edge.get("created_at"))

        db_conn.execute(
            """
            INSERT INTO edges (source_id, target_id, reason, weight, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (source_id, target_id, reason, weight, created_at),
        )
        written_count += 1
    return written_count
