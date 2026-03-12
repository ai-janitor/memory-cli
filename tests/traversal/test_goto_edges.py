# =============================================================================
# Module: test_goto_edges.py
# Purpose: Test single-hop edge traversal — outgoing, incoming, both directions,
#   self-loops, empty results, pagination, and reference-not-found error handling.
# Rationale: Goto is the structural graph navigation command. Edge direction
#   logic (outgoing vs incoming vs both) and self-loop handling are the primary
#   correctness concerns. The "both" direction uses UNION ALL and must produce
#   correct ordering and counts even when self-loops appear twice. Edge metadata
#   (reason, weight, created_at, direction label) must be faithfully propagated.
# Responsibility:
#   - Test outgoing: follows edges where source_id = reference
#   - Test incoming: follows edges where target_id = reference
#   - Test both: union of outgoing + incoming
#   - Test self-loop: edge where source_id = target_id = reference appears in results
#   - Test ordering: edge created_at DESC, tie-break by neuron ID ASC
#   - Test empty result set returns exit 0 (no error)
#   - Test reference not found raises LookupError (caller maps to exit 1)
#   - Test pagination: limit, offset, total count is pre-pagination
#   - Test JSON envelope structure: command, reference_id, direction, results, total, limit, offset
#   - Test result object structure: {neuron: {...}, edge: {...}}
# Organization:
#   1. Imports and fixtures
#   2. Outgoing direction tests
#   3. Incoming direction tests
#   4. Both direction tests
#   5. Self-loop tests
#   6. Ordering tests
#   7. Pagination tests
#   8. Empty results and error tests
#   9. Envelope and result structure tests
# =============================================================================

from __future__ import annotations

import sqlite3
import time
import pytest
from typing import Any, Dict, List

from memory_cli.db.connection_setup_wal_fk_busy import open_connection
from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as apply_v001
from memory_cli.traversal.goto_follow_edges_single_hop import goto_follow_edges

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


def _create_neuron(conn, content, created_at_ms=None, project="test-project"):
    """Insert a neuron and return its ID."""
    if created_at_ms is None:
        created_at_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) "
        "VALUES (?, ?, ?, ?, 'active')",
        (content, created_at_ms, created_at_ms, project),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _create_edge(conn, source_id, target_id, reason="test reason", weight=1.0, created_at_ms=None):
    """Insert an edge and return its ID."""
    if created_at_ms is None:
        created_at_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO edges (source_id, target_id, weight, reason, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (source_id, target_id, weight, reason, created_at_ms),
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
def graph_with_edges(migrated_conn):
    """Insert neurons and edges forming a small test graph.

    Graph structure:
      neuron 1 (reference) --edge_A--> neuron 2 (outgoing, reason="relates_to", weight=0.8)
      neuron 1 (reference) --edge_B--> neuron 3 (outgoing, reason="caused_by", weight=0.5)
      neuron 4 --edge_C--> neuron 1 (reference) (incoming, reason="follows", weight=0.9)
      neuron 5 --edge_D--> neuron 1 (reference) (incoming, reason="contradicts", weight=0.3)
      neuron 1 --edge_E--> neuron 1 (self-loop, reason="self_ref", weight=1.0)

    Edge timestamps:
      edge_A: created_at=2000
      edge_B: created_at=1500
      edge_C: created_at=2500
      edge_D: created_at=1800
      edge_E: created_at=2200 (self-loop)

    Neuron tags: neuron 2 has tags ["important", "work"], others have none.

    Returns (conn, ref_id) tuple where ref_id is the ID of neuron 1.
    """
    conn = migrated_conn
    ref_id = _create_neuron(conn, "reference neuron", 5000)
    neuron2_id = _create_neuron(conn, "neuron 2 outgoing target", 5000)
    neuron3_id = _create_neuron(conn, "neuron 3 outgoing target", 5000)
    neuron4_id = _create_neuron(conn, "neuron 4 incoming source", 5000)
    neuron5_id = _create_neuron(conn, "neuron 5 incoming source", 5000)

    _create_edge(conn, ref_id, neuron2_id, reason="relates_to", weight=0.8, created_at_ms=2000)
    _create_edge(conn, ref_id, neuron3_id, reason="caused_by", weight=0.5, created_at_ms=1500)
    _create_edge(conn, neuron4_id, ref_id, reason="follows", weight=0.9, created_at_ms=2500)
    _create_edge(conn, neuron5_id, ref_id, reason="contradicts", weight=0.3, created_at_ms=1800)
    _create_edge(conn, ref_id, ref_id, reason="self_ref", weight=1.0, created_at_ms=2200)

    # Attach tags to neuron 2
    tag_important = _create_tag(conn, "important")
    tag_work = _create_tag(conn, "work")
    _attach_tag(conn, neuron2_id, tag_important)
    _attach_tag(conn, neuron2_id, tag_work)

    return conn, ref_id, neuron2_id, neuron3_id, neuron4_id, neuron5_id


# -----------------------------------------------------------------------------
# Outgoing direction tests
# -----------------------------------------------------------------------------

class TestGotoOutgoing:
    """Test outgoing edge traversal — edges where source_id = reference."""

    def test_outgoing_returns_target_neurons(self, graph_with_edges):
        """Verify outgoing walk returns neurons on the target side of edges.

        Setup: reference neuron 1 has outgoing edges to neurons 2 and 3.
        Expected: results contain neurons 2 and 3.
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="outgoing")
        neuron_ids = [r["neuron"]["id"] for r in result["results"]]
        # Should include n2, n3, and self-loop (ref_id) from outgoing
        assert n2_id in neuron_ids
        assert n3_id in neuron_ids

    def test_outgoing_default_direction(self, graph_with_edges):
        """Verify outgoing is the default when no direction specified.

        Call goto_follow_edges without direction kwarg, confirm outgoing behavior.
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id)
        assert result["direction"] == "outgoing"
        neuron_ids = [r["neuron"]["id"] for r in result["results"]]
        assert n2_id in neuron_ids

    def test_outgoing_includes_edge_metadata(self, graph_with_edges):
        """Verify each result includes edge reason, weight, created_at, direction.

        Expected: edge dict has reason="relates_to", weight=0.8, created_at=2000,
        direction="outgoing" for edge_A.
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="outgoing")
        # Find the result for n2 (edge_A)
        n2_result = next(r for r in result["results"] if r["neuron"]["id"] == n2_id)
        edge = n2_result["edge"]
        assert edge["reason"] == "relates_to"
        assert abs(edge["weight"] - 0.8) < 1e-6
        assert edge["created_at"] == 2000
        assert edge["direction"] == "outgoing"

    def test_outgoing_does_not_include_incoming_edges(self, graph_with_edges):
        """Verify outgoing direction does not return incoming edges.

        Neurons 4 and 5 have edges TO reference — they should not appear
        in outgoing results.
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="outgoing")
        neuron_ids = [r["neuron"]["id"] for r in result["results"]]
        assert n4_id not in neuron_ids
        assert n5_id not in neuron_ids


# -----------------------------------------------------------------------------
# Incoming direction tests
# -----------------------------------------------------------------------------

class TestGotoIncoming:
    """Test incoming edge traversal — edges where target_id = reference."""

    def test_incoming_returns_source_neurons(self, graph_with_edges):
        """Verify incoming walk returns neurons on the source side of edges.

        Setup: neurons 4 and 5 have edges to reference neuron 1.
        Expected: results contain neurons 4 and 5.
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="incoming")
        neuron_ids = [r["neuron"]["id"] for r in result["results"]]
        assert n4_id in neuron_ids
        assert n5_id in neuron_ids

    def test_incoming_includes_edge_metadata(self, graph_with_edges):
        """Verify each result includes edge metadata with direction='incoming'.

        Expected: edge dict has direction="incoming" for all results.
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="incoming")
        # All non-self-loop results should have direction="incoming"
        non_self = [r for r in result["results"] if r["neuron"]["id"] != ref_id]
        for r in non_self:
            assert r["edge"]["direction"] == "incoming"

    def test_incoming_does_not_include_outgoing_edges(self, graph_with_edges):
        """Verify incoming direction does not return outgoing edges.

        Reference neuron's outgoing edges to neurons 2 and 3 should not appear.
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="incoming")
        neuron_ids = [r["neuron"]["id"] for r in result["results"]]
        assert n2_id not in neuron_ids
        assert n3_id not in neuron_ids


# -----------------------------------------------------------------------------
# Both direction tests
# -----------------------------------------------------------------------------

class TestGotoBoth:
    """Test both direction — union of outgoing and incoming edges."""

    def test_both_returns_outgoing_and_incoming(self, graph_with_edges):
        """Verify both direction returns edges from both directions.

        Expected: results contain neurons from outgoing (2, 3) and incoming (4, 5).
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="both")
        neuron_ids = [r["neuron"]["id"] for r in result["results"]]
        assert n2_id in neuron_ids
        assert n3_id in neuron_ids
        assert n4_id in neuron_ids
        assert n5_id in neuron_ids

    def test_both_labels_direction_per_edge(self, graph_with_edges):
        """Verify each result's edge has correct direction label.

        Outgoing edges labeled "outgoing", incoming edges labeled "incoming".
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="both")
        # Find result for n2 (outgoing) and n4 (incoming)
        n2_result = next(
            (r for r in result["results"] if r["neuron"]["id"] == n2_id
             and r["edge"]["direction"] == "outgoing"), None
        )
        n4_result = next(
            (r for r in result["results"] if r["neuron"]["id"] == n4_id
             and r["edge"]["direction"] == "incoming"), None
        )
        assert n2_result is not None
        assert n4_result is not None

    def test_both_total_count_is_sum_of_both_directions(self, graph_with_edges):
        """Verify total count for 'both' includes all edges.

        Expected: total = outgoing_count + incoming_count.
        Note: self-loops appear twice (once outgoing, once incoming).
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        # Outgoing: edge_A (n2), edge_B (n3), edge_E (self-loop) = 3
        # Incoming: edge_C (n4), edge_D (n5), edge_E (self-loop) = 3
        # Total both = 6
        result_both = goto_follow_edges(conn, ref_id, direction="both")
        result_out = goto_follow_edges(conn, ref_id, direction="outgoing")
        result_in = goto_follow_edges(conn, ref_id, direction="incoming")
        assert result_both["total"] == result_out["total"] + result_in["total"]


# -----------------------------------------------------------------------------
# Self-loop tests
# -----------------------------------------------------------------------------

class TestGotoSelfLoop:
    """Test self-loop handling — edge where source_id = target_id = reference."""

    def test_self_loop_appears_in_outgoing(self, graph_with_edges):
        """Verify self-loop edge appears in outgoing results.

        Setup: edge_E is neuron 1 -> neuron 1.
        Outgoing query (source_id = 1): edge_E matches, connected neuron = 1.
        Expected: self-loop result present with neuron id=ref_id as connected neuron.
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="outgoing")
        self_loop_results = [r for r in result["results"] if r["neuron"]["id"] == ref_id]
        assert len(self_loop_results) >= 1

    def test_self_loop_appears_in_incoming(self, graph_with_edges):
        """Verify self-loop edge appears in incoming results.

        Incoming query (target_id = 1): edge_E matches, connected neuron = 1.
        Expected: self-loop result present.
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="incoming")
        self_loop_results = [r for r in result["results"] if r["neuron"]["id"] == ref_id]
        assert len(self_loop_results) >= 1

    def test_self_loop_appears_twice_in_both(self, graph_with_edges):
        """Verify self-loop appears twice in 'both' (once outgoing, once incoming).

        UNION ALL does not deduplicate — self-loop matches both WHERE clauses.
        Expected: two results for the self-loop edge, one labeled "outgoing",
        one labeled "incoming".
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="both")
        self_loop_results = [r for r in result["results"] if r["neuron"]["id"] == ref_id]
        # Self-loop with reason="self_ref" should appear twice
        self_ref_results = [r for r in self_loop_results if r["edge"]["reason"] == "self_ref"]
        assert len(self_ref_results) == 2
        directions = {r["edge"]["direction"] for r in self_ref_results}
        assert "outgoing" in directions
        assert "incoming" in directions

    def test_self_loop_edge_metadata_correct(self, graph_with_edges):
        """Verify self-loop edge has correct reason, weight, created_at.

        Expected: reason="self_ref", weight=1.0, created_at=2200.
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="outgoing")
        self_ref_result = next(
            r for r in result["results"] if r["edge"]["reason"] == "self_ref"
        )
        edge = self_ref_result["edge"]
        assert edge["reason"] == "self_ref"
        assert abs(edge["weight"] - 1.0) < 1e-6
        assert edge["created_at"] == 2200


# -----------------------------------------------------------------------------
# Ordering tests
# -----------------------------------------------------------------------------

class TestGotoOrdering:
    """Test result ordering — edge created_at DESC, tie-break neuron ID ASC."""

    def test_ordered_by_edge_created_at_descending(self, graph_with_edges):
        """Verify results are ordered by edge creation time, newest first.

        Setup: outgoing edges at created_at 2000 (edge_A) and 1500 (edge_B),
        plus self-loop at 2200.
        Expected: newest edge appears first.
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="outgoing")
        edge_timestamps = [r["edge"]["created_at"] for r in result["results"]]
        assert edge_timestamps == sorted(edge_timestamps, reverse=True)

    def test_tie_break_by_neuron_id_ascending(self, migrated_conn):
        """Verify edges with same created_at are tie-broken by neuron ID ascending.

        Setup: two outgoing edges with identical edge_created_at but different
        target neuron IDs.
        Expected: lower neuron ID appears first within the same timestamp.
        """
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 5000)
        target_a = _create_neuron(conn, "target A", 5000)
        target_b = _create_neuron(conn, "target B", 5000)
        # Both edges have the same created_at
        same_ts = 3000
        _create_edge(conn, ref_id, target_a, reason="to_a", created_at_ms=same_ts)
        _create_edge(conn, ref_id, target_b, reason="to_b", created_at_ms=same_ts)
        assert target_a < target_b  # AUTOINCREMENT guarantees this
        result = goto_follow_edges(conn, ref_id, direction="outgoing")
        same_ts_results = [r for r in result["results"] if r["edge"]["created_at"] == same_ts]
        ids = [r["neuron"]["id"] for r in same_ts_results]
        assert ids == sorted(ids)  # ascending by neuron ID

    def test_both_direction_ordering_across_directions(self, graph_with_edges):
        """Verify 'both' results interleave correctly by edge created_at DESC.

        Setup: mix of outgoing and incoming edges with various timestamps.
        Expected: all results ordered by edge_created_at DESC regardless of direction.
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="both")
        edge_timestamps = [r["edge"]["created_at"] for r in result["results"]]
        assert edge_timestamps == sorted(edge_timestamps, reverse=True)


# -----------------------------------------------------------------------------
# Pagination tests
# -----------------------------------------------------------------------------

class TestGotoPagination:
    """Test limit, offset, and total count behavior."""

    def test_default_limit_is_20(self, migrated_conn):
        """Verify default limit is 20 when not specified."""
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 5000)
        result = goto_follow_edges(conn, ref_id)
        assert result["limit"] == 20

    def test_default_offset_is_0(self, migrated_conn):
        """Verify default offset is 0 when not specified."""
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 5000)
        result = goto_follow_edges(conn, ref_id)
        assert result["offset"] == 0

    def test_limit_restricts_results(self, graph_with_edges):
        """Verify limit=1 returns only one result even when more edges exist.

        Setup: reference has 2 outgoing edges (plus self-loop = 3).
        Expected: results list has 1 item, total shows 3.
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="outgoing", limit=1)
        assert len(result["results"]) == 1
        assert result["total"] == 3  # edge_A, edge_B, edge_E (self-loop)

    def test_offset_skips_results(self, graph_with_edges):
        """Verify offset=1 skips the first matching edge result.

        Setup: reference has outgoing edges ordered by edge_created_at DESC.
        Expected with offset=1: first result is the second-newest edge.
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result_full = goto_follow_edges(conn, ref_id, direction="outgoing")
        result_offset = goto_follow_edges(conn, ref_id, direction="outgoing", offset=1)
        # The first result in offset=1 should match the second result in full
        assert result_offset["results"][0]["edge"]["created_at"] == \
               result_full["results"][1]["edge"]["created_at"]

    def test_total_is_pre_pagination_count(self, graph_with_edges):
        """Verify total reflects full edge count before limit/offset applied.

        Setup: 4 edges match incoming, limit=2.
        Expected: total=4, len(results)=2.
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        # incoming: edge_C (n4), edge_D (n5), edge_E (self-loop) = 3
        result = goto_follow_edges(conn, ref_id, direction="incoming", limit=2)
        assert result["total"] == 3
        assert len(result["results"]) == 2

    def test_offset_beyond_total_returns_empty(self, graph_with_edges):
        """Verify offset beyond total returns empty results, total still correct.

        Setup: 2 edges match, offset=10.
        Expected: results=[], total=2.
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="outgoing", offset=100)
        assert result["results"] == []
        assert result["total"] == 3  # edge_A, edge_B, edge_E


# -----------------------------------------------------------------------------
# Empty results and error tests
# -----------------------------------------------------------------------------

class TestGotoEmptyAndErrors:
    """Test empty result sets and reference-not-found error."""

    def test_no_outgoing_edges_returns_empty(self, migrated_conn):
        """Verify neuron with no outgoing edges returns empty results, exit 0.

        Setup: neuron exists but has no edges where source_id = its ID.
        Expected: results=[], total=0.
        """
        conn = migrated_conn
        ref_id = _create_neuron(conn, "isolated neuron", 5000)
        result = goto_follow_edges(conn, ref_id, direction="outgoing")
        assert result["results"] == []
        assert result["total"] == 0

    def test_no_incoming_edges_returns_empty(self, migrated_conn):
        """Verify neuron with no incoming edges returns empty results, exit 0.

        Setup: neuron exists but has no edges where target_id = its ID.
        Expected: results=[], total=0.
        """
        conn = migrated_conn
        ref_id = _create_neuron(conn, "isolated neuron", 5000)
        result = goto_follow_edges(conn, ref_id, direction="incoming")
        assert result["results"] == []
        assert result["total"] == 0

    def test_no_edges_at_all_returns_empty(self, migrated_conn):
        """Verify neuron with no edges in any direction returns empty for 'both'.

        Expected: results=[], total=0.
        """
        conn = migrated_conn
        ref_id = _create_neuron(conn, "isolated neuron", 5000)
        result = goto_follow_edges(conn, ref_id, direction="both")
        assert result["results"] == []
        assert result["total"] == 0

    def test_reference_not_found_raises_lookup_error(self, migrated_conn):
        """Verify non-existent reference ID raises LookupError.

        Setup: no neuron with id=9999 exists.
        Expected: LookupError raised (caller maps to exit 1).
        """
        conn = migrated_conn
        with pytest.raises(LookupError):
            goto_follow_edges(conn, 9999, direction="outgoing")

    def test_empty_result_envelope_structure(self, migrated_conn):
        """Verify empty result envelope still has all required keys.

        Expected keys: command, reference_id, direction, results, total, limit, offset.
        results should be [], total should be 0.
        """
        conn = migrated_conn
        ref_id = _create_neuron(conn, "isolated neuron", 5000)
        result = goto_follow_edges(conn, ref_id, direction="outgoing")
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
# Envelope and result structure tests
# -----------------------------------------------------------------------------

class TestGotoEnvelope:
    """Test the JSON envelope structure and result object shape."""

    def test_envelope_has_command_field(self, migrated_conn):
        """Verify envelope contains command='goto'."""
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 5000)
        result = goto_follow_edges(conn, ref_id)
        assert result["command"] == "goto"

    def test_envelope_has_reference_id(self, migrated_conn):
        """Verify envelope contains reference_id matching the input."""
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 5000)
        result = goto_follow_edges(conn, ref_id)
        assert result["reference_id"] == ref_id

    def test_envelope_has_direction(self, migrated_conn):
        """Verify envelope contains the direction that was requested."""
        conn = migrated_conn
        ref_id = _create_neuron(conn, "reference", 5000)
        result = goto_follow_edges(conn, ref_id, direction="incoming")
        assert result["direction"] == "incoming"

    def test_result_neuron_has_required_fields(self, graph_with_edges):
        """Verify each result's neuron dict contains: id, content, created_at, project, tags, source.

        Tags should be a list of strings (possibly empty).
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="outgoing")
        assert len(result["results"]) >= 1
        r = result["results"][0]
        assert "neuron" in r
        neuron = r["neuron"]
        assert "id" in neuron
        assert "content" in neuron
        assert "created_at" in neuron
        assert "project" in neuron
        assert "tags" in neuron
        assert "source" in neuron
        assert isinstance(neuron["tags"], list)

    def test_result_edge_has_required_fields(self, graph_with_edges):
        """Verify each result's edge dict contains: reason, weight, created_at, direction.

        - reason: string (semantic label)
        - weight: float
        - created_at: integer timestamp (edge creation time)
        - direction: "outgoing" or "incoming"
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="outgoing")
        assert len(result["results"]) >= 1
        r = result["results"][0]
        assert "edge" in r
        edge = r["edge"]
        assert "reason" in edge
        assert "weight" in edge
        assert "created_at" in edge
        assert "direction" in edge
        assert isinstance(edge["reason"], str)
        assert isinstance(edge["weight"], float)
        assert isinstance(edge["created_at"], int)
        assert edge["direction"] in ("outgoing", "incoming")

    def test_result_tags_are_hydrated(self, graph_with_edges):
        """Verify result neuron tags are hydrated names, not raw IDs.

        Setup: neuron 2 has tags ["important", "work"].
        Expected: result neuron's tags == ["important", "work"] (sorted).
        """
        conn, ref_id, n2_id, n3_id, n4_id, n5_id = graph_with_edges
        result = goto_follow_edges(conn, ref_id, direction="outgoing")
        n2_result = next(r for r in result["results"] if r["neuron"]["id"] == n2_id)
        assert n2_result["neuron"]["tags"] == ["important", "work"]
