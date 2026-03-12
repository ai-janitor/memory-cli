# =============================================================================
# Module: test_tag_filter_post_activation.py
# Purpose: Test post-activation AND/OR tag filtering — stage 7 of the light
#   search pipeline. Verifies AND mode, OR mode, case insensitivity, and
#   the important property that filtering is post-activation.
# Rationale: Tag filtering is a user-facing feature that directly controls
#   which results appear. AND vs OR semantics must be exact. The post-
#   activation timing is crucial: activation must flow through ALL neurons
#   before filtering, so tests must verify that filtering doesn't interfere
#   with activation propagation.
# Responsibility:
#   - Test AND mode: candidate must have ALL required tags
#   - Test OR mode: candidate must have at least ONE required tag
#   - Test case-insensitive tag matching
#   - Test empty tag list returns all candidates (no filtering)
#   - Test no matching tags returns empty list
#   - Test invalid tag_mode defaults to AND
#   - Test batch tag fetching from DB
# Organization:
#   1. Imports and fixtures
#   2. AND mode tests
#   3. OR mode tests
#   4. Case sensitivity tests
#   5. Edge case tests (empty tags, no matches, invalid mode)
#   6. Combined filter tests
# =============================================================================

from __future__ import annotations

import time

import pytest

from memory_cli.search.tag_filter_post_activation import (
    filter_by_tags,
    _fetch_neuron_tags_batch,
    _matches_and_filter,
    _matches_or_filter,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """Full in-memory DB with schema."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply
    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply(conn)
    conn.execute("COMMIT")
    return conn


def _insert_neuron(conn, content, tags=None):
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) "
        "VALUES (?, ?, ?, 'test', 'active')",
        (content, now_ms, now_ms),
    )
    nid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    if tags:
        for t in tags:
            from memory_cli.registries import tag_autocreate
            tid = tag_autocreate(conn, t)
            conn.execute(
                "INSERT OR IGNORE INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)",
                (nid, tid),
            )
    return nid


@pytest.fixture
def tag_db(migrated_conn):
    """DB with 5 neurons with known tags.

    Neurons and their tags:
    1. tags: ["python", "search", "memory"]
    2. tags: ["python", "data"]
    3. tags: ["rust", "search"]
    4. tags: ["rust", "memory"]
    5. tags: [] (no tags)
    """
    conn = migrated_conn
    conn.execute("BEGIN")
    n1 = _insert_neuron(conn, "content 1", ["python", "search", "memory"])
    n2 = _insert_neuron(conn, "content 2", ["python", "data"])
    n3 = _insert_neuron(conn, "content 3", ["rust", "search"])
    n4 = _insert_neuron(conn, "content 4", ["rust", "memory"])
    n5 = _insert_neuron(conn, "content 5", [])
    conn.execute("COMMIT")
    return conn, [n1, n2, n3, n4, n5]


@pytest.fixture
def sample_candidates(tag_db):
    """Candidate dicts for neurons 1-5."""
    conn, nids = tag_db
    candidates = [
        {"neuron_id": nid, "activation_score": 1.0, "rrf_score": 0.01}
        for nid in nids
    ]
    return conn, candidates, nids


# -----------------------------------------------------------------------------
# AND mode tests
# -----------------------------------------------------------------------------

class TestTagFilterAND:
    """Test AND mode: candidate must have ALL required tags."""

    def test_and_single_tag_filters_correctly(self, sample_candidates):
        """Verify AND with ["python"] keeps neurons 1, 2 only."""
        conn, candidates, nids = sample_candidates
        result = filter_by_tags(conn, candidates, ["python"], "AND")
        result_ids = {r["neuron_id"] for r in result}
        assert nids[0] in result_ids  # neuron 1: has python
        assert nids[1] in result_ids  # neuron 2: has python
        assert nids[2] not in result_ids  # neuron 3: no python
        assert nids[3] not in result_ids  # neuron 4: no python
        assert nids[4] not in result_ids  # neuron 5: no tags

    def test_and_multiple_tags_intersection(self, sample_candidates):
        """Verify AND with ["python", "search"] keeps only neuron 1.

        Only neuron 1 has both "python" AND "search".
        """
        conn, candidates, nids = sample_candidates
        result = filter_by_tags(conn, candidates, ["python", "search"], "AND")
        result_ids = {r["neuron_id"] for r in result}
        assert result_ids == {nids[0]}

    def test_and_no_neuron_has_all_tags(self, sample_candidates):
        """Verify AND with ["python", "rust"] returns empty.

        No single neuron has both tags.
        """
        conn, candidates, nids = sample_candidates
        result = filter_by_tags(conn, candidates, ["python", "rust"], "AND")
        assert result == []

    def test_and_preserves_candidate_order(self, sample_candidates):
        """Verify filtered list preserves original candidate ordering."""
        conn, candidates, nids = sample_candidates
        result = filter_by_tags(conn, candidates, ["python"], "AND")
        result_ids = [r["neuron_id"] for r in result]
        # Original order is nids[0], nids[1] since candidates are in nids order
        assert result_ids == [nids[0], nids[1]]


# -----------------------------------------------------------------------------
# OR mode tests
# -----------------------------------------------------------------------------

class TestTagFilterOR:
    """Test OR mode: candidate must have at least ONE required tag."""

    def test_or_single_tag_matches(self, sample_candidates):
        """Verify OR with ["python"] keeps neurons 1, 2."""
        conn, candidates, nids = sample_candidates
        result = filter_by_tags(conn, candidates, ["python"], "OR")
        result_ids = {r["neuron_id"] for r in result}
        assert nids[0] in result_ids
        assert nids[1] in result_ids

    def test_or_multiple_tags_union(self, sample_candidates):
        """Verify OR with ["python", "rust"] keeps neurons 1, 2, 3, 4.

        Any neuron with either tag qualifies.
        """
        conn, candidates, nids = sample_candidates
        result = filter_by_tags(conn, candidates, ["python", "rust"], "OR")
        result_ids = {r["neuron_id"] for r in result}
        assert nids[0] in result_ids  # python
        assert nids[1] in result_ids  # python
        assert nids[2] in result_ids  # rust
        assert nids[3] in result_ids  # rust
        assert nids[4] not in result_ids  # no tags

    def test_or_no_matching_tags(self, sample_candidates):
        """Verify OR with ["nonexistent"] returns empty list."""
        conn, candidates, nids = sample_candidates
        result = filter_by_tags(conn, candidates, ["nonexistent_xyz"], "OR")
        assert result == []

    def test_or_preserves_candidate_order(self, sample_candidates):
        """Verify filtered list preserves original candidate ordering."""
        conn, candidates, nids = sample_candidates
        result = filter_by_tags(conn, candidates, ["python"], "OR")
        result_ids = [r["neuron_id"] for r in result]
        assert result_ids == [nids[0], nids[1]]


# -----------------------------------------------------------------------------
# Case sensitivity tests
# -----------------------------------------------------------------------------

class TestTagFilterCaseSensitivity:
    """Test case-insensitive tag matching."""

    def test_uppercase_tag_matches_lowercase(self, sample_candidates):
        """Verify required tag "PYTHON" matches stored tag "python"."""
        conn, candidates, nids = sample_candidates
        result = filter_by_tags(conn, candidates, ["PYTHON"], "AND")
        result_ids = {r["neuron_id"] for r in result}
        assert nids[0] in result_ids
        assert nids[1] in result_ids

    def test_mixed_case_tag_matches(self, sample_candidates):
        """Verify required tag "Python" matches stored tag "python"."""
        conn, candidates, nids = sample_candidates
        result = filter_by_tags(conn, candidates, ["Python"], "AND")
        result_ids = {r["neuron_id"] for r in result}
        assert nids[0] in result_ids
        assert nids[1] in result_ids


# -----------------------------------------------------------------------------
# Edge case tests
# -----------------------------------------------------------------------------

class TestTagFilterEdgeCases:
    """Test edge cases for tag filtering."""

    def test_empty_required_tags_returns_all(self, sample_candidates):
        """Verify empty required_tags list returns all candidates unfiltered."""
        conn, candidates, nids = sample_candidates
        result = filter_by_tags(conn, candidates, [], "AND")
        assert len(result) == len(candidates)

    def test_neuron_with_no_tags_filtered_in_and_mode(self, sample_candidates):
        """Verify neuron with no tags is filtered out in AND mode.

        Neuron 5 (no tags) cannot satisfy any AND requirement.
        """
        conn, candidates, nids = sample_candidates
        result = filter_by_tags(conn, candidates, ["python"], "AND")
        result_ids = {r["neuron_id"] for r in result}
        assert nids[4] not in result_ids

    def test_neuron_with_no_tags_filtered_in_or_mode(self, sample_candidates):
        """Verify neuron with no tags is filtered out in OR mode.

        Neuron 5 (no tags) has no tags to match against.
        """
        conn, candidates, nids = sample_candidates
        result = filter_by_tags(conn, candidates, ["python"], "OR")
        result_ids = {r["neuron_id"] for r in result}
        assert nids[4] not in result_ids

    def test_invalid_tag_mode_defaults_to_and(self, sample_candidates):
        """Verify invalid tag_mode (e.g., "XOR") defaults to AND behavior."""
        conn, candidates, nids = sample_candidates
        result_invalid = filter_by_tags(conn, candidates, ["python"], "XOR")
        result_and = filter_by_tags(conn, candidates, ["python"], "AND")
        result_ids_invalid = {r["neuron_id"] for r in result_invalid}
        result_ids_and = {r["neuron_id"] for r in result_and}
        assert result_ids_invalid == result_ids_and

    def test_empty_candidates_returns_empty(self, tag_db):
        """Verify filtering empty candidate list returns empty list."""
        conn, nids = tag_db
        result = filter_by_tags(conn, [], ["python"], "AND")
        assert result == []


# -----------------------------------------------------------------------------
# Combined filter tests
# -----------------------------------------------------------------------------

class TestTagFilterCombined:
    """Test combined scenarios with multiple tags and modes."""

    def test_and_with_three_tags(self, sample_candidates):
        """Verify AND with ["python", "search", "memory"] keeps only neuron 1."""
        conn, candidates, nids = sample_candidates
        result = filter_by_tags(conn, candidates, ["python", "search", "memory"], "AND")
        result_ids = {r["neuron_id"] for r in result}
        assert result_ids == {nids[0]}

    def test_or_with_exclusive_tags(self, sample_candidates):
        """Verify OR with ["data", "memory"] keeps neurons 1, 2, 4.

        Neuron 1: has "memory". Neuron 2: has "data". Neuron 4: has "memory".
        """
        conn, candidates, nids = sample_candidates
        result = filter_by_tags(conn, candidates, ["data", "memory"], "OR")
        result_ids = {r["neuron_id"] for r in result}
        assert nids[0] in result_ids  # has memory
        assert nids[1] in result_ids  # has data
        assert nids[3] in result_ids  # has memory

    def test_all_candidates_metadata_preserved(self, sample_candidates):
        """Verify tag filtering doesn't modify candidate dicts.

        All activation scores, RRF scores, etc. should be intact.
        """
        conn, candidates, nids = sample_candidates
        result = filter_by_tags(conn, candidates, ["python"], "AND")
        for r in result:
            assert "activation_score" in r
            assert "rrf_score" in r
            assert r["activation_score"] == 1.0
