# =============================================================================
# Module: test_tag_affinity_scoring.py
# Purpose: Test tag-affinity scoring — stage 5b of the light search pipeline.
#   Verifies that neurons sharing tags with seed neurons get boosted, that
#   rare tags produce stronger signals, and that tag-only neighbors are
#   discovered and injected into the candidate set.
# Rationale: Tag-affinity is an additive scoring layer that augments graph-based
#   spreading activation. Bugs here would silently corrupt search ranking by
#   over/under-weighting shared tags, or fail to discover tag-connected neurons.
# Responsibility:
#   - Test seed tag collection from DB
#   - Test tag weight computation (1/count)
#   - Test scoring of existing candidates via shared tags
#   - Test discovery of new neurons sharing tags with seeds
#   - Test edge cases: no seeds, no tags, empty candidate list
#   - Test rare vs common tag weighting
#   - Test multiple shared tags sum correctly
# Organization:
#   1. Imports and fixtures
#   2. Seed tag collection tests
#   3. Tag weight computation tests
#   4. Candidate scoring tests
#   5. Tag-neighbor discovery tests
#   6. Edge case tests
#   7. Integration with final scoring tests
# =============================================================================

from __future__ import annotations

import time

import pytest

from memory_cli.search.tag_affinity_scoring_shared_tags import (
    apply_tag_affinity,
    _collect_seed_tags,
    _compute_tag_weights,
    _score_candidates,
    _discover_tag_neighbors,
)
from memory_cli.search.final_score_combine_and_rank import (
    compute_final_scores,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """Full in-memory DB with schema for tag-affinity testing."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply
    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply(conn)
    conn.execute("COMMIT")
    return conn


def _insert_neuron(conn, content="test", project="test"):
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) "
        "VALUES (?, ?, ?, ?, 'active')",
        (content, now_ms, now_ms, project),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _insert_tag(conn, name):
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO tags (name, created_at) VALUES (?, ?)",
        (name, now_ms),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _link_neuron_tag(conn, neuron_id, tag_id):
    conn.execute(
        "INSERT INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)",
        (neuron_id, tag_id),
    )


def _make_direct_candidate(neuron_id, rrf_score=0.016):
    return {
        "neuron_id": neuron_id,
        "rrf_score": rrf_score,
        "match_type": "direct_match",
        "activation_score": 1.0,
        "hop_distance": 0,
        "edge_reason": None,
    }


def _make_fanout_candidate(neuron_id, activation_score=0.4):
    return {
        "neuron_id": neuron_id,
        "rrf_score": 0.0,
        "match_type": "fan_out",
        "activation_score": activation_score,
        "hop_distance": 1,
        "edge_reason": "related",
    }


@pytest.fixture
def tagged_db(migrated_conn):
    """DB with neurons and tags for affinity testing.

    Neurons:
      1 (seed) — tags: rust, async
      2 (seed) — tags: rust, python
      3 (fan-out, already in candidates) — tags: rust
      4 (not in candidates) — tags: rust, async  (shares 2 tags with seeds)
      5 (not in candidates) — tags: python       (shares 1 tag with seeds)
      6 (not in candidates) — tags: javascript   (no shared tags)
      7 (not in candidates) — tags: async         (shares 1 tag with seeds)

    Tag distribution (for weight computation):
      rust:       neurons 1, 2, 3, 4  → count=4, weight=0.25
      async:      neurons 1, 4, 7     → count=3, weight=0.333...
      python:     neurons 2, 5        → count=2, weight=0.5
      javascript: neurons 6           → count=1, weight=1.0
    """
    conn = migrated_conn
    conn.execute("BEGIN")

    # Insert neurons
    for i in range(1, 8):
        _insert_neuron(conn, f"neuron {i}")

    # Insert tags
    t_rust = _insert_tag(conn, "rust")
    t_async = _insert_tag(conn, "async")
    t_python = _insert_tag(conn, "python")
    t_javascript = _insert_tag(conn, "javascript")

    # Link neurons to tags
    _link_neuron_tag(conn, 1, t_rust)
    _link_neuron_tag(conn, 1, t_async)
    _link_neuron_tag(conn, 2, t_rust)
    _link_neuron_tag(conn, 2, t_python)
    _link_neuron_tag(conn, 3, t_rust)
    _link_neuron_tag(conn, 4, t_rust)
    _link_neuron_tag(conn, 4, t_async)
    _link_neuron_tag(conn, 5, t_python)
    _link_neuron_tag(conn, 6, t_javascript)
    _link_neuron_tag(conn, 7, t_async)

    conn.execute("COMMIT")
    return conn


# -----------------------------------------------------------------------------
# Seed tag collection tests
# -----------------------------------------------------------------------------

class TestSeedTagCollection:
    """Test _collect_seed_tags correctly retrieves tags from seed neurons."""

    def test_collects_tags_from_single_seed(self, tagged_db):
        """Verify tags from a single seed neuron are collected."""
        tag_ids = _collect_seed_tags(tagged_db, [1])
        assert len(tag_ids) == 2  # rust, async

    def test_collects_tags_from_multiple_seeds(self, tagged_db):
        """Verify tags from multiple seeds are unioned (no duplicates)."""
        tag_ids = _collect_seed_tags(tagged_db, [1, 2])
        assert len(tag_ids) == 3  # rust, async, python (rust deduplicated)

    def test_empty_seed_list_returns_empty(self, tagged_db):
        """Verify empty seed list returns empty set."""
        tag_ids = _collect_seed_tags(tagged_db, [])
        assert len(tag_ids) == 0

    def test_seed_with_no_tags_returns_empty(self, migrated_conn):
        """Verify seed with no tags returns empty set."""
        conn = migrated_conn
        conn.execute("BEGIN")
        nid = _insert_neuron(conn, "no tags")
        conn.execute("COMMIT")
        tag_ids = _collect_seed_tags(conn, [nid])
        assert len(tag_ids) == 0


# -----------------------------------------------------------------------------
# Tag weight computation tests
# -----------------------------------------------------------------------------

class TestTagWeightComputation:
    """Test _compute_tag_weights produces correct 1/count weights."""

    def test_rare_tag_gets_higher_weight(self, tagged_db):
        """Verify a tag on fewer neurons gets a higher weight.

        python is on 2 neurons → weight=0.5
        rust is on 4 neurons → weight=0.25
        """
        # Get tag IDs
        seed_tags = _collect_seed_tags(tagged_db, [1, 2])
        weights = _compute_tag_weights(tagged_db, seed_tags)
        # python tag should have higher weight than rust tag
        weight_values = sorted(weights.values(), reverse=True)
        # python=0.5, async=0.333, rust=0.25
        assert abs(weight_values[0] - 0.5) < 1e-9
        assert abs(weight_values[1] - 1.0 / 3) < 1e-9
        assert abs(weight_values[2] - 0.25) < 1e-9

    def test_empty_tag_set_returns_empty(self, tagged_db):
        """Verify empty tag set returns empty weights dict."""
        weights = _compute_tag_weights(tagged_db, set())
        assert weights == {}


# -----------------------------------------------------------------------------
# Candidate scoring tests
# -----------------------------------------------------------------------------

class TestCandidateScoring:
    """Test scoring of existing candidates via shared tags."""

    def test_candidate_sharing_tag_with_seed_gets_score(self, tagged_db):
        """Verify fan-out candidate sharing a tag with seed gets nonzero score."""
        candidates = [
            _make_direct_candidate(1),
            _make_fanout_candidate(3),  # has tag: rust
        ]
        result = apply_tag_affinity(tagged_db, candidates)
        by_id = {r["neuron_id"]: r for r in result}
        # Neuron 3 shares "rust" with seed 1 → should have positive affinity
        assert by_id[3]["tag_affinity_score"] > 0

    def test_seed_gets_own_tag_affinity_score(self, tagged_db):
        """Verify seed neurons also get a tag_affinity_score (self-scoring)."""
        candidates = [_make_direct_candidate(1)]
        result = apply_tag_affinity(tagged_db, candidates)
        # Seed 1 has tags rust and async which are also seed tags
        assert result[0]["tag_affinity_score"] > 0

    def test_multiple_shared_tags_sum(self, tagged_db):
        """Verify multiple shared tags sum their weights.

        Seeds 1,2 have tags: rust, async, python.
        If a candidate has rust+async, its score = weight(rust) + weight(async).
        """
        candidates = [
            _make_direct_candidate(1),
            _make_direct_candidate(2),
        ]
        result = apply_tag_affinity(tagged_db, candidates)
        by_id = {r["neuron_id"]: r for r in result}
        # Neuron 1 has rust (w=0.25) + async (w=0.333) → score ≈ 0.583
        score_1 = by_id[1]["tag_affinity_score"]
        assert abs(score_1 - (0.25 + 1.0 / 3)) < 1e-9


# -----------------------------------------------------------------------------
# Tag-neighbor discovery tests
# -----------------------------------------------------------------------------

class TestTagNeighborDiscovery:
    """Test discovery of new neurons sharing tags with seeds."""

    def test_discovers_new_neuron_sharing_tag(self, tagged_db):
        """Verify neurons not in candidates but sharing seed tags are discovered."""
        candidates = [
            _make_direct_candidate(1),
            _make_direct_candidate(2),
        ]
        result = apply_tag_affinity(tagged_db, candidates)
        result_ids = {r["neuron_id"] for r in result}
        # Neuron 4 (rust+async), 5 (python), 7 (async) should be discovered
        assert 4 in result_ids
        assert 5 in result_ids
        assert 7 in result_ids

    def test_discovered_neuron_has_tag_affinity_match_type(self, tagged_db):
        """Verify discovered neurons have match_type='tag_affinity'."""
        candidates = [
            _make_direct_candidate(1),
            _make_direct_candidate(2),
        ]
        result = apply_tag_affinity(tagged_db, candidates)
        by_id = {r["neuron_id"]: r for r in result}
        assert by_id[4]["match_type"] == "tag_affinity"

    def test_discovered_neuron_has_correct_score(self, tagged_db):
        """Verify discovered neuron's score sums shared-tag weights.

        Neuron 4 shares rust (w=0.25) + async (w=0.333) with seeds.
        Score should be 0.25 + 0.333 ≈ 0.583.
        """
        candidates = [
            _make_direct_candidate(1),
            _make_direct_candidate(2),
        ]
        result = apply_tag_affinity(tagged_db, candidates)
        by_id = {r["neuron_id"]: r for r in result}
        expected = 0.25 + 1.0 / 3
        assert abs(by_id[4]["tag_affinity_score"] - expected) < 1e-9

    def test_neuron_with_no_shared_tags_not_discovered(self, tagged_db):
        """Verify neuron 6 (javascript only) is NOT discovered — no shared tags."""
        candidates = [
            _make_direct_candidate(1),
            _make_direct_candidate(2),
        ]
        result = apply_tag_affinity(tagged_db, candidates)
        result_ids = {r["neuron_id"] for r in result}
        assert 6 not in result_ids

    def test_already_existing_candidate_not_duplicated(self, tagged_db):
        """Verify neuron already in candidates is not added again."""
        candidates = [
            _make_direct_candidate(1),
            _make_fanout_candidate(3),  # neuron 3 shares rust with seed
        ]
        result = apply_tag_affinity(tagged_db, candidates)
        ids = [r["neuron_id"] for r in result]
        assert ids.count(3) == 1  # not duplicated


# -----------------------------------------------------------------------------
# Edge case tests
# -----------------------------------------------------------------------------

class TestTagAffinityEdgeCases:
    """Test edge cases for tag-affinity scoring."""

    def test_no_seeds_returns_candidates_unchanged(self, tagged_db):
        """Verify no seed neurons → all get tag_affinity_score=0.0."""
        candidates = [_make_fanout_candidate(3)]
        result = apply_tag_affinity(tagged_db, candidates)
        assert len(result) == 1
        assert result[0]["tag_affinity_score"] == 0.0

    def test_seeds_with_no_tags_returns_zero_scores(self, migrated_conn):
        """Verify seeds with no tags → all get tag_affinity_score=0.0."""
        conn = migrated_conn
        conn.execute("BEGIN")
        nid = _insert_neuron(conn, "untagged seed")
        conn.execute("COMMIT")
        candidates = [_make_direct_candidate(nid)]
        result = apply_tag_affinity(conn, candidates)
        assert result[0]["tag_affinity_score"] == 0.0

    def test_empty_candidate_list(self, tagged_db):
        """Verify empty candidate list returns empty list."""
        result = apply_tag_affinity(tagged_db, [])
        assert result == []

    def test_no_threshold_weak_scores_kept(self, tagged_db):
        """Verify even weak tag-affinity scores are preserved (no cutoff).

        Spec says: if result set would be empty, return weak tag-links anyway.
        """
        candidates = [
            _make_direct_candidate(1),  # tags: rust, async
        ]
        result = apply_tag_affinity(tagged_db, candidates)
        # All discovered neurons should be kept regardless of score
        discovered = [r for r in result if r.get("match_type") == "tag_affinity"]
        for d in discovered:
            assert d["tag_affinity_score"] > 0


# -----------------------------------------------------------------------------
# Integration with final scoring tests
# -----------------------------------------------------------------------------

class TestTagAffinityFinalScoring:
    """Test that tag_affinity_score integrates correctly with final scoring."""

    def test_tag_affinity_boosts_direct_match(self):
        """Verify tag_affinity_score is additive in direct_match scoring.

        final_score = (rrf_score + tag_affinity_score) * temporal_weight
        """
        candidates = [
            {
                "neuron_id": 1,
                "match_type": "direct_match",
                "rrf_score": 0.016,
                "tag_affinity_score": 0.25,
                "temporal_weight": 1.0,
            }
        ]
        result = compute_final_scores(candidates)
        expected = (0.016 + 0.25) * 1.0
        assert abs(result[0]["final_score"] - expected) < 1e-10

    def test_tag_affinity_boosts_fan_out(self):
        """Verify tag_affinity_score is additive in fan_out scoring.

        final_score = (activation_score + tag_affinity_score) * temporal_weight
        """
        candidates = [
            {
                "neuron_id": 2,
                "match_type": "fan_out",
                "activation_score": 0.4,
                "tag_affinity_score": 0.5,
                "temporal_weight": 1.0,
            }
        ]
        result = compute_final_scores(candidates)
        expected = (0.4 + 0.5) * 1.0
        assert abs(result[0]["final_score"] - expected) < 1e-10

    def test_tag_affinity_only_neuron_scored(self):
        """Verify tag_affinity-only neurons (match_type='tag_affinity') are scored.

        final_score = tag_affinity_score * temporal_weight
        """
        candidates = [
            {
                "neuron_id": 3,
                "match_type": "tag_affinity",
                "tag_affinity_score": 0.583,
                "temporal_weight": 0.8,
            }
        ]
        result = compute_final_scores(candidates)
        expected = 0.583 * 0.8
        assert abs(result[0]["final_score"] - expected) < 1e-10

    def test_tag_affinity_changes_ranking(self):
        """Verify tag_affinity_score can reorder results.

        Without affinity: neuron 1 (rrf=0.03) > neuron 2 (rrf=0.01).
        With affinity: neuron 2 (rrf=0.01 + affinity=0.5) > neuron 1 (rrf=0.03 + affinity=0.0).
        """
        candidates = [
            {
                "neuron_id": 1,
                "match_type": "direct_match",
                "rrf_score": 0.03,
                "tag_affinity_score": 0.0,
                "temporal_weight": 1.0,
            },
            {
                "neuron_id": 2,
                "match_type": "direct_match",
                "rrf_score": 0.01,
                "tag_affinity_score": 0.5,
                "temporal_weight": 1.0,
            },
        ]
        result = compute_final_scores(candidates)
        # Neuron 2 should now be first (0.01+0.5=0.51 > 0.03+0.0=0.03)
        assert result[0]["neuron_id"] == 2

    def test_no_tag_affinity_defaults_to_zero(self):
        """Verify missing tag_affinity_score defaults to 0 (backward compat)."""
        candidates = [
            {
                "neuron_id": 1,
                "match_type": "direct_match",
                "rrf_score": 0.016,
                "temporal_weight": 1.0,
                # no tag_affinity_score key
            }
        ]
        result = compute_final_scores(candidates)
        # Should work like before: rrf_score * temporal_weight
        assert abs(result[0]["final_score"] - 0.016) < 1e-10


# -----------------------------------------------------------------------------
# Depth=2 tag-affinity tests
# -----------------------------------------------------------------------------

@pytest.fixture
def depth2_db(migrated_conn):
    """DB with neurons and tags for depth=2 affinity testing.

    Simulates the test case: arc-b60 →(cpp)→ GLOBAL-131 →(architecture)→ GLOBAL-124

    Neurons:
      1 (seed, "arc-b60 gpu kernels") — tags: cpp, gpu
      2 (depth=1 hop, "llama.cpp internals") — tags: cpp, architecture
      3 (depth=2 target, "visualizer system") — tags: architecture, rendering
      4 (unrelated) — tags: javascript

    Tag distribution:
      cpp:           neurons 1, 2       → count=2, weight=0.5
      gpu:           neurons 1          → count=1, weight=1.0
      architecture:  neurons 2, 3       → count=2, weight=0.5
      rendering:     neurons 3          → count=1, weight=1.0
      javascript:    neurons 4          → count=1, weight=1.0

    Expected depth=1: neuron 2 discovered via cpp (score=0.5)
    Expected depth=2: neuron 3 discovered via architecture through neuron 2
      hop1_score(neuron2) = 0.5, hop2_weight(architecture) = 0.5
      depth2_score = 0.5 * 0.5 = 0.25
    """
    conn = migrated_conn
    conn.execute("BEGIN")

    # Insert neurons
    for i in range(1, 5):
        _insert_neuron(conn, f"neuron {i}")

    # Insert tags
    t_cpp = _insert_tag(conn, "cpp")
    t_gpu = _insert_tag(conn, "gpu")
    t_arch = _insert_tag(conn, "architecture")
    t_render = _insert_tag(conn, "rendering")
    t_js = _insert_tag(conn, "javascript")

    # Link neurons to tags
    _link_neuron_tag(conn, 1, t_cpp)
    _link_neuron_tag(conn, 1, t_gpu)
    _link_neuron_tag(conn, 2, t_cpp)
    _link_neuron_tag(conn, 2, t_arch)
    _link_neuron_tag(conn, 3, t_arch)
    _link_neuron_tag(conn, 3, t_render)
    _link_neuron_tag(conn, 4, t_js)

    conn.execute("COMMIT")
    return conn


class TestDepth2TagAffinity:
    """Test depth=2 tag-affinity scoring discovers neurons 2 hops away."""

    def test_depth2_discovers_neuron_through_hop1(self, depth2_db):
        """Verify depth=2 finds neuron 3 through neuron 2.

        Seed 1 →(cpp)→ neuron 2 →(architecture)→ neuron 3.
        Neuron 3 is NOT reachable at depth=1 (no shared tags with seed 1).
        """
        candidates = [_make_direct_candidate(1)]
        result = apply_tag_affinity(depth2_db, candidates)
        result_ids = {r["neuron_id"] for r in result}
        assert 3 in result_ids, "Depth=2 should discover neuron 3 via architecture"

    def test_depth2_neuron_has_correct_match_type(self, depth2_db):
        """Verify depth=2 discovered neurons have match_type='tag_affinity'."""
        candidates = [_make_direct_candidate(1)]
        result = apply_tag_affinity(depth2_db, candidates)
        by_id = {r["neuron_id"]: r for r in result}
        assert by_id[3]["match_type"] == "tag_affinity"

    def test_depth2_neuron_has_depth_2(self, depth2_db):
        """Verify depth=2 discovered neurons have tag_affinity_depth=2."""
        candidates = [_make_direct_candidate(1)]
        result = apply_tag_affinity(depth2_db, candidates)
        by_id = {r["neuron_id"]: r for r in result}
        assert by_id[3]["tag_affinity_depth"] == 2

    def test_depth1_neuron_has_depth_1(self, depth2_db):
        """Verify depth=1 discovered neurons have tag_affinity_depth=1."""
        candidates = [_make_direct_candidate(1)]
        result = apply_tag_affinity(depth2_db, candidates)
        by_id = {r["neuron_id"]: r for r in result}
        assert by_id[2]["tag_affinity_depth"] == 1

    def test_seed_has_no_depth(self, depth2_db):
        """Verify seed neurons have tag_affinity_depth=None."""
        candidates = [_make_direct_candidate(1)]
        result = apply_tag_affinity(depth2_db, candidates)
        by_id = {r["neuron_id"]: r for r in result}
        assert by_id[1]["tag_affinity_depth"] is None

    def test_depth2_weight_is_multiplicative(self, depth2_db):
        """Verify depth=2 score = hop1_score × hop2_weight.

        Neuron 2 at depth=1: score = weight(cpp) = 0.5
        Neuron 3 at depth=2: hop2_weight(architecture) = 0.5
        Expected depth=2 score = 0.5 * 0.5 = 0.25
        """
        candidates = [_make_direct_candidate(1)]
        result = apply_tag_affinity(depth2_db, candidates)
        by_id = {r["neuron_id"]: r for r in result}
        expected = 0.5 * 0.5  # hop1_score × hop2_weight
        assert abs(by_id[3]["tag_affinity_score"] - expected) < 1e-9

    def test_depth2_score_less_than_depth1(self, depth2_db):
        """Verify depth=2 scores are lower than depth=1 (multiplicative decay)."""
        candidates = [_make_direct_candidate(1)]
        result = apply_tag_affinity(depth2_db, candidates)
        by_id = {r["neuron_id"]: r for r in result}
        assert by_id[3]["tag_affinity_score"] < by_id[2]["tag_affinity_score"]

    def test_depth2_does_not_rediscover_depth1(self, depth2_db):
        """Verify depth=2 pass does not re-add neurons already found at depth=1."""
        candidates = [_make_direct_candidate(1)]
        result = apply_tag_affinity(depth2_db, candidates)
        ids = [r["neuron_id"] for r in result]
        assert ids.count(2) == 1  # neuron 2 appears only once (depth=1)

    def test_depth2_does_not_rediscover_seed(self, depth2_db):
        """Verify depth=2 pass does not re-add the seed neuron."""
        candidates = [_make_direct_candidate(1)]
        result = apply_tag_affinity(depth2_db, candidates)
        ids = [r["neuron_id"] for r in result]
        assert ids.count(1) == 1  # seed appears only once

    def test_depth2_unrelated_neuron_not_discovered(self, depth2_db):
        """Verify neuron 4 (javascript only) is NOT discovered at depth=2."""
        candidates = [_make_direct_candidate(1)]
        result = apply_tag_affinity(depth2_db, candidates)
        result_ids = {r["neuron_id"] for r in result}
        assert 4 not in result_ids

    def test_depth2_no_depth1_results_returns_no_depth2(self, migrated_conn):
        """Verify no depth=1 discoveries → no depth=2 pass."""
        conn = migrated_conn
        conn.execute("BEGIN")
        nid = _insert_neuron(conn, "isolated")
        # Give it a tag but no other neurons share it
        tid = _insert_tag(conn, "unique_only")
        _link_neuron_tag(conn, nid, tid)
        conn.execute("COMMIT")
        candidates = [_make_direct_candidate(nid)]
        result = apply_tag_affinity(conn, candidates)
        depth2 = [r for r in result if r.get("tag_affinity_depth") == 2]
        assert len(depth2) == 0

    def test_depth2_with_multiple_hop1_paths(self, migrated_conn):
        """Verify depth=2 takes the best path when multiple hop1 neurons connect.

        Neuron 1 (seed) — tags: rust
        Neuron 2 (hop1, strong) — tags: rust, systems → score via rust=0.333
        Neuron 3 (hop1, weak)  — tags: rust, systems → score via rust=0.333
        Neuron 4 (hop2)        — tags: systems

        Both neurons 2 and 3 connect to neuron 4 via "systems".
        Best path: max(0.333 * weight(systems), 0.333 * weight(systems))
        """
        conn = migrated_conn
        conn.execute("BEGIN")
        for i in range(1, 5):
            _insert_neuron(conn, f"neuron {i}")
        t_rust = _insert_tag(conn, "rust")
        t_sys = _insert_tag(conn, "systems")
        _link_neuron_tag(conn, 1, t_rust)
        _link_neuron_tag(conn, 2, t_rust)
        _link_neuron_tag(conn, 2, t_sys)
        _link_neuron_tag(conn, 3, t_rust)
        _link_neuron_tag(conn, 3, t_sys)
        _link_neuron_tag(conn, 4, t_sys)
        conn.execute("COMMIT")

        candidates = [_make_direct_candidate(1)]
        result = apply_tag_affinity(conn, candidates)
        by_id = {r["neuron_id"]: r for r in result}
        assert 4 in by_id
        assert by_id[4]["tag_affinity_depth"] == 2
        assert by_id[4]["tag_affinity_score"] > 0
