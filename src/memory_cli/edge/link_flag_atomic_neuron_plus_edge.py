# =============================================================================
# Module: link_flag_atomic_neuron_plus_edge.py
# Purpose: Atomic creation of a neuron and an edge to an existing neuron in a
#   single transaction. Implements the --link flag on `memory neuron add`.
#   If either the neuron INSERT or the edge INSERT fails, the entire
#   transaction rolls back — no partial state.
# Rationale: The --link flag is a convenience that creates a neuron and
#   immediately connects it to an existing neuron. Without atomicity, a crash
#   between neuron creation and edge creation would leave an orphan neuron
#   with no link, which violates user intent. The single-transaction approach
#   guarantees all-or-nothing semantics. This differs from the non-atomic
#   approach in neuron_add where link failure is non-fatal — this module is
#   used when the caller requires strict atomicity.
# Responsibility:
#   - Validate target neuron exists BEFORE any writes
#   - Validate --link-reason is present and non-empty when --link is used
#   - Create neuron record in a single transaction
#   - Create edge (new neuron -> target) in the same transaction
#   - New neuron is ALWAYS the source, linked neuron is ALWAYS the target
#   - Rollback entire transaction if edge creation fails
#   - Return both the created neuron and edge records on success
# Organization:
#   1. Imports
#   2. LinkAtomicError — custom exception
#   3. link_flag_atomic_create() — main entry point
#   4. _validate_link_inputs() — pre-write validation
#   5. _create_neuron_and_edge() — transactional write
# =============================================================================

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------------------------------------------------------
# Constants — default link weight, table references.
# -----------------------------------------------------------------------------
DEFAULT_LINK_WEIGHT = 1.0


class LinkAtomicError(Exception):
    """Raised when atomic neuron+edge creation fails.

    Attributes:
        exit_code: CLI exit code — 1 for not-found, 2 for validation errors.
        message: Human-readable description of the failure.
        step: Which step failed — 'validate', 'neuron_write', 'edge_write'.
    """

    def __init__(self, message: str, exit_code: int = 2, step: str = "validate") -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.step = step


def link_flag_atomic_create(
    conn: sqlite3.Connection,
    content: str,
    link_target_id: int,
    link_reason: str,
    tags: Optional[List[str]] = None,
    source: Optional[str] = None,
    attrs: Optional[Dict[str, str]] = None,
    link_weight: Optional[float] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Atomically create a neuron and an edge to an existing neuron.

    CLI: `memory neuron add "<content>" --link <neuron_id> --link-reason "<reason>"
          [--link-weight <float>] [--tags TAG,...] [--source SOURCE] [--attr KEY=VALUE]`

    Pipeline (all in one transaction):
    1. Validate inputs via _validate_link_inputs()
       a. content must be non-empty after strip
       b. link_reason must be non-empty after strip
       c. link_target_id must reference an existing neuron
          - SELECT id FROM neurons WHERE id = ?
          - Not found -> LinkAtomicError(exit_code=1)
       d. link_weight (if provided) must be > 0.0
    2. Create neuron and edge atomically via _create_neuron_and_edge()
       a. BEGIN TRANSACTION (explicit or via conn as context manager)
       b. INSERT neuron record (content, created_at, updated_at, project, source, status)
       c. Get new neuron_id from cursor.lastrowid
       d. Process tags: resolve via tag registry, insert neuron_tags junction rows
       e. Process attrs: resolve via attr registry, insert neuron_attrs rows
       f. INSERT edge record (source_id=new_neuron_id, target_id=link_target_id,
          reason=link_reason, weight=resolved_weight, created_at)
       g. COMMIT
       h. If ANY step fails: ROLLBACK — no neuron, no edge, no tag/attr associations
    3. Return tuple of (neuron_dict, edge_dict)

    Error semantics (differ from non-atomic neuron_add):
    - ANY failure -> ROLLBACK entire transaction, nothing written
    - This is stricter than neuron_add where embedding/link failures are non-fatal
    - The caller (CLI handler) decides whether to fall back to non-atomic creation

    Note: Embedding is NOT done inside the transaction. The caller should
    trigger embedding after this function returns successfully. Embedding
    failure should be handled as non-fatal (same as regular neuron_add).

    Args:
        conn: SQLite connection with neurons, edges, tags, attrs tables.
        content: Neuron content text (required, non-empty).
        link_target_id: ID of existing neuron to link to (must exist).
        link_reason: Reason for the edge (required, non-empty).
        tags: Optional list of tag names.
        source: Optional source identifier.
        attrs: Optional dict of attribute key=value pairs.
        link_weight: Optional edge weight (default 1.0, must be > 0.0).

    Returns:
        Tuple of (neuron_dict, edge_dict) on success.

    Raises:
        LinkAtomicError: On any validation or write failure (transaction rolled back).
    """
    # --- Step 1: Validate all inputs before any writes ---
    # _validate_link_inputs(conn, content, link_target_id, link_reason, link_weight)
    _validate_link_inputs(conn, content, link_target_id, link_reason, link_weight)

    # --- Step 2: Create neuron and edge atomically ---
    # neuron_dict, edge_dict = _create_neuron_and_edge(
    #     conn, content, link_target_id, link_reason,
    #     tags=tags, source=source, attrs=attrs,
    #     link_weight=link_weight if link_weight is not None else DEFAULT_LINK_WEIGHT,
    # )
    neuron_dict, edge_dict = _create_neuron_and_edge(
        conn, content, link_target_id, link_reason,
        tags=tags, source=source, attrs=attrs,
        link_weight=link_weight if link_weight is not None else DEFAULT_LINK_WEIGHT,
    )

    # --- Step 3: Return both records ---
    # return (neuron_dict, edge_dict)
    return (neuron_dict, edge_dict)


def _validate_link_inputs(
    conn: sqlite3.Connection,
    content: str,
    link_target_id: int,
    link_reason: str,
    link_weight: Optional[float],
) -> None:
    """Validate all inputs before starting the transaction.

    Validation order:
    1. content must be non-empty after strip
       - Empty -> LinkAtomicError("Content cannot be empty", exit_code=2, step='validate')
    2. link_reason must be non-empty after strip
       - Empty -> LinkAtomicError("Link reason cannot be empty", exit_code=2, step='validate')
    3. Target neuron must exist
       - SELECT id FROM neurons WHERE id = ?
       - Not found -> LinkAtomicError(
             f"Link target {link_target_id} not found", exit_code=1, step='validate'
         )
    4. link_weight (if not None) must be > 0.0
       - Invalid -> LinkAtomicError(
             f"Link weight must be > 0.0, got {link_weight}", exit_code=2, step='validate'
         )

    Args:
        conn: SQLite connection for target neuron lookup.
        content: Raw content string.
        link_target_id: Target neuron ID.
        link_reason: Raw reason string.
        link_weight: Optional weight value.

    Raises:
        LinkAtomicError: On any validation failure.
    """
    if not content.strip():
        raise LinkAtomicError("Content cannot be empty", exit_code=2, step="validate")
    if not link_reason.strip():
        raise LinkAtomicError("Link reason cannot be empty", exit_code=2, step="validate")
    row = conn.execute("SELECT id FROM neurons WHERE id = ?", (link_target_id,)).fetchone()
    if row is None:
        raise LinkAtomicError(
            f"Link target {link_target_id} not found", exit_code=1, step="validate"
        )
    if link_weight is not None and link_weight <= 0.0:
        raise LinkAtomicError(
            f"Link weight must be > 0.0, got {link_weight}", exit_code=2, step="validate"
        )


def _create_neuron_and_edge(
    conn: sqlite3.Connection,
    content: str,
    link_target_id: int,
    link_reason: str,
    tags: Optional[List[str]],
    source: Optional[str],
    attrs: Optional[Dict[str, str]],
    link_weight: float,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create neuron and edge in a single atomic transaction.

    Logic flow (all within one transaction):
    1. Generate timestamps: created_at = updated_at = int(time.time() * 1000)
    2. Detect project name via detect_project()
    3. INSERT INTO neurons (content, created_at, updated_at, project, source, status)
       VALUES (?, ?, ?, ?, ?, 'active')
    4. Capture neuron_id = cursor.lastrowid
    5. For each tag in tags (if any):
       a. Resolve tag_id via tag_autocreate(conn, tag_name)
       b. INSERT INTO neuron_tags (neuron_id, tag_id)
    6. For each (key, value) in attrs (if any):
       a. Resolve attr_key_id via attr_autocreate(conn, key)
       b. INSERT INTO neuron_attrs (neuron_id, attr_key_id, value)
    7. INSERT INTO edges (source_id, target_id, reason, weight, created_at)
       VALUES (neuron_id, link_target_id, link_reason, link_weight, created_at)
       - source = NEW neuron, target = EXISTING linked neuron
    8. COMMIT transaction
    9. Build neuron_dict with all fields + hydrated tags + attrs
    10. Build edge_dict with all edge fields
    11. Return (neuron_dict, edge_dict)

    On any failure at steps 3-7:
    - ROLLBACK transaction
    - Raise LinkAtomicError with step='neuron_write' or step='edge_write'

    Args:
        conn: SQLite connection (transaction managed here).
        content: Validated content text.
        link_target_id: Validated target neuron ID.
        link_reason: Validated reason string.
        tags: Optional list of tag names.
        source: Optional source string.
        attrs: Optional dict of attr key -> value.
        link_weight: Validated positive weight.

    Returns:
        Tuple of (neuron_dict, edge_dict).

    Raises:
        LinkAtomicError: On any DB failure (transaction rolled back).
    """
    from memory_cli.neuron.project_detection_git_or_cwd import detect_project
    from memory_cli.registries.tag_registry_crud_normalize_autocreate import tag_autocreate
    from memory_cli.registries.attr_registry_crud_normalize_autocreate import attr_autocreate

    clean_content = content.strip()
    clean_reason = link_reason.strip()

    try:
        # 1. Generate timestamps
        created_at = int(time.time() * 1000)
        updated_at = created_at

        # 2. Detect project name
        project = detect_project()

        # 3. INSERT neuron
        cursor = conn.execute(
            "INSERT INTO neurons (content, created_at, updated_at, project, source, status) "
            "VALUES (?, ?, ?, ?, ?, 'active')",
            (clean_content, created_at, updated_at, project, source),
        )
        neuron_id = cursor.lastrowid

        # 4. Tags: resolve via tag_autocreate, insert neuron_tags junction rows
        tag_names: List[str] = []
        for tag_name in (tags or []):
            tag_id = tag_autocreate(conn, tag_name)
            conn.execute(
                "INSERT INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)",
                (neuron_id, tag_id),
            )
            tag_names.append(tag_name)

        # 5. Attrs: resolve via attr_autocreate, insert neuron_attrs rows
        attr_dict: Dict[str, str] = {}
        for key, value in (attrs or {}).items():
            attr_key_id = attr_autocreate(conn, key)
            conn.execute(
                "INSERT INTO neuron_attrs (neuron_id, attr_key_id, value) VALUES (?, ?, ?)",
                (neuron_id, attr_key_id, value),
            )
            attr_dict[key] = value

        # 6. INSERT edge (source=new neuron, target=existing linked neuron)
        edge_created_at = int(time.time() * 1000)
        conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, weight, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (neuron_id, link_target_id, clean_reason, link_weight, edge_created_at),
        )

        # 7. COMMIT — sqlite3 with isolation_level=None would require explicit commit,
        #    but with default isolation_level conn auto-manages. Use conn.commit() to be safe.
        conn.commit()

        # 8. Build return dicts
        neuron_dict: Dict[str, Any] = {
            "id": neuron_id,
            "content": clean_content,
            "created_at": created_at,
            "updated_at": updated_at,
            "project": project,
            "source": source,
            "status": "active",
            "embedding_updated_at": None,
            "tags": tag_names,
            "attrs": attr_dict,
        }
        edge_dict: Dict[str, Any] = {
            "source_id": neuron_id,
            "target_id": link_target_id,
            "reason": clean_reason,
            "weight": link_weight,
            "created_at": edge_created_at,
        }

        return (neuron_dict, edge_dict)

    except Exception as exc:
        conn.rollback()
        if isinstance(exc, LinkAtomicError):
            raise
        raise LinkAtomicError(
            f"Atomic neuron+edge creation failed: {exc}",
            exit_code=2,
            step="neuron_write" if "edges" not in str(exc) else "edge_write",
        ) from exc
