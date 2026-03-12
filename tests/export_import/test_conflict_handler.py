# =============================================================================
# Module: test_conflict_handler.py
# Purpose: Test the ConflictHandler class and ConflictAction enum — verifying
#   correct behavior for skip, overwrite, and error modes, including edge
#   handling when neurons are skipped.
# Rationale: Conflict handling is the trickiest part of import — wrong behavior
#   here silently overwrites data (overwrite mode bug), silently drops data
#   (skip mode bug), or blocks valid imports (error mode false positive).
#   Each mode must be tested with: no conflict, single conflict, multiple
#   conflicts. Edge handling with skipped neurons is a subtle cross-cutting
#   concern that needs explicit coverage.
# Responsibility:
#   - Test ConflictAction enum values
#   - Test ConflictHandler initialization and mode validation
#   - Test resolve() for each mode with no conflict
#   - Test resolve() for each mode with conflict
#   - Test skipped_neuron_ids tracking
#   - Test ConflictError is raised in error mode
#   - Test edge filtering based on skipped neuron IDs
# Organization:
#   1. Imports and fixtures
#   2. Fixture: in-memory DB with some existing neurons
#   3. Tests: ConflictAction enum
#   4. Tests: ConflictHandler initialization
#   5. Tests: error mode
#   6. Tests: skip mode
#   7. Tests: overwrite mode
#   8. Tests: skipped ID tracking
#   9. Tests: edge handling with skipped neurons
# =============================================================================

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict

import pytest

from memory_cli.export_import.conflict_handler_skip_overwrite_error import (
    ConflictAction,
    ConflictHandler,
    ConflictError,
)


# --- Helper ---

def _create_neurons_table(conn: sqlite3.Connection) -> None:
    """Create minimal neurons table for conflict testing."""
    conn.execute("""
        CREATE TABLE neurons (
            id      INTEGER PRIMARY KEY,
            content TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            project TEXT NOT NULL DEFAULT 'test',
            status  TEXT NOT NULL DEFAULT 'active'
        )
    """)


# --- Fixtures ---


@pytest.fixture
def empty_db() -> sqlite3.Connection:
    """In-memory DB with neurons table but no data.

    Creates:
    - neurons (id INTEGER PK, content TEXT, created_at INTEGER, updated_at INTEGER,
      project TEXT, status TEXT)

    Yields connection, closes after test.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with conn:
        _create_neurons_table(conn)
    yield conn
    conn.close()


@pytest.fixture
def db_with_existing_neuron() -> sqlite3.Connection:
    """In-memory DB with one existing neuron (ID: 1001).

    Creates neurons table, inserts one neuron:
    - id: 1001
    - content: "I already exist in the DB"
    - project: "test-project"

    Yields connection, closes after test.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    now_ms = int(time.time() * 1000)
    with conn:
        _create_neurons_table(conn)
        conn.execute(
            "INSERT INTO neurons (id, content, created_at, updated_at, project) "
            "VALUES (1001, 'I already exist in the DB', ?, ?, 'test-project')",
            (now_ms, now_ms),
        )
    yield conn
    conn.close()


@pytest.fixture
def new_neuron() -> Dict[str, Any]:
    """A neuron dict that does NOT conflict with existing DB data.

    Returns:
        Dict with id=9999 and valid required fields.
    """
    return {
        "id": 9999,
        "content": "Brand new neuron",
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
        "project": "test-project",
        "source": None,
        "tags": [],
        "attributes": {},
    }


@pytest.fixture
def conflicting_neuron() -> Dict[str, Any]:
    """A neuron dict that DOES conflict — same ID as existing DB neuron (1001).

    Returns:
        Dict with id=1001 (matches db_with_existing_neuron fixture).
        Content and other fields differ from the existing DB neuron.
    """
    return {
        "id": 1001,
        "content": "I am the import version",
        "created_at": "2025-06-01T00:00:00+00:00",
        "updated_at": "2025-06-01T00:00:00+00:00",
        "project": "new-project",
        "source": None,
        "tags": [],
        "attributes": {},
    }


# --- Tests: ConflictAction enum ---


class TestConflictAction:
    """ConflictAction enum has the expected values."""

    def test_write_value(self):
        """ConflictAction.WRITE should have value "write".

        Steps:
        1. Import ConflictAction from conflict_handler module
        2. Assert ConflictAction.WRITE.value == "write"
        """
        assert ConflictAction.WRITE.value == "write"

    def test_skip_value(self):
        """ConflictAction.SKIP should have value "skip"."""
        assert ConflictAction.SKIP.value == "skip"

    def test_overwrite_value(self):
        """ConflictAction.OVERWRITE should have value "overwrite"."""
        assert ConflictAction.OVERWRITE.value == "overwrite"


# --- Tests: ConflictHandler initialization ---


class TestConflictHandlerInit:
    """ConflictHandler initializes correctly and validates mode."""

    def test_valid_modes_accepted(self, empty_db):
        """Modes 'error', 'skip', 'overwrite' should be accepted.

        Steps:
        1. ConflictHandler(empty_db, mode="error") — no exception
        2. ConflictHandler(empty_db, mode="skip") — no exception
        3. ConflictHandler(empty_db, mode="overwrite") — no exception
        """
        ConflictHandler(empty_db, mode="error")
        ConflictHandler(empty_db, mode="skip")
        ConflictHandler(empty_db, mode="overwrite")

    def test_invalid_mode_raises(self, empty_db):
        """Invalid mode string should raise ValueError.

        Steps:
        1. Attempt ConflictHandler(empty_db, mode="invalid")
        2. Assert pytest.raises(ValueError)
        """
        with pytest.raises(ValueError):
            ConflictHandler(empty_db, mode="invalid")

    def test_initial_skipped_ids_empty(self, empty_db):
        """skipped_neuron_ids should be empty on init.

        Steps:
        1. handler = ConflictHandler(empty_db, mode="skip")
        2. Assert handler.get_skipped_ids() == set()
        """
        handler = ConflictHandler(empty_db, mode="skip")
        assert handler.get_skipped_ids() == set()


# --- Tests: Error mode ---


class TestErrorMode:
    """mode='error' aborts on any conflict."""

    def test_no_conflict_returns_write(self, empty_db, new_neuron):
        """Non-conflicting neuron should return WRITE.

        Steps:
        1. handler = ConflictHandler(empty_db, mode="error")
        2. action = handler.resolve(new_neuron)
        3. Assert action == ConflictAction.WRITE
        """
        handler = ConflictHandler(empty_db, mode="error")
        action = handler.resolve(new_neuron)
        assert action == ConflictAction.WRITE

    def test_conflict_raises_error(self, db_with_existing_neuron, conflicting_neuron):
        """Conflicting neuron should raise ConflictError.

        Steps:
        1. handler = ConflictHandler(db_with_existing_neuron, mode="error")
        2. with pytest.raises(ConflictError):
               handler.resolve(conflicting_neuron)
        """
        handler = ConflictHandler(db_with_existing_neuron, mode="error")
        with pytest.raises(ConflictError):
            handler.resolve(conflicting_neuron)

    def test_conflict_error_contains_neuron_id(self, db_with_existing_neuron, conflicting_neuron):
        """ConflictError should contain the conflicting neuron ID.

        Steps:
        1. handler = ConflictHandler(db_with_existing_neuron, mode="error")
        2. Try handler.resolve(conflicting_neuron), catch ConflictError
        3. Assert exc.neuron_id == 1001
        """
        handler = ConflictHandler(db_with_existing_neuron, mode="error")
        try:
            handler.resolve(conflicting_neuron)
            assert False, "Should have raised ConflictError"
        except ConflictError as exc:
            assert exc.neuron_id == 1001


# --- Tests: Skip mode ---


class TestSkipMode:
    """mode='skip' skips conflicting neurons without error."""

    def test_no_conflict_returns_write(self, empty_db, new_neuron):
        """Non-conflicting neuron should return WRITE.

        Steps:
        1. handler = ConflictHandler(empty_db, mode="skip")
        2. Assert handler.resolve(new_neuron) == ConflictAction.WRITE
        """
        handler = ConflictHandler(empty_db, mode="skip")
        assert handler.resolve(new_neuron) == ConflictAction.WRITE

    def test_conflict_returns_skip(self, db_with_existing_neuron, conflicting_neuron):
        """Conflicting neuron should return SKIP (no error raised).

        Steps:
        1. handler = ConflictHandler(db_with_existing_neuron, mode="skip")
        2. action = handler.resolve(conflicting_neuron)
        3. Assert action == ConflictAction.SKIP
        """
        handler = ConflictHandler(db_with_existing_neuron, mode="skip")
        action = handler.resolve(conflicting_neuron)
        assert action == ConflictAction.SKIP

    def test_skipped_id_tracked(self, db_with_existing_neuron, conflicting_neuron):
        """Skipped neuron ID should be in get_skipped_ids().

        Steps:
        1. handler = ConflictHandler(db_with_existing_neuron, mode="skip")
        2. handler.resolve(conflicting_neuron)
        3. Assert 1001 in handler.get_skipped_ids()
        """
        handler = ConflictHandler(db_with_existing_neuron, mode="skip")
        handler.resolve(conflicting_neuron)
        assert 1001 in handler.get_skipped_ids()

    def test_multiple_skips_accumulated(self, db_with_existing_neuron):
        """Multiple skipped neurons should all be tracked.

        Steps:
        1. Insert another neuron 1002 into DB
        2. handler = ConflictHandler(db_with_existing_neuron, mode="skip")
        3. Resolve neuron with id=1001 -> SKIP
        4. Resolve neuron with id=1002 -> SKIP
        5. Assert both IDs in handler.get_skipped_ids()
        6. Assert len(handler.get_skipped_ids()) == 2
        """
        now_ms = int(time.time() * 1000)
        with db_with_existing_neuron:
            db_with_existing_neuron.execute(
                "INSERT INTO neurons (id, content, created_at, updated_at) "
                "VALUES (1002, 'Second existing', ?, ?)",
                (now_ms, now_ms),
            )
        handler = ConflictHandler(db_with_existing_neuron, mode="skip")
        handler.resolve({"id": 1001, "content": "conflict 1"})
        handler.resolve({"id": 1002, "content": "conflict 2"})
        skipped = handler.get_skipped_ids()
        assert 1001 in skipped
        assert 1002 in skipped
        assert len(skipped) == 2


# --- Tests: Overwrite mode ---


class TestOverwriteMode:
    """mode='overwrite' replaces existing neurons."""

    def test_no_conflict_returns_write(self, empty_db, new_neuron):
        """Non-conflicting neuron should return WRITE.

        Steps:
        1. handler = ConflictHandler(empty_db, mode="overwrite")
        2. Assert handler.resolve(new_neuron) == ConflictAction.WRITE
        """
        handler = ConflictHandler(empty_db, mode="overwrite")
        assert handler.resolve(new_neuron) == ConflictAction.WRITE

    def test_conflict_returns_overwrite(self, db_with_existing_neuron, conflicting_neuron):
        """Conflicting neuron should return OVERWRITE (no error raised).

        Steps:
        1. handler = ConflictHandler(db_with_existing_neuron, mode="overwrite")
        2. action = handler.resolve(conflicting_neuron)
        3. Assert action == ConflictAction.OVERWRITE
        """
        handler = ConflictHandler(db_with_existing_neuron, mode="overwrite")
        action = handler.resolve(conflicting_neuron)
        assert action == ConflictAction.OVERWRITE

    def test_overwrite_does_not_track_skipped(self, db_with_existing_neuron, conflicting_neuron):
        """Overwritten neurons should NOT be in skipped_neuron_ids.

        Steps:
        1. handler = ConflictHandler(db_with_existing_neuron, mode="overwrite")
        2. handler.resolve(conflicting_neuron)
        3. Assert handler.get_skipped_ids() == set() (empty)
        """
        handler = ConflictHandler(db_with_existing_neuron, mode="overwrite")
        handler.resolve(conflicting_neuron)
        assert handler.get_skipped_ids() == set()


# --- Tests: Skipped ID tracking ---


class TestSkippedIdTracking:
    """get_skipped_ids() returns correct set of skipped neuron IDs."""

    def test_empty_after_no_resolves(self, empty_db):
        """No resolves -> empty skipped set.

        Steps:
        1. handler = ConflictHandler(empty_db, mode="skip")
        2. Assert handler.get_skipped_ids() == set()
        """
        handler = ConflictHandler(empty_db, mode="skip")
        assert handler.get_skipped_ids() == set()

    def test_empty_after_write_resolves(self, empty_db, new_neuron):
        """Only WRITE resolves -> empty skipped set.

        Steps:
        1. handler = ConflictHandler(empty_db, mode="skip")
        2. handler.resolve(new_neuron) -> WRITE
        3. Assert handler.get_skipped_ids() == set()
        """
        handler = ConflictHandler(empty_db, mode="skip")
        handler.resolve(new_neuron)
        assert handler.get_skipped_ids() == set()

    def test_populated_after_skip_resolves(self, db_with_existing_neuron, conflicting_neuron):
        """SKIP resolves -> skipped set contains those IDs.

        Steps:
        1. handler = ConflictHandler(db_with_existing_neuron, mode="skip")
        2. handler.resolve(conflicting_neuron)
        3. Assert len(handler.get_skipped_ids()) == 1
        4. Assert 1001 in handler.get_skipped_ids()
        """
        handler = ConflictHandler(db_with_existing_neuron, mode="skip")
        handler.resolve(conflicting_neuron)
        skipped = handler.get_skipped_ids()
        assert len(skipped) == 1
        assert 1001 in skipped

    def test_returns_copy_not_reference(self, db_with_existing_neuron, conflicting_neuron):
        """get_skipped_ids() should return a copy, not a mutable reference.

        Steps:
        1. handler = ConflictHandler(db_with_existing_neuron, mode="skip")
        2. handler.resolve(conflicting_neuron)
        3. ids1 = handler.get_skipped_ids()
        4. ids1.add("tampered-id")
        5. ids2 = handler.get_skipped_ids()
        6. Assert "tampered-id" NOT in ids2
        7. Assert len(ids2) == 1 (original size, unmodified)
        """
        handler = ConflictHandler(db_with_existing_neuron, mode="skip")
        handler.resolve(conflicting_neuron)
        ids1 = handler.get_skipped_ids()
        ids1.add("tampered-id")
        ids2 = handler.get_skipped_ids()
        assert "tampered-id" not in ids2
        assert len(ids2) == 1


# --- Tests: Edge handling with skipped neurons ---


class TestEdgeHandlingWithSkippedNeurons:
    """Edges referencing skipped neurons should be identified for exclusion.

    Note: The ConflictHandler doesn't filter edges directly — it provides
    get_skipped_ids() which the write pipeline uses to skip edges. These
    tests verify the data flow is correct for edge filtering decisions.
    """

    def test_edge_both_endpoints_written_is_kept(self, empty_db):
        """Edge where both neurons are written should be importable.

        Steps:
        1. handler = ConflictHandler(empty_db, mode="skip")
        2. Resolve neuron_a (new, WRITE) and neuron_b (new, WRITE)
        3. skipped = handler.get_skipped_ids()
        4. Assert neuron_a["id"] not in skipped
        5. Assert neuron_b["id"] not in skipped
        6. Therefore edge a->b should NOT be skipped by write pipeline
        """
        handler = ConflictHandler(empty_db, mode="skip")
        neuron_a = {"id": 101, "content": "a"}
        neuron_b = {"id": 102, "content": "b"}
        handler.resolve(neuron_a)
        handler.resolve(neuron_b)
        skipped = handler.get_skipped_ids()
        assert neuron_a["id"] not in skipped
        assert neuron_b["id"] not in skipped

    def test_edge_source_skipped_should_be_dropped(self, db_with_existing_neuron):
        """Edge where source is skipped should be dropped.

        Steps:
        1. handler = ConflictHandler(db_with_existing_neuron, mode="skip")
        2. Resolve conflicting neuron (source, SKIP)
        3. Resolve new neuron (target, WRITE)
        4. skipped = handler.get_skipped_ids()
        5. Assert source_id in skipped -> edge should be dropped
        """
        handler = ConflictHandler(db_with_existing_neuron, mode="skip")
        conflicting = {"id": 1001, "content": "conflict"}
        new = {"id": 9999, "content": "new"}
        handler.resolve(conflicting)
        handler.resolve(new)
        skipped = handler.get_skipped_ids()
        assert 1001 in skipped  # source should be skipped

    def test_edge_target_skipped_should_be_dropped(self, db_with_existing_neuron):
        """Edge where target is skipped should be dropped.

        Steps:
        1. handler = ConflictHandler(db_with_existing_neuron, mode="skip")
        2. Resolve new neuron (source, WRITE)
        3. Resolve conflicting neuron (target, SKIP)
        4. skipped = handler.get_skipped_ids()
        5. Assert target_id in skipped -> edge should be dropped
        """
        handler = ConflictHandler(db_with_existing_neuron, mode="skip")
        new = {"id": 9999, "content": "new"}
        conflicting = {"id": 1001, "content": "conflict"}
        handler.resolve(new)
        handler.resolve(conflicting)
        skipped = handler.get_skipped_ids()
        assert 1001 in skipped  # target should be skipped

    def test_edge_both_skipped_should_be_dropped(self, db_with_existing_neuron):
        """Edge where both endpoints are skipped should be dropped.

        Steps:
        1. Insert second existing neuron into DB
        2. handler = ConflictHandler(db_with_existing_neuron, mode="skip")
        3. Resolve both conflicting neurons (both SKIP)
        4. skipped = handler.get_skipped_ids()
        5. Assert both source and target in skipped -> edge dropped
        """
        now_ms = int(time.time() * 1000)
        with db_with_existing_neuron:
            db_with_existing_neuron.execute(
                "INSERT INTO neurons (id, content, created_at, updated_at) "
                "VALUES (1002, 'Second existing', ?, ?)",
                (now_ms, now_ms),
            )
        handler = ConflictHandler(db_with_existing_neuron, mode="skip")
        handler.resolve({"id": 1001, "content": "conflict 1"})
        handler.resolve({"id": 1002, "content": "conflict 2"})
        skipped = handler.get_skipped_ids()
        assert 1001 in skipped
        assert 1002 in skipped
