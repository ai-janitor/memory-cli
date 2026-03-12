# =============================================================================
# Module: neuron_update_content_tags_attrs.py
# Purpose: Update a neuron's content, tags, attributes, and source — with
#   re-embedding on content change, auto-tag protection, and archived rejection.
# Rationale: Neuron mutation is the second most complex write path after add.
#   It has specific rules: archived neurons reject updates (must restore first),
#   auto-tags can't be removed, content changes trigger re-embedding, and all
#   tag/attr changes must be idempotent. Centralizing this prevents inconsistent
#   mutation logic.
# Responsibility:
#   - Reject updates to archived neurons (exit 2)
#   - Update content with re-embed trigger
#   - Add tags (idempotent) and remove tags (with auto-tag protection)
#   - Set attributes (upsert) and unset attributes
#   - Update source field
#   - Update updated_at timestamp on any mutation
# Organization:
#   1. Imports
#   2. Constants
#   3. NeuronUpdateError — custom exception
#   4. neuron_update() — main entry point
#   5. _update_content() — content change + re-embed trigger
#   6. _add_tags() — idempotent tag addition
#   7. _remove_tags() — tag removal with auto-tag protection
#   8. _set_attrs() — attribute upsert
#   9. _unset_attrs() — attribute removal
#   10. _is_auto_tag() — check if a tag is an auto-tag
# =============================================================================

from __future__ import annotations

import re
import sqlite3
import time
from typing import Any, Dict, List, Optional


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"
# Pattern to match timestamp auto-tags: YYYY-MM-DD
TIMESTAMP_TAG_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class NeuronUpdateError(Exception):
    """Raised when neuron update fails.

    Attributes:
        reason: Why the update failed (not_found, archived, validation, db_error).
        exit_code: Suggested CLI exit code (1 for not found, 2 for archived).
    """

    pass


def neuron_update(
    conn: sqlite3.Connection,
    neuron_id: int,
    content: Optional[str] = None,
    tags_add: Optional[List[str]] = None,
    tags_remove: Optional[List[str]] = None,
    attr_set: Optional[Dict[str, str]] = None,
    attr_unset: Optional[List[str]] = None,
    source: Optional[str] = None,
    no_embed: bool = False,
) -> Dict[str, Any]:
    """Update a neuron's content, tags, attributes, and/or source.

    CLI: `memory neuron update <id> [--content TEXT] [--tags-add TAG,...]
          [--tags-remove TAG,...] [--attr-set KEY=VALUE ...] [--attr-unset KEY ...]
          [--source SOURCE] [--no-embed]`

    Logic flow:
    1. Look up neuron by ID:
       - Not found -> raise NeuronUpdateError(exit_code=1)
    2. Check status:
       - If archived -> raise NeuronUpdateError(exit_code=2, "restore first")
    3. Apply mutations in order:
       a. Content update (if provided):
          - Validate non-empty after strip
          - UPDATE neurons SET content = ?, updated_at = ? WHERE id = ?
          - Trigger re-embed unless no_embed (non-fatal warning on failure)
       b. Tags add (if provided):
          - For each tag: resolve via tag_autocreate, INSERT OR IGNORE into neuron_tags
          - Idempotent: adding an already-present tag is a no-op
       c. Tags remove (if provided):
          - For each tag: check if auto-tag via _is_auto_tag()
            - Auto-tags silently skipped (not an error, just ignored)
          - For non-auto tags: DELETE FROM neuron_tags WHERE neuron_id = ? AND tag_id = ?
          - Removing an absent tag is silently ignored (not an error)
       d. Attrs set (if provided):
          - For each (key, value): resolve key via attr_autocreate
          - INSERT OR REPLACE INTO neuron_attrs (neuron_id, attr_key_id, value)
          - Upsert semantics: existing value overwritten, new key-value created
       e. Attrs unset (if provided):
          - For each key: resolve key ID (if exists)
          - DELETE FROM neuron_attrs WHERE neuron_id = ? AND attr_key_id = ?
          - Unsetting an absent attr is silently ignored
       f. Source update (if provided):
          - UPDATE neurons SET source = ?, updated_at = ? WHERE id = ?
    4. Update updated_at timestamp (if any mutation was applied)
    5. Return fully hydrated neuron dict (via neuron_get)

    Auto-tag protection:
    - Timestamp tags (YYYY-MM-DD format) cannot be removed
    - _is_auto_tag() determines if a tag is auto-generated
    - Attempting to remove an auto-tag is silently ignored, not an error

    Args:
        conn: SQLite connection.
        neuron_id: ID of the neuron to update.
        content: New content text (triggers re-embed).
        tags_add: Tag names to add (idempotent).
        tags_remove: Tag names to remove (auto-tags protected).
        attr_set: Attribute key-value pairs to set (upsert).
        attr_unset: Attribute key names to unset.
        source: New source value.
        no_embed: If True, skip re-embed on content change.

    Returns:
        Fully hydrated neuron dict after mutations.

    Raises:
        NeuronUpdateError: If neuron not found (exit 1) or archived (exit 2).
    """
    # --- Step 1: Lookup neuron ---
    # SELECT id, status FROM neurons WHERE id = ?
    # Not found -> raise NeuronUpdateError(exit_code=1)

    # --- Step 2: Check status ---
    # If status == 'archived' -> raise NeuronUpdateError(exit_code=2)

    # --- Step 3a: Content update ---
    # if content is not None:
    #     validate non-empty after strip
    #     _update_content(conn, neuron_id, content, no_embed)

    # --- Step 3b: Tags add ---
    # if tags_add: _add_tags(conn, neuron_id, tags_add)

    # --- Step 3c: Tags remove ---
    # if tags_remove: _remove_tags(conn, neuron_id, tags_remove)

    # --- Step 3d: Attrs set ---
    # if attr_set: _set_attrs(conn, neuron_id, attr_set)

    # --- Step 3e: Attrs unset ---
    # if attr_unset: _unset_attrs(conn, neuron_id, attr_unset)

    # --- Step 3f: Source update ---
    # if source is not None:
    #     UPDATE neurons SET source = ?, updated_at = ? WHERE id = ?

    # --- Step 4: Update timestamp ---
    # Track whether any mutation was applied via a changed flag
    # If changed: UPDATE neurons SET updated_at = <current UTC ms> WHERE id = ?

    # --- Step 5: Return hydrated record ---
    # from .neuron_get_by_id import neuron_get
    # return neuron_get(conn, neuron_id)

    pass


def _update_content(
    conn: sqlite3.Connection,
    neuron_id: int,
    content: str,
    no_embed: bool,
) -> None:
    """Update neuron content and trigger re-embed if needed.

    Logic flow:
    1. UPDATE neurons SET content = ?, updated_at = ? WHERE id = ?
       - updated_at = current UTC milliseconds
    2. FTS triggers fire automatically on UPDATE
    3. If not no_embed:
       a. Fetch current tags for this neuron (for embedding input)
          - from .neuron_get_by_id import _hydrate_tags
       b. Call _embed_neuron() from neuron_add module (shared embed helper)
       c. On failure: log warning, do NOT re-raise (non-fatal)

    Args:
        conn: SQLite connection.
        neuron_id: ID of the neuron.
        content: New content text (validated non-empty by caller).
        no_embed: Skip re-embedding if True.
    """
    pass


def _add_tags(
    conn: sqlite3.Connection,
    neuron_id: int,
    tag_names: List[str],
) -> None:
    """Add tags to a neuron. Idempotent — already-present tags are no-ops.

    Logic flow:
    1. For each tag_name in tag_names:
       a. Resolve tag_id via tag_autocreate(conn, tag_name) from registries
       b. INSERT OR IGNORE INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)
       c. OR IGNORE handles the idempotent case (already associated)

    Args:
        conn: SQLite connection.
        neuron_id: ID of the neuron.
        tag_names: List of tag names to add.
    """
    pass


def _remove_tags(
    conn: sqlite3.Connection,
    neuron_id: int,
    tag_names: List[str],
) -> None:
    """Remove tags from a neuron, protecting auto-tags.

    Logic flow:
    1. For each tag_name in tag_names:
       a. Normalize tag name (strip, lowercase) for auto-tag check
       b. Check if _is_auto_tag(normalized_name) -> silently skip if True
       c. Look up tag_id by name (normalized) in tags table
          - Not found -> silently skip (tag doesn't exist, so can't be associated)
       d. DELETE FROM neuron_tags WHERE neuron_id = ? AND tag_id = ?
          - No rows affected -> silently skip (tag not associated with this neuron)

    Args:
        conn: SQLite connection.
        neuron_id: ID of the neuron.
        tag_names: List of tag names to remove.
    """
    pass


def _set_attrs(
    conn: sqlite3.Connection,
    neuron_id: int,
    attrs: Dict[str, str],
) -> None:
    """Set (upsert) attributes on a neuron.

    Logic flow:
    1. For each (key, value) in attrs.items():
       a. Resolve attr_key_id via attr_autocreate(conn, key) from registries
       b. INSERT OR REPLACE INTO neuron_attrs (neuron_id, attr_key_id, value) VALUES (?, ?, ?)
       c. OR REPLACE provides upsert: existing value overwritten, new key created

    Args:
        conn: SQLite connection.
        neuron_id: ID of the neuron.
        attrs: Dict mapping attribute key names to values.
    """
    pass


def _unset_attrs(
    conn: sqlite3.Connection,
    neuron_id: int,
    attr_keys: List[str],
) -> None:
    """Remove attributes from a neuron.

    Logic flow:
    1. For each key_name in attr_keys:
       a. Normalize key name (strip, lowercase)
       b. Look up attr_key_id by name in attr_keys table
          - Not found -> silently skip (key doesn't exist)
       c. DELETE FROM neuron_attrs WHERE neuron_id = ? AND attr_key_id = ?
          - No rows affected -> silently skip (attr not set on this neuron)

    Args:
        conn: SQLite connection.
        neuron_id: ID of the neuron.
        attr_keys: List of attribute key names to unset.
    """
    pass


def _is_auto_tag(tag_name: str) -> bool:
    """Check if a tag name matches an auto-tag pattern.

    Auto-tags are generated automatically during neuron creation and cannot
    be removed via --tags-remove. They are silently ignored on removal attempts.

    Auto-tag patterns:
    1. Timestamp tags: match YYYY-MM-DD format (4 digits, dash, 2 digits, dash, 2 digits)
       - regex: ^\\d{4}-\\d{2}-\\d{2}$
    2. Project tags: these match the project detection output pattern
       - For v1, only timestamp tags are protected. Project tag protection
         requires cross-referencing the neuron's project field, which adds
         complexity. This can be added in a later iteration.

    Args:
        tag_name: Normalized tag name to check.

    Returns:
        True if the tag is an auto-tag that should be protected from removal.
    """
    # --- Check timestamp pattern ---
    # return bool(TIMESTAMP_TAG_PATTERN.match(tag_name))

    pass
