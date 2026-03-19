# =============================================================================
# Module: neuron_add_with_autotags_and_embed.py
# Purpose: Full neuron add pipeline — validate inputs, resolve auto-tags,
#   write the neuron record with tag/attr associations, embed the content,
#   and optionally create a link to another neuron.
# Rationale: Neuron creation is the most complex write path in the system.
#   It must orchestrate multiple subsystems (tag registry, attr registry,
#   embedding engine, edge module) in a specific order with clear failure
#   semantics: the neuron write is the critical transaction, embedding
#   failure is a non-fatal warning, and link failure doesn't rollback the
#   neuron. Centralizing this pipeline prevents scattered partial-create
#   logic.
# Responsibility:
#   - Validate all inputs before any writes
#   - Resolve auto-tags (timestamp, project) via auto_tag_capture
#   - Write neuron record + tag associations + attr pairs in one transaction
#   - Trigger embedding unless --no-embed (non-fatal on failure)
#   - Create edge via --link if specified (non-fatal on failure)
#   - Return the created neuron record
# Organization:
#   1. Imports
#   2. Constants (table names, status values)
#   3. NeuronAddError — custom exception
#   4. neuron_add() — main pipeline entry point
#   5. _validate_add_inputs() — input validation helper
#   6. _write_neuron_record() — core INSERT + junction writes
#   7. _embed_neuron() — embedding delegation helper
#   8. _build_embedding_input() — format content+tags for embedding
#   9. _link_neuron() — optional edge creation delegation
# =============================================================================

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------------------------------------------------------
# Constants — table and column names, valid status values.
# Single source of truth for neuron table schema references.
# -----------------------------------------------------------------------------
NEURONS_TABLE = "neurons"
NEURON_TAGS_TABLE = "neuron_tags"
NEURON_ATTRS_TABLE = "neuron_attrs"
STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"


class NeuronAddError(Exception):
    """Raised when neuron add pipeline fails.

    Attributes:
        step: Which pipeline step failed (validate, write, embed, link).
        details: Human-readable description of what went wrong.
    """

    pass


def neuron_add(
    conn: sqlite3.Connection,
    content: str,
    tags: Optional[List[str]] = None,
    source: Optional[str] = None,
    attrs: Optional[Dict[str, str]] = None,
    link_target_id: Optional[int] = None,
    link_reason: Optional[str] = None,
    no_embed: bool = False,
) -> Dict[str, Any]:
    """Create a new neuron with auto-tags, embedding, and optional link.

    CLI: `memory neuron add <content> [--tags TAG,...] [--source SOURCE]
          [--attr KEY=VALUE ...] [--link NEURON_ID --reason REASON] [--no-embed]`

    Pipeline steps:
    1. Validate inputs via _validate_add_inputs()
       - content must be non-empty (strip whitespace first)
       - if link_target_id is set, link_reason must also be set
       - if link_target_id is set, target must exist and be active
       - tags list items are raw strings (normalization happens in tag registry)
       - attrs dict keys are raw strings (normalization happens in attr registry)
    2. Resolve auto-tags via capture_auto_tags()
       - Timestamp tag: YYYY-MM-DD of current UTC date
       - Project tag: detected from git remote / dir / cwd
       - Merge auto-tags with user-provided tags (auto-tags always included)
       - Deduplicate tag list (after normalization)
    3. Write neuron record via _write_neuron_record()
       - BEGIN TRANSACTION (or use conn as context manager)
       - INSERT INTO neurons (content, created_at, updated_at, project, source, status)
       - For each tag: resolve via tag_autocreate() -> INSERT INTO neuron_tags
       - For each attr: resolve key via attr_autocreate() -> INSERT INTO neuron_attrs
       - FTS triggers fire automatically on neuron INSERT (no manual FTS update)
       - COMMIT
    4. Embed unless no_embed via _embed_neuron()
       - Build embedding input: "<content> [<tag1> <tag2> ... <tagN>]"
       - Tags sorted alphabetically in the bracket suffix
       - Call embedding engine (spec #5) to compute vector
       - Store vector via sqlite-vec
       - UPDATE neurons SET embedding_updated_at = ? WHERE id = ?
       - On failure: log warning, do NOT rollback neuron, do NOT re-raise
       - The neuron exists without embedding — background job can fix later
    5. Optional link via _link_neuron()
       - Delegate to edge module (spec #7) to create edge
       - source_id = new neuron id, target_id = link_target_id, reason = link_reason
       - On failure: log warning, do NOT rollback neuron, do NOT re-raise
    6. Return created neuron as dict:
       - id, content, created_at, updated_at, project, source, status,
         embedding_updated_at, tags (list of tag names), attrs (dict of key->value)

    Error semantics:
    - Validation failure -> raise NeuronAddError (nothing written)
    - DB write failure -> raise NeuronAddError (transaction rolled back)
    - Embedding failure -> warning logged, neuron exists, embedding_updated_at is None
    - Link failure -> warning logged, neuron exists without the link

    Args:
        conn: SQLite connection with neuron/tag/attr tables.
        content: Neuron content text (required, non-empty).
        tags: Optional list of tag names to apply.
        source: Optional source identifier (e.g., "chat:session-42").
        attrs: Optional dict of attribute key=value pairs.
        link_target_id: Optional neuron ID to link to.
        link_reason: Required if link_target_id is set — reason for the link.
        no_embed: If True, skip embedding step.

    Returns:
        Dict with full neuron record including hydrated tags and attrs.

    Raises:
        NeuronAddError: On validation or DB write failure.
    """
    # --- Step 1: Validate inputs ---
    # Call _validate_add_inputs(conn, content, link_target_id, link_reason)
    # Raises NeuronAddError on any invalid input

    # --- Step 2: Resolve auto-tags ---
    # Call capture_auto_tags() to get [timestamp_tag, project_tag]
    # Merge with user-provided tags via merge_and_deduplicate_tags()
    # Result: all_tags list (auto-tags + user tags, deduplicated)

    # --- Step 3: Write neuron record ---
    # Call _write_neuron_record(conn, content, all_tags, source, attrs)
    # Returns (neuron_id, neuron_dict)

    # --- Step 4: Embed (unless --no-embed) ---
    # if not no_embed:
    #     try: _embed_neuron(conn, neuron_id, content, all_tags)
    #     except Exception as e: log warning with str(e), continue

    # --- Step 5: Optional link ---
    # if link_target_id is not None:
    #     try: _link_neuron(conn, neuron_id, link_target_id, link_reason)
    #     except Exception as e: log warning with str(e), continue

    # --- Step 6: Return neuron record ---
    # Re-fetch via neuron_get to get fully hydrated record (including embed timestamp)
    # return neuron_get(conn, neuron_id)

    import warnings
    from .auto_tag_capture_timestamp_and_project import capture_auto_tags, merge_and_deduplicate_tags
    from .neuron_get_by_id import neuron_get

    _validate_add_inputs(conn, content, link_target_id, link_reason)

    auto_tags = capture_auto_tags()
    all_tags = merge_and_deduplicate_tags(tags, auto_tags)

    neuron_id, _ = _write_neuron_record(conn, content, all_tags, source, attrs)

    if not no_embed:
        try:
            _embed_neuron(conn, neuron_id, content, all_tags)
        except Exception as e:
            warnings.warn(f"Embedding failed for neuron {neuron_id}: {e}")

    if link_target_id is not None:
        try:
            _link_neuron(conn, neuron_id, link_target_id, link_reason)
        except Exception as e:
            warnings.warn(f"Link creation failed for neuron {neuron_id}: {e}")

    return neuron_get(conn, neuron_id)


def _validate_add_inputs(
    conn: sqlite3.Connection,
    content: str,
    link_target_id: Optional[int],
    link_reason: Optional[str],
) -> None:
    """Validate all inputs before any writes.

    Validation rules:
    1. content must be non-empty after stripping whitespace
       - Empty or whitespace-only -> NeuronAddError("Content cannot be empty")
    2. If link_target_id is provided:
       a. link_reason must also be provided and non-empty
          - Missing -> NeuronAddError("--link requires --reason")
       b. Target neuron must exist:
          - SELECT id, status FROM neurons WHERE id = ?
          - Not found -> NeuronAddError("Link target {id} not found")
       c. Target neuron must be active:
          - status != 'active' -> NeuronAddError("Link target {id} is archived")

    Args:
        conn: SQLite connection for target neuron lookup.
        content: Raw content string.
        link_target_id: Optional target neuron ID.
        link_reason: Optional reason string for the link.

    Raises:
        NeuronAddError: On any validation failure.
    """
    if not content or not content.strip():
        raise NeuronAddError("Content cannot be empty")

    if link_target_id is not None:
        if not link_reason or not link_reason.strip():
            raise NeuronAddError("--link requires --reason")

        row = conn.execute(
            "SELECT id, status FROM neurons WHERE id = ?",
            (link_target_id,)
        ).fetchone()

        if row is None:
            raise NeuronAddError(f"Link target {link_target_id} not found")

        if row["status"] != STATUS_ACTIVE:
            raise NeuronAddError(f"Link target {link_target_id} is archived")


def _write_neuron_record(
    conn: sqlite3.Connection,
    content: str,
    tags: List[str],
    source: Optional[str],
    attrs: Optional[Dict[str, str]],
) -> Tuple[int, Dict[str, Any]]:
    """Write neuron record, tag associations, and attribute pairs.

    All writes happen in a single transaction. FTS triggers fire
    automatically on the neuron INSERT — no manual FTS bookkeeping needed.

    Logic flow:
    1. Generate timestamps: created_at = updated_at = current UTC ms
       - int(time.time() * 1000) for millisecond precision
    2. Detect project name via detect_project() for the project column
    3. INSERT INTO neurons (content, created_at, updated_at, project, source, status)
       VALUES (?, ?, ?, ?, ?, 'active')
    4. Get neuron_id from cursor.lastrowid
    5. For each tag in tags:
       a. Resolve tag_id via tag_autocreate(conn, tag_name) from registries
       b. INSERT INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)
       c. UNIQUE constraint handles duplicates (same tag listed twice)
    6. For each (key, value) in attrs:
       a. Resolve attr_key_id via attr_autocreate(conn, key) from registries
       b. INSERT INTO neuron_attrs (neuron_id, attr_key_id, value) VALUES (?, ?, ?)
    7. Build and return neuron dict with all fields + hydrated tags + attrs

    Args:
        conn: SQLite connection (transaction managed here).
        content: Validated content text.
        tags: List of tag names (includes auto-tags, already deduplicated).
        source: Optional source string.
        attrs: Optional dict of attr key -> value.

    Returns:
        Tuple of (neuron_id, neuron_dict).

    Raises:
        NeuronAddError: On DB write failure (transaction rolled back).
    """
    from memory_cli.registries import tag_autocreate, attr_autocreate
    from .project_detection_git_or_cwd import detect_project
    from .neuron_get_by_id import neuron_get

    try:
        now_ms = int(time.time() * 1000)
        project = detect_project()

        cursor = conn.execute(
            """INSERT INTO neurons (content, created_at, updated_at, project, source, status)
               VALUES (?, ?, ?, ?, ?, 'active')""",
            (content, now_ms, now_ms, project, source)
        )
        neuron_id = cursor.lastrowid

        for tag_name in tags:
            tag_id = tag_autocreate(conn, tag_name)
            conn.execute(
                "INSERT OR IGNORE INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)",
                (neuron_id, tag_id)
            )

        if attrs:
            for key, value in attrs.items():
                attr_key_id = attr_autocreate(conn, key)
                conn.execute(
                    "INSERT INTO neuron_attrs (neuron_id, attr_key_id, value) VALUES (?, ?, ?)",
                    (neuron_id, attr_key_id, value)
                )

        conn.commit()
        neuron_dict = neuron_get(conn, neuron_id)
        return (neuron_id, neuron_dict)

    except sqlite3.Error as e:
        conn.rollback()
        raise NeuronAddError(f"DB write failed: {e}") from e


def _embed_neuron(
    conn: sqlite3.Connection,
    neuron_id: int,
    content: str,
    tags: List[str],
) -> None:
    """Compute and store embedding for the neuron.

    Non-fatal — caller catches exceptions and logs warnings.

    Logic flow:
    1. Build embedding input via _build_embedding_input(content, tags)
    2. Call embed_single(input_text, OperationType.INDEX) from embedding module (spec #5)
       - OperationType.INDEX for neuron content (not QUERY — that's for search)
       - Embedding engine adds "search_document: " prefix automatically for INDEX
    3. Store vector via write_vector(conn, neuron_id, vector) from vector_storage module
    4. UPDATE neurons SET embedding_updated_at = <current UTC ms> WHERE id = ?

    Args:
        conn: SQLite connection.
        neuron_id: ID of the neuron to embed.
        content: Neuron content text.
        tags: List of tag names for embedding context.

    Raises:
        Any exception from embedding engine or DB — caller handles.
    """
    import hashlib
    from memory_cli.embedding import embed_single, write_vector, OperationType

    input_text = _build_embedding_input(content, tags)
    input_hash = hashlib.sha256(input_text.encode()).hexdigest()
    vector = embed_single(None, input_text, "index")
    write_vector(conn, neuron_id, vector)
    now_ms = int(time.time() * 1000)
    conn.execute(
        "UPDATE neurons SET embedding_updated_at = ?, embedding_input_hash = ? WHERE id = ?",
        (now_ms, input_hash, neuron_id)
    )
    conn.commit()


def _build_embedding_input(content: str, tags: List[str]) -> str:
    """Format content and tags into the embedding input string.

    Format: "<content> [<tag1> <tag2> ... <tagN>]"
    - Tags are sorted alphabetically
    - Tags are space-separated inside brackets
    - The embedding engine adds "search_document: " prefix — we don't add it here

    Examples:
        _build_embedding_input("Hello world", ["python", "ai"]) -> "Hello world [ai python]"
        _build_embedding_input("Test", []) -> "Test []"

    Args:
        content: Neuron content text.
        tags: List of tag names (will be sorted).

    Returns:
        Formatted embedding input string.
    """
    from memory_cli.embedding import build_embedding_input
    return build_embedding_input(content, tags)


def _link_neuron(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
    reason: str,
) -> None:
    """Create an edge from the new neuron to the link target.

    Delegates to the edge module (spec #7). Non-fatal — caller catches
    exceptions and logs warnings.

    Logic flow:
    1. Import edge creation function from edge module
    2. Call edge_add(conn, source_id, target_id, reason)
    3. Return (no return value — success is silent)

    Args:
        conn: SQLite connection.
        source_id: ID of the newly created neuron.
        target_id: ID of the target neuron to link to.
        reason: Human-readable reason for the link.

    Raises:
        Any exception from edge module — caller handles.
    """
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO edges (source_id, target_id, weight, reason, created_at) VALUES (?, ?, 1.0, ?, ?)",
        (source_id, target_id, reason, now_ms)
    )
    conn.commit()
