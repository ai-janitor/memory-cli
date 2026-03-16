# =============================================================================
# Module: test_search_result_hydration.py
# Purpose: Test result hydration and output envelope — stage 10 of the light
#   search pipeline. Verifies neuron field hydration, tag attachment, envelope
#   structure, pagination metadata, and deleted neuron handling.
# Rationale: The hydration stage is the final transform before user-visible
#   output. Missing fields, wrong tag associations, or broken pagination
#   would be immediately visible to users. The envelope structure is a
#   contract that CLI formatters and downstream consumers depend on.
# Responsibility:
#   - Test neuron fields hydrated correctly (content, timestamps, project, etc.)
#   - Test tags attached as sorted list of names
#   - Test search metadata attached (match_type, hop_distance, edge_reason, score)
#   - Test score_breakdown conditionally included (only with --explain)
#   - Test envelope structure (results, pagination, metadata)
#   - Test pagination fields (total, limit, offset, has_more)
#   - Test deleted neuron skipped gracefully
#   - Test empty candidates → empty results
# Organization:
#   1. Imports and fixtures
#   2. Neuron field hydration tests
#   3. Tag hydration tests
#   4. Search metadata tests
#   5. Envelope structure tests
#   6. Pagination tests
#   7. Edge case tests (deleted neurons, empty input)
# =============================================================================

from __future__ import annotations

import time

import pytest

from memory_cli.search.search_result_hydration_and_envelope import (
    hydrate_results,
    build_envelope,
    _build_result_record,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """Full in-memory DB with schema."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as apply_v001
    from memory_cli.db.migrations.v004_add_access_tracking import apply as apply_v004
    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply_v001(conn)
    conn.execute("COMMIT")
    conn.execute("BEGIN")
    apply_v004(conn)
    conn.execute("COMMIT")
    return conn


def _insert_neuron(conn, content, project="test", source=None, tags=None):
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, source, status) "
        "VALUES (?, ?, ?, ?, ?, 'active')",
        (content, now_ms, now_ms, project, source),
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


def _make_candidate(neuron_id, final_score=0.5, match_type="direct_match",
                    hop_distance=0, edge_reason=None):
    return {
        "neuron_id": neuron_id,
        "final_score": final_score,
        "match_type": match_type,
        "hop_distance": hop_distance,
        "edge_reason": edge_reason,
    }


@pytest.fixture
def hydration_db(migrated_conn):
    """DB with 3 neurons having known content and tags."""
    conn = migrated_conn
    conn.execute("BEGIN")
    n1 = _insert_neuron(conn, "alpha", project="proj-a", source="src-1",
                        tags=["python", "search"])
    n2 = _insert_neuron(conn, "beta", project="proj-b", source=None,
                        tags=["rust"])
    n3 = _insert_neuron(conn, "gamma", project="proj-a", source=None, tags=[])
    conn.execute("COMMIT")
    return conn, [n1, n2, n3]


@pytest.fixture
def sample_paginated_candidates(hydration_db):
    conn, nids = hydration_db
    candidates = [
        _make_candidate(nids[0], final_score=0.9, match_type="direct_match"),
        _make_candidate(nids[1], final_score=0.5, match_type="direct_match"),
        _make_candidate(nids[2], final_score=0.3, match_type="fan_out",
                        hop_distance=1, edge_reason="related"),
    ]
    return conn, candidates, nids


# -----------------------------------------------------------------------------
# Neuron field hydration tests
# -----------------------------------------------------------------------------

class TestNeuronFieldHydration:
    """Test that neuron fields are correctly hydrated from DB."""

    def test_content_field_populated(self, sample_paginated_candidates):
        """Verify result has correct content string from DB."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, [candidates[0]])
        assert results[0]["content"] == "alpha"

    def test_created_at_field_populated(self, sample_paginated_candidates):
        """Verify result has correct created_at timestamp (int ms)."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, [candidates[0]])
        assert isinstance(results[0]["created_at"], int)
        assert results[0]["created_at"] > 0

    def test_updated_at_field_populated(self, sample_paginated_candidates):
        """Verify result has correct updated_at timestamp."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, [candidates[0]])
        assert isinstance(results[0]["updated_at"], int)

    def test_project_field_populated(self, sample_paginated_candidates):
        """Verify result has correct project string."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, [candidates[0]])
        assert results[0]["project"] == "proj-a"

    def test_source_field_populated(self, sample_paginated_candidates):
        """Verify result has correct source string (may be None)."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, [candidates[0]])
        assert results[0]["source"] == "src-1"

    def test_status_field_populated(self, sample_paginated_candidates):
        """Verify result has correct status string."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, [candidates[0]])
        assert results[0]["status"] == "active"

    def test_id_field_matches_neuron_id(self, sample_paginated_candidates):
        """Verify result's id field matches the neuron_id from candidate."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, candidates)
        for i, r in enumerate(results):
            assert r["id"] == candidates[i]["neuron_id"]


# -----------------------------------------------------------------------------
# Tag hydration tests
# -----------------------------------------------------------------------------

class TestTagHydration:
    """Test that tags are correctly attached to hydrated results."""

    def test_tags_present_as_list(self, sample_paginated_candidates):
        """Verify tags field is a list of strings."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, [candidates[0]])
        assert isinstance(results[0]["tags"], list)

    def test_tags_sorted_alphabetically(self, sample_paginated_candidates):
        """Verify tags are sorted by name."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, [candidates[0]])
        tags = results[0]["tags"]
        assert tags == sorted(tags)
        assert "python" in tags
        assert "search" in tags

    def test_neuron_with_no_tags_has_empty_list(self, sample_paginated_candidates):
        """Verify neuron with no tags gets tags=[]."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, [candidates[2]])
        assert results[0]["tags"] == []

    def test_multiple_tags_all_present(self, sample_paginated_candidates):
        """Verify all associated tags appear in the list."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, [candidates[0]])
        assert set(results[0]["tags"]) == {"python", "search"}


# -----------------------------------------------------------------------------
# Search metadata tests
# -----------------------------------------------------------------------------

class TestSearchMetadataAttachment:
    """Test that search metadata is attached to each result."""

    def test_match_type_attached(self, sample_paginated_candidates):
        """Verify match_type field is present (direct_match or fan_out)."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, candidates)
        for r in results:
            assert "match_type" in r

    def test_hop_distance_attached(self, sample_paginated_candidates):
        """Verify hop_distance field is present (int)."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, candidates)
        for r in results:
            assert "hop_distance" in r
            assert isinstance(r["hop_distance"], int)

    def test_edge_reason_attached(self, sample_paginated_candidates):
        """Verify edge_reason field is present (string or None)."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, candidates)
        # fan-out candidate should have edge_reason
        fan_out_result = next(r for r in results if r["match_type"] == "fan_out")
        assert fan_out_result["edge_reason"] == "related"

    def test_score_field_attached(self, sample_paginated_candidates):
        """Verify score field contains final_score value."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, candidates)
        assert results[0]["score"] == 0.9

    def test_breakdown_included_with_explain(self, sample_paginated_candidates):
        """Verify score_breakdown is included when explain=True."""
        conn, candidates, nids = sample_paginated_candidates
        # Pre-attach breakdown (as the pipeline would do)
        candidates[0]["score_breakdown"] = {"final_score": 0.9}
        results = hydrate_results(conn, [candidates[0]], explain=True)
        assert "score_breakdown" in results[0]
        assert results[0]["score_breakdown"]["final_score"] == 0.9

    def test_breakdown_omitted_without_explain(self, sample_paginated_candidates):
        """Verify score_breakdown is NOT included when explain=False."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, [candidates[0]], explain=False)
        assert "score_breakdown" not in results[0]


# -----------------------------------------------------------------------------
# Envelope structure tests
# -----------------------------------------------------------------------------

class TestEnvelopeStructure:
    """Test the output envelope dict structure."""

    def test_envelope_has_results_key(self):
        """Verify envelope has 'results' key with list value."""
        env = build_envelope([], 0, 20, 0)
        assert "results" in env
        assert isinstance(env["results"], list)

    def test_envelope_has_pagination_key(self):
        """Verify envelope has 'pagination' key with dict value."""
        env = build_envelope([], 0, 20, 0)
        assert "pagination" in env
        assert isinstance(env["pagination"], dict)

    def test_envelope_has_metadata_key(self):
        """Verify envelope has 'metadata' key with dict value."""
        env = build_envelope([], 0, 20, 0)
        assert "metadata" in env
        assert isinstance(env["metadata"], dict)

    def test_pagination_has_total(self):
        """Verify pagination has 'total' field (int)."""
        env = build_envelope([], 50, 20, 0)
        assert env["pagination"]["total"] == 50

    def test_pagination_has_limit(self):
        """Verify pagination has 'limit' field (int)."""
        env = build_envelope([], 50, 20, 0)
        assert env["pagination"]["limit"] == 20

    def test_pagination_has_offset(self):
        """Verify pagination has 'offset' field (int)."""
        env = build_envelope([], 50, 20, 10)
        assert env["pagination"]["offset"] == 10

    def test_pagination_has_has_more(self):
        """Verify pagination has 'has_more' field (bool)."""
        env = build_envelope([], 50, 20, 0)
        assert "has_more" in env["pagination"]
        assert isinstance(env["pagination"]["has_more"], bool)

    def test_metadata_has_vector_unavailable(self):
        """Verify metadata has 'vector_unavailable' field (bool)."""
        env = build_envelope([], 0, 20, 0, vector_unavailable=True)
        assert env["metadata"]["vector_unavailable"] is True

    def test_metadata_has_result_count(self):
        """Verify metadata has 'result_count' field matching len(results)."""
        fake_results = [{"id": 1}, {"id": 2}]
        env = build_envelope(fake_results, 5, 20, 0)
        assert env["metadata"]["result_count"] == 2


# -----------------------------------------------------------------------------
# Pagination tests
# -----------------------------------------------------------------------------

class TestEnvelopePagination:
    """Test pagination metadata correctness."""

    def test_has_more_true_when_more_results(self):
        """Verify has_more=True when total > offset + limit."""
        env = build_envelope([], 100, 20, 0)
        assert env["pagination"]["has_more"] is True

    def test_has_more_false_when_no_more_results(self):
        """Verify has_more=False when total <= offset + limit."""
        env = build_envelope([], 20, 20, 0)
        assert env["pagination"]["has_more"] is False

    def test_result_count_matches_actual_results(self):
        """Verify metadata.result_count == len(envelope.results)."""
        fake_results = [{"id": i} for i in range(5)]
        env = build_envelope(fake_results, 100, 20, 0)
        assert env["metadata"]["result_count"] == len(fake_results)


# -----------------------------------------------------------------------------
# Edge case tests
# -----------------------------------------------------------------------------

class TestHydrationEdgeCases:
    """Test edge cases in hydration."""

    def test_deleted_neuron_skipped(self, hydration_db):
        """Verify a candidate whose neuron was deleted is silently skipped.

        Candidate refers to neuron_id=99 which doesn't exist.
        Assert: no error, result list has one fewer entry.
        """
        conn, nids = hydration_db
        candidates = [
            _make_candidate(nids[0], final_score=0.9),
            _make_candidate(9999, final_score=0.5),  # non-existent
        ]
        results = hydrate_results(conn, candidates)
        assert len(results) == 1
        assert results[0]["id"] == nids[0]

    def test_empty_candidates_returns_empty(self, hydration_db):
        """Verify empty paginated_candidates → empty results list."""
        conn, nids = hydration_db
        results = hydrate_results(conn, [])
        assert results == []

    def test_results_preserve_candidate_order(self, sample_paginated_candidates):
        """Verify hydrated results maintain the ranking order from candidates."""
        conn, candidates, nids = sample_paginated_candidates
        results = hydrate_results(conn, candidates)
        result_ids = [r["id"] for r in results]
        candidate_ids = [c["neuron_id"] for c in candidates]
        assert result_ids == candidate_ids


# -----------------------------------------------------------------------------
# Edge topology summary tests
# -----------------------------------------------------------------------------

class TestEdgeTopologySummary:
    """Test edges topology summary attached to search results."""

    def test_edges_key_present_in_result(self, hydration_db):
        """Verify each hydrated result has an 'edges' dict."""
        conn, nids = hydration_db
        candidates = [_make_candidate(nids[0], final_score=0.9)]
        results = hydrate_results(conn, candidates)
        assert "edges" in results[0]
        assert isinstance(results[0]["edges"], dict)

    def test_edges_has_top_types_and_total(self, hydration_db):
        """Verify edges dict has top_types list and total int."""
        conn, nids = hydration_db
        candidates = [_make_candidate(nids[0], final_score=0.9)]
        results = hydrate_results(conn, candidates)
        edges = results[0]["edges"]
        assert "top_types" in edges
        assert "total" in edges
        assert isinstance(edges["top_types"], list)
        assert isinstance(edges["total"], int)

    def test_neuron_with_no_edges_has_empty_summary(self, hydration_db):
        """Verify neuron with no edges gets top_types=[] and total=0."""
        conn, nids = hydration_db
        # nids[0..2] have no edges in hydration_db fixture
        candidates = [_make_candidate(nids[0], final_score=0.9)]
        results = hydrate_results(conn, candidates)
        assert results[0]["edges"]["top_types"] == []
        assert results[0]["edges"]["total"] == 0

    def test_edges_summary_counts_correct(self, hydration_db):
        """Verify edge type counts are correct when edges exist."""
        conn, nids = hydration_db
        now_ms = int(time.time() * 1000)
        # Add edges: nids[0] -> nids[1] (related_to), nids[0] -> nids[2] (related_to),
        #            nids[1] -> nids[0] (depends_on)
        conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, weight, created_at) "
            "VALUES (?, ?, ?, ?, ?)", (nids[0], nids[1], "related_to", 1.0, now_ms))
        conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, weight, created_at) "
            "VALUES (?, ?, ?, ?, ?)", (nids[0], nids[2], "related_to", 1.0, now_ms))
        conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, weight, created_at) "
            "VALUES (?, ?, ?, ?, ?)", (nids[1], nids[0], "depends_on", 1.0, now_ms))

        candidates = [_make_candidate(nids[0], final_score=0.9)]
        results = hydrate_results(conn, candidates)
        edges = results[0]["edges"]

        assert edges["total"] == 3
        types_map = {t["type"]: t["count"] for t in edges["top_types"]}
        assert types_map["related_to"] == 2
        assert types_map["depends_on"] == 1

    def test_top_types_ordered_by_count_desc(self, hydration_db):
        """Verify top_types are ordered by count descending."""
        conn, nids = hydration_db
        now_ms = int(time.time() * 1000)
        # 3 related_to, 1 depends_on
        for target in [nids[1], nids[2], nids[1]]:
            conn.execute(
                "INSERT INTO edges (source_id, target_id, reason, weight, created_at) "
                "VALUES (?, ?, ?, ?, ?)", (nids[0], target, "related_to", 1.0, now_ms))
        conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, weight, created_at) "
            "VALUES (?, ?, ?, ?, ?)", (nids[1], nids[0], "depends_on", 1.0, now_ms))

        candidates = [_make_candidate(nids[0], final_score=0.9)]
        results = hydrate_results(conn, candidates)
        top_types = results[0]["edges"]["top_types"]
        assert top_types[0]["type"] == "related_to"
        assert top_types[0]["count"] >= top_types[1]["count"]
