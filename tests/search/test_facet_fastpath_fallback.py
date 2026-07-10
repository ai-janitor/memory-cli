# =============================================================================
# Module: test_facet_fastpath_fallback.py
# Purpose: Acceptance tests for MEM-FIX-0008 — facet fast-path staged
#   relaxation (AND -> OR -> recency) in _rank_facet_candidates(). Turns
#   AC-1..AC-6 (spec docs/delegations/MEM-FIX-0008.spec.md §41) red->green.
# Rationale: MEM-FIX-0007's facet fast-path ranked candidates via FTS5 MATCH
#   with implicit AND across all tokens and no fallback — a real multi-word
#   gate phrase (e.g. "verify on live path") against a facet where no single
#   row contains every token silently returned 0, even though the facet is
#   populated. This file proves the staged relaxation fixes that hole using
#   a genuine multi-word phrase (not a convenient single-word query), and
#   that the fix costs zero model loads and leaves Tier 1 / empty-query
#   behavior unchanged.
# Organization:
#   1. Fixtures (migrated in-memory DB, neuron_add-based seeding helper)
#   2. AC-1: Tier 2 OR-join — multi-word phrase, no row matches all tokens
#   3. AC-2: Tier 3 recency fallback — phrase matches zero tokens anywhere
#   4. AC-3: Tier 1 regression guard — full AND match unchanged
#   5. AC-4: no model load on any tier (spy)
#   6. AC-5: empty facet + any query -> exit 1, empty (unchanged)
#   7. AC-6: empty-query recency branch unchanged
# =============================================================================

from __future__ import annotations

from unittest.mock import patch

import pytest

from memory_cli.config import load_config
from memory_cli.search.light_search_pipeline_orchestrator import (
    light_search,
    SearchOptions,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def conn():
    """Full in-memory DB with schema, FTS5, and access-tracking columns."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as apply_v001
    from memory_cli.db.migrations.v004_add_access_tracking import apply as apply_v004
    c = open_connection(":memory:")
    load_and_verify_extensions(c)
    c.execute("BEGIN")
    apply_v001(c)
    c.execute("COMMIT")
    c.execute("BEGIN")
    apply_v004(c)
    c.execute("COMMIT")
    return c


def _add(conn, content, ntype=None, tags=None):
    """Add a neuron via the production neuron_add() path (no_embed — the
    fast-path fix must work without any embedding ever having run)."""
    from memory_cli.neuron import neuron_add
    attrs = {"type": ntype} if ntype else None
    result = neuron_add(conn, content, tags=tags, attrs=attrs, no_embed=True)
    return result["id"]


def _get_model_patch():
    """Patch target for the embedding entry point light_search calls."""
    return patch(
        "memory_cli.search.light_search_pipeline_orchestrator.get_model",
        side_effect=FileNotFoundError("model not available in tests"),
    )


# -----------------------------------------------------------------------------
# AC-1 — Tier 2 OR-join: multi-word phrase, no row matches ALL tokens but
# some rows match ONE token each -> non-empty results, exit 0.
#
# This is the exact shape of the shipped bug: a real multi-word gate phrase
# ("verify on live path") against a populated facet where NOT ALL tokens
# co-occur in any single row. A single-word or all-match query would not
# exercise the AND-fails-but-OR-succeeds path — that's the hole MEM-FIX-0007
# left open.
# -----------------------------------------------------------------------------

class TestAC1TierTwoOrJoin:
    def test_multiword_phrase_falls_back_to_or_join(self, conn):
        verify_row = _add(conn, "lesson: verify this change works", ntype="lesson")
        path_row = _add(conn, "lesson: path to the deploy target", ntype="lesson")
        unrelated = _add(conn, "lesson: totally different content here", ntype="lesson")

        options = SearchOptions(query="verify on live path", ntype="lesson")
        envelope = light_search(conn, options, config=load_config())

        ids = {r["id"] for r in envelope.results}
        assert ids, "facet has 3 rows but AND-only match would return 0 (the bug)"
        assert ids == {verify_row, path_row}
        assert unrelated not in ids
        assert envelope.exit_code == 0
        assert envelope.facet_fast is True


# -----------------------------------------------------------------------------
# AC-2 — Tier 3 recency fallback: phrase matches zero tokens anywhere in the
# facet -> recency-ranked facet rows, match_type=facet_recency, exit 0.
# -----------------------------------------------------------------------------

class TestAC2TierThreeRecencyFallback:
    def test_phrase_matching_nothing_falls_back_to_recency(self, conn):
        oldest = _add(conn, "lesson: alpha bravo charlie", ntype="lesson")
        newest = _add(conn, "lesson: delta echo foxtrot", ntype="lesson")
        conn.execute("UPDATE neurons SET created_at = 1000 WHERE id = ?", (oldest,))
        conn.execute("UPDATE neurons SET created_at = 2000 WHERE id = ?", (newest,))
        conn.commit()

        options = SearchOptions(query="zzzznomatch qqqqnotfound", ntype="lesson")
        envelope = light_search(conn, options, config=load_config())

        assert envelope.exit_code == 0
        ids = [r["id"] for r in envelope.results]
        assert ids == [newest, oldest]


# -----------------------------------------------------------------------------
# AC-3 — Tier 1 regression guard: a query that fully AND-matches a row is
# unaffected by the new tiers — identical results/order to pre-0008.
# -----------------------------------------------------------------------------

class TestAC3TierOneRegressionGuard:
    def test_full_and_match_unchanged(self, conn):
        lesson_match = _add(conn, "lesson: verify on live path today", ntype="lesson")
        lesson_no_match = _add(conn, "lesson: dump facts in briefs", ntype="lesson")

        options = SearchOptions(query="verify on live path", ntype="lesson")
        envelope = light_search(conn, options, config=load_config())

        ids = [r["id"] for r in envelope.results]
        assert ids == [lesson_match]
        assert lesson_no_match not in ids
        assert envelope.exit_code == 0


# -----------------------------------------------------------------------------
# AC-4 — zero model loads on any tier (Tier 1, Tier 2, Tier 3 all covered).
# -----------------------------------------------------------------------------

class TestAC4NoModelLoadOnAnyTier:
    def test_tier2_or_join_never_loads_model(self, conn):
        _add(conn, "lesson: verify this change works", ntype="lesson")
        _add(conn, "lesson: path to the deploy target", ntype="lesson")

        with patch(
            "memory_cli.search.light_search_pipeline_orchestrator.get_model"
        ) as mock_get_model:
            options = SearchOptions(query="verify on live path", ntype="lesson")
            light_search(conn, options, config=load_config())

        mock_get_model.assert_not_called()

    def test_tier3_recency_fallback_never_loads_model(self, conn):
        _add(conn, "lesson: alpha bravo charlie", ntype="lesson")

        with patch(
            "memory_cli.search.light_search_pipeline_orchestrator.get_model"
        ) as mock_get_model:
            options = SearchOptions(query="zzzznomatch qqqqnotfound", ntype="lesson")
            light_search(conn, options, config=load_config())

        mock_get_model.assert_not_called()

    def test_tier1_and_match_never_loads_model(self, conn):
        _add(conn, "lesson: verify on live path today", ntype="lesson")

        with patch(
            "memory_cli.search.light_search_pipeline_orchestrator.get_model"
        ) as mock_get_model:
            options = SearchOptions(query="verify on live path", ntype="lesson")
            light_search(conn, options, config=load_config())

        mock_get_model.assert_not_called()


# -----------------------------------------------------------------------------
# AC-5 — empty facet (no candidate rows) + any query -> exit 1, empty.
# Unchanged behavior — the relaxation tiers never run against an empty
# candidate set (short-circuited before _rank_facet_candidates is called).
# -----------------------------------------------------------------------------

class TestAC5EmptyFacetUnchanged:
    def test_empty_facet_returns_exit_1(self, conn):
        _add(conn, "memory: something unrelated", ntype="memory")

        options = SearchOptions(query="verify on live path", ntype="lesson")
        envelope = light_search(conn, options, config=load_config())

        assert envelope.results == []
        assert envelope.exit_code == 1
        assert envelope.facet_fast is True


# -----------------------------------------------------------------------------
# AC-6 — empty-query recency branch unchanged (pre-0008 AC-6 of MEM-FIX-0007,
# pinned again here as a regression guard for the refactor).
# -----------------------------------------------------------------------------

class TestAC6EmptyQueryRecencyUnchanged:
    def test_empty_query_type_scoped_ranks_by_recency(self, conn):
        oldest = _add(conn, "lesson oldest", ntype="lesson")
        middle = _add(conn, "lesson middle", ntype="lesson")
        newest = _add(conn, "lesson newest", ntype="lesson")
        conn.execute("UPDATE neurons SET created_at = 1000 WHERE id = ?", (oldest,))
        conn.execute("UPDATE neurons SET created_at = 2000 WHERE id = ?", (middle,))
        conn.execute("UPDATE neurons SET created_at = 3000 WHERE id = ?", (newest,))
        conn.commit()

        with patch(
            "memory_cli.search.light_search_pipeline_orchestrator.get_model"
        ) as mock_get_model:
            options = SearchOptions(query="", ntype="lesson")
            envelope = light_search(conn, options, config=load_config())

        mock_get_model.assert_not_called()
        assert envelope.exit_code == 0
        assert [r["id"] for r in envelope.results] == [newest, middle, oldest]
