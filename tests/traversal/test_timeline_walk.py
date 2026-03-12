# =============================================================================
# Module: test_timeline_walk.py
# Purpose: Test chronological timeline navigation — forward, backward, empty
#   results, tie-breaking, pagination, and reference-not-found error handling.
# Rationale: Timeline is a deterministic navigation command — ordering and
#   pagination must be exact. Tie-breaking by neuron ID is a subtle correctness
#   requirement that needs explicit test coverage. The reference-not-found case
#   must map to exit 1 (LookupError), not a silent empty result.
# Responsibility:
#   - Test forward direction returns neurons created after reference, ascending
#   - Test backward direction returns neurons created before reference, descending
#   - Test tie-breaking: same created_at, different IDs, correct order
#   - Test reference neuron excluded from results
#   - Test empty result set returns exit 0 (no error, just empty results list)
#   - Test reference not found raises LookupError (caller maps to exit 1)
#   - Test pagination: limit, offset, total count is pre-pagination
#   - Test JSON envelope structure: command, reference_id, direction, results, total, limit, offset
#   - Test result object structure: id, content, created_at, project, tags, source
# Organization:
#   1. Imports and fixtures
#   2. Forward direction tests
#   3. Backward direction tests
#   4. Tie-breaking tests
#   5. Pagination tests
#   6. Empty results and error tests
#   7. Envelope structure tests
# =============================================================================

from __future__ import annotations

import sqlite3
import time
import pytest
from typing import Any, Dict, List

from memory_cli.db.connection_setup_wal_fk_busy import open_connection
from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as apply_v001
from memory_cli.traversal.timeline_walk_forward_backward import timeline_walk

# --- Module-level guard: all tests require sqlite_vec for the full migration ---
sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec package required for migration (vec0 virtual table)",
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """Create an in-memory SQLite database with full schema applied.

    Loads sqlite_vec extension, runs v001 migration, yields connection.
    row_factory = sqlite3.Row is set by open_connection.
    """
    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply_v001(conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


def _create_neuron(conn, content, created_at_ms, project="test-project"):
    """Insert a neuron with controlled timestamps and return its ID."""
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) "
        "VALUES (?, ?, ?, ?, 'active')",
        (content, created_at_ms, created_at_ms, project),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _create_tag(conn, name):
    """Insert a tag by name and return its ID."""
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO tags (name, created_at) VALUES (?, ?)",
        (name, now_ms),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _attach_tag(conn, neuron_id, tag_id):
    """Link a tag to a neuron via neuron_tags junction."""
    conn.execute(
        "INSERT INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)",
        (neuron_id, tag_id),
    )


@pytest.fixture
def timeline_neurons(migrated_conn):
    """Insert neurons with known timestamps for timeline testing.

    Creates 7 neurons:
      id-assigned, created_at=1000 (reference neuron)
      id-assigned, created_at=900  (before reference)
      id-assigned, created_at=800  (before reference)
      id-assigned, created_at=1100 (after reference)
      id-assigned, created_at=1200 (after reference)
      id-assigned, created_at=1000 (same ts as reference, higher ID — forward tie-break)
      id-assigned, created_at=1000 (same ts as reference, highest ID — tie-break)

    Also creates tags "alpha" and "beta", attaches both to the first
    "after" neuron (created_at=1100) for hydration testing.

    Returns (conn, ref_id) tuple.
    """
    conn = migrated_conn
    ref_id = _create_neuron(conn, "reference neuron", 1000)
    _create_neuron(conn, "before reference 900", 900)
    _create_neuron(conn, "before reference 800", 800)
    after_id = _create_neuron(conn, "after reference 1100", 1100)
    _create_neuron(conn, "after reference 1200", 1200)
    _create_neuron(conn, "same ts higher id A", 1000)
    _create_neuron(conn, "same ts higher id B", 1000)

    # Attach tags to the 1100 neuron for hydration test
    tag_alpha_id = _create_tag(conn, "alpha")
    tag_beta_id = _create_tag(conn, "beta")
    _attach_tag(conn, after_id, tag_alpha_id)
    _attach_tag(conn, after_id, tag_beta_id)

    return conn, ref_id


# -----------------------------------------------------------------------------
# Forward direction tests
# -----------------------------------------------------------------------------

class TestTimelineForward:
    """Test forward timeline walk — neurons created AFTER reference."""

    def test_forward_returns_neurons_after_reference(self, timeline_neurons):
        """Verify forward walk returns only neurons with created_at > reference.

        Setup: reference at created_at=1000, neurons at 1100 and 1200 exist.
        Expected: results contain neurons at 1100 and 1200.
        """
        conn, ref_id = timeline_neurons
        result = timeline_walk(conn, ref_id, direction="forward")
        created_ats = [r["created_at"] for r in result["results"]]
        # Neurons with created_at > 1000 should be present
        assert 1100 in created_ats
        assert 1200 in created_ats
        # No neurons with created_at < 1000 should appear
        assert all(ts >= 1000 for ts in created_ats)

    def test_forward_ascending_order(self, timeline_neurons):
        """Verify forward results are ordered by created_at ASC.

        Expected: earliest-after-reference neuron appears first.
        """
        conn, ref_id = timeline_neurons
        result = timeline_walk(conn, ref_id, direction="forward")
        results = [r for r in result["results"] if r["created_at"] in (1100, 1200)]
        # Find 1100 and 1200 in full results
        all_ts = [r["created_at"] for r in result["results"]]
        # 1100 should appear before 1200
        idx_1100 = next(i for i, ts in enumerate(all_ts) if ts == 1100)
        idx_1200 = next(i for i, ts in enumerate(all_ts) if ts == 1200)
        assert idx_1100 < idx_1200

    def test_forward_excludes_reference_neuron(self, timeline_neurons):
        """Verify reference neuron itself is not in forward results.

        The reference anchors the walk but is not part of the output.
        """
        conn, ref_id = timeline_neurons
        result = timeline_walk(conn, ref_id, direction="forward")
        ids = [r["id"] for r in result["results"]]
        assert ref_id not in ids

    def test_forward_default_direction(self, timeline_neurons):
        """Verify forward is the default when no direction specified.

        Call timeline_walk without direction kwarg, confirm forward behavior.
        """
        conn, ref_id = timeline_neurons
        result = timeline_walk(conn, ref_id)
        # Default should behave same as forward
        assert result["direction"] == "forward"
        created_ats = [r["created_at"] for r in result["results"]]
        assert 1100 in created_ats
        assert 1200 in created_ats

    def test_forward_includes_tie_break_neurons(self, timeline_neurons):
        """Verify neurons with same created_at but higher ID appear in forward results.

        Setup: reference id=ref_id at created_at=1000, neurons with same ts and higher IDs.
        Expected: those neurons appear in forward results.
        """
        conn, ref_id = timeline_neurons
        result = timeline_walk(conn, ref_id, direction="forward")
        # Neurons at created_at=1000 with id > ref_id should be in results
        same_ts_results = [r for r in result["results"] if r["created_at"] == 1000]
        assert len(same_ts_results) == 2  # two neurons at ts=1000 with higher IDs
        for r in same_ts_results:
            assert r["id"] > ref_id


# -----------------------------------------------------------------------------
# Backward direction tests
# -----------------------------------------------------------------------------

class TestTimelineBackward:
    """Test backward timeline walk — neurons created BEFORE reference."""

    def test_backward_returns_neurons_before_reference(self, timeline_neurons):
        """Verify backward walk returns only neurons with created_at < reference.

        Setup: reference at created_at=1000, neurons at 800 and 900 exist.
        Expected: results contain neurons at 800 and 900.
        """
        conn, ref_id = timeline_neurons
        result = timeline_walk(conn, ref_id, direction="backward")
        created_ats = [r["created_at"] for r in result["results"]]
        assert 900 in created_ats
        assert 800 in created_ats
        # No neurons with created_at > 1000 should appear
        assert all(ts <= 1000 for ts in created_ats)

    def test_backward_descending_order(self, timeline_neurons):
        """Verify backward results are ordered by created_at DESC.

        Expected: most-recent-before-reference neuron appears first.
        """
        conn, ref_id = timeline_neurons
        result = timeline_walk(conn, ref_id, direction="backward")
        # Filter to strict before-reference neurons
        before_ts = [r["created_at"] for r in result["results"] if r["created_at"] < 1000]
        # Should be descending: 900 before 800
        assert before_ts == sorted(before_ts, reverse=True)

    def test_backward_excludes_reference_neuron(self, timeline_neurons):
        """Verify reference neuron itself is not in backward results."""
        conn, ref_id = timeline_neurons
        result = timeline_walk(conn, ref_id, direction="backward")
        ids = [r["id"] for r in result["results"]]
        assert ref_id not in ids


# -----------------------------------------------------------------------------
# Tie-breaking tests
# -----------------------------------------------------------------------------

class TestTimelineTieBreaking:
    """Test tie-breaking behavior when neurons share the same created_at."""

    def test_same_timestamp_forward_ordered_by_id_asc(self, migrated_conn):
        """Verify neurons with identical created_at are ordered by ID ascending.

        Setup: multiple neurons at created_at=1000 with IDs > reference ID.
        Expected: lower ID appears before higher ID in forward results.
        """
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 1000)
        id_a = _create_neuron(conn, "tie A", 1000)
        id_b = _create_neuron(conn, "tie B", 1000)
        # Both id_a and id_b > ref_id (AUTOINCREMENT), id_a < id_b
        assert id_a < id_b
        result = timeline_walk(conn, ref_id, direction="forward")
        same_ts = [r for r in result["results"] if r["created_at"] == 1000]
        same_ts_ids = [r["id"] for r in same_ts]
        assert same_ts_ids == sorted(same_ts_ids)  # ascending

    def test_same_timestamp_backward_ordered_by_id_asc(self, migrated_conn):
        """Verify backward tie-breaking also uses ID ascending.

        Setup: multiple neurons at same timestamp before reference.
        Expected: within same timestamp group, lower ID appears first.
        Note: backward reverses timestamp order but ID sort remains ASC.
        """
        conn = migrated_conn
        id_a = _create_neuron(conn, "early A", 500)
        id_b = _create_neuron(conn, "early B", 500)
        ref_id = _create_neuron(conn, "reference", 1000)
        assert id_a < id_b
        result = timeline_walk(conn, ref_id, direction="backward")
        same_ts = [r for r in result["results"] if r["created_at"] == 500]
        same_ts_ids = [r["id"] for r in same_ts]
        # Within the same timestamp group, order is ID ASC
        assert same_ts_ids == sorted(same_ts_ids)

    def test_tie_break_does_not_include_reference(self, migrated_conn):
        """Verify reference neuron excluded even when other neurons share its timestamp.

        Setup: reference id=ref_id at ts=1000, neuron with same ts but higher id.
        Forward results should contain higher-id neuron but NOT ref_id.
        """
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 1000)
        other_id = _create_neuron(conn, "same ts higher id", 1000)
        result = timeline_walk(conn, ref_id, direction="forward")
        ids = [r["id"] for r in result["results"]]
        assert ref_id not in ids
        assert other_id in ids


# -----------------------------------------------------------------------------
# Pagination tests
# -----------------------------------------------------------------------------

class TestTimelinePagination:
    """Test limit, offset, and total count behavior."""

    def test_default_limit_is_20(self, migrated_conn):
        """Verify default limit is 20 when not specified."""
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 1000)
        result = timeline_walk(conn, ref_id)
        assert result["limit"] == 20

    def test_default_offset_is_0(self, migrated_conn):
        """Verify default offset is 0 when not specified."""
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 1000)
        result = timeline_walk(conn, ref_id)
        assert result["offset"] == 0

    def test_limit_restricts_results(self, migrated_conn):
        """Verify limit=1 returns only one result even when more match.

        Setup: 3 neurons after reference.
        Expected: results list has 1 item, total shows 3.
        """
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 1000)
        _create_neuron(conn, "after 1", 1100)
        _create_neuron(conn, "after 2", 1200)
        _create_neuron(conn, "after 3", 1300)
        result = timeline_walk(conn, ref_id, direction="forward", limit=1)
        assert len(result["results"]) == 1
        assert result["total"] == 3

    def test_offset_skips_results(self, migrated_conn):
        """Verify offset=1 skips the first matching result.

        Setup: 3 neurons after reference at ts 1100, 1200, 1300.
        Expected with offset=1: first result is ts=1200, not ts=1100.
        """
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 1000)
        _create_neuron(conn, "after 1100", 1100)
        _create_neuron(conn, "after 1200", 1200)
        _create_neuron(conn, "after 1300", 1300)
        result = timeline_walk(conn, ref_id, direction="forward", offset=1)
        assert result["results"][0]["created_at"] == 1200

    def test_total_is_pre_pagination_count(self, migrated_conn):
        """Verify total reflects full count before limit/offset applied.

        Setup: 4 neurons match, limit=2, offset=0.
        Expected: total=4, len(results)=2.
        """
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 1000)
        for ts in [1100, 1200, 1300, 1400]:
            _create_neuron(conn, f"after {ts}", ts)
        result = timeline_walk(conn, ref_id, direction="forward", limit=2, offset=0)
        assert result["total"] == 4
        assert len(result["results"]) == 2

    def test_offset_beyond_total_returns_empty(self, migrated_conn):
        """Verify offset beyond total returns empty results, total still correct.

        Setup: 2 neurons match, offset=10.
        Expected: results=[], total=2.
        """
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 1000)
        _create_neuron(conn, "after 1", 1100)
        _create_neuron(conn, "after 2", 1200)
        result = timeline_walk(conn, ref_id, direction="forward", offset=10)
        assert result["results"] == []
        assert result["total"] == 2

    def test_envelope_contains_applied_limit_and_offset(self, migrated_conn):
        """Verify envelope reflects the limit and offset that were actually applied.

        Even when results are empty due to high offset, envelope shows
        the requested limit and offset values.
        """
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 1000)
        result = timeline_walk(conn, ref_id, direction="forward", limit=5, offset=100)
        assert result["limit"] == 5
        assert result["offset"] == 100


# -----------------------------------------------------------------------------
# Empty results and error tests
# -----------------------------------------------------------------------------

class TestTimelineEmptyAndErrors:
    """Test empty result sets and reference-not-found error."""

    def test_no_neurons_after_reference_returns_empty(self, migrated_conn):
        """Verify forward walk with no later neurons returns empty results, exit 0.

        Setup: reference is the latest neuron.
        Expected: results=[], total=0.
        """
        conn = migrated_conn
        _create_neuron(conn, "earlier neuron", 500)
        ref_id = _create_neuron(conn, "latest neuron", 1000)
        result = timeline_walk(conn, ref_id, direction="forward")
        assert result["results"] == []
        assert result["total"] == 0

    def test_no_neurons_before_reference_returns_empty(self, migrated_conn):
        """Verify backward walk with no earlier neurons returns empty results, exit 0.

        Setup: reference is the earliest neuron.
        Expected: results=[], total=0.
        """
        conn = migrated_conn
        ref_id = _create_neuron(conn, "earliest neuron", 500)
        _create_neuron(conn, "later neuron", 1000)
        result = timeline_walk(conn, ref_id, direction="backward")
        assert result["results"] == []
        assert result["total"] == 0

    def test_reference_not_found_raises_lookup_error(self, migrated_conn):
        """Verify non-existent reference ID raises LookupError.

        Setup: no neuron with id=9999 exists.
        Expected: LookupError raised (caller maps to exit 1).
        """
        conn = migrated_conn
        with pytest.raises(LookupError):
            timeline_walk(conn, 9999, direction="forward")

    def test_empty_result_envelope_structure(self, migrated_conn):
        """Verify empty result envelope still has all required keys.

        Expected keys: command, reference_id, direction, results, total, limit, offset.
        results should be [], total should be 0.
        """
        conn = migrated_conn
        ref_id = _create_neuron(conn, "only neuron", 1000)
        result = timeline_walk(conn, ref_id, direction="forward")
        assert "command" in result
        assert "reference_id" in result
        assert "direction" in result
        assert "results" in result
        assert "total" in result
        assert "limit" in result
        assert "offset" in result
        assert result["results"] == []
        assert result["total"] == 0


# -----------------------------------------------------------------------------
# Envelope structure tests
# -----------------------------------------------------------------------------

class TestTimelineEnvelope:
    """Test the JSON envelope structure and result object shape."""

    def test_envelope_has_command_field(self, migrated_conn):
        """Verify envelope contains command='timeline'."""
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 1000)
        result = timeline_walk(conn, ref_id)
        assert result["command"] == "timeline"

    def test_envelope_has_reference_id(self, migrated_conn):
        """Verify envelope contains reference_id matching the input."""
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 1000)
        result = timeline_walk(conn, ref_id)
        assert result["reference_id"] == ref_id

    def test_envelope_has_direction(self, migrated_conn):
        """Verify envelope contains the direction that was requested."""
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 1000)
        result = timeline_walk(conn, ref_id, direction="backward")
        assert result["direction"] == "backward"

    def test_result_object_has_required_fields(self, migrated_conn):
        """Verify each result dict contains: id, content, created_at, project, tags, source.

        Tags should be a list of strings (possibly empty).
        """
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 1000)
        _create_neuron(conn, "after neuron", 1100)
        result = timeline_walk(conn, ref_id, direction="forward")
        assert len(result["results"]) >= 1
        r = result["results"][0]
        assert "id" in r
        assert "content" in r
        assert "created_at" in r
        assert "project" in r
        assert "tags" in r
        assert "source" in r
        assert isinstance(r["tags"], list)

    def test_result_tags_are_hydrated(self, timeline_neurons):
        """Verify result tags are hydrated from junction table, not raw IDs.

        Setup: neuron at 1100 with tags ["alpha", "beta"].
        Expected: result["tags"] == ["alpha", "beta"] (sorted).
        """
        conn, ref_id = timeline_neurons
        result = timeline_walk(conn, ref_id, direction="forward")
        # Find the neuron at 1100 which has tags
        neuron_1100 = next(
            (r for r in result["results"] if r["created_at"] == 1100), None
        )
        assert neuron_1100 is not None
        assert neuron_1100["tags"] == ["alpha", "beta"]
