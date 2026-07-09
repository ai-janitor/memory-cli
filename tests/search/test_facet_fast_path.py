# =============================================================================
# Module: test_facet_fast_path.py
# Purpose: Acceptance tests for MEM-FIX-0007 — facet-scoped search fast-path.
#   Turns AC-1..AC-7 (spec docs/delegations/MEM-FIX-0007.spec.md §5) red→green.
# Rationale: BUG-1 (--type/--tag silently dropped) + BUG-2 (every facet query
#   pays full embed) are fixed by resolving candidates via the existing
#   attr/tag indexes and skipping embed+vector+activation when the query is
#   facet-scoped (no --semantic opt-out). This file proves: (a) the filter is
#   now correct, (b) the fast-path never touches get_model(), (c) the
#   non-facet full pipeline is untouched (INV-A), (d) --semantic opts back in.
# Organization:
#   1. Fixtures (migrated in-memory DB, neuron_add-based seeding helper)
#   2. AC-1: --type filter correctness
#   3. AC-2: no model load for --type search
#   4. AC-3: --tag facet, AND/OR mode
#   5. AC-4: --type + --tag intersection
#   6. AC-5: INV-A guard — non-facet search still embeds
#   7. AC-6: INV-C — empty query + --type ranks by recency, exit 0
#   8. AC-7: --semantic opts a facet query back into the full pipeline
#   9. Bonus: handle_search CLI wiring proof (BUG-1 — flags were dropped)
# =============================================================================

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

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
# AC-1 — --type filter correctness (was silently ignored)
# -----------------------------------------------------------------------------

class TestAC1TypeFilterCorrectness:
    def test_type_filter_returns_only_matching_type(self, conn):
        lesson_match = _add(conn, "lesson: verify on live path", ntype="lesson")
        lesson_no_match = _add(conn, "lesson: dump facts in briefs", ntype="lesson")
        memory_match = _add(conn, "random build note about verify verbs", ntype="memory")

        options = SearchOptions(query="verify", ntype="lesson")
        envelope = light_search(conn, options)

        ids = {r["id"] for r in envelope.results}
        assert ids == {lesson_match}
        assert lesson_no_match not in ids
        assert memory_match not in ids
        assert envelope.exit_code == 0


# -----------------------------------------------------------------------------
# AC-2 — facet-scoped search never loads the embedding model
# -----------------------------------------------------------------------------

class TestAC2NoModelLoad:
    def test_type_scoped_search_does_not_call_get_model(self, conn):
        _add(conn, "lesson: verify on live path", ntype="lesson")

        with patch(
            "memory_cli.search.light_search_pipeline_orchestrator.get_model"
        ) as mock_get_model:
            options = SearchOptions(query="verify", ntype="lesson")
            envelope = light_search(conn, options)

        mock_get_model.assert_not_called()
        assert envelope.facet_fast is True
        assert envelope.exit_code == 0


# -----------------------------------------------------------------------------
# AC-3 — --tag facet, AND/OR mode
# -----------------------------------------------------------------------------

class TestAC3TagFacet:
    def test_and_mode_requires_all_tags(self, conn):
        both = _add(conn, "n1 has both tags", tags=["urgent", "review"])
        urgent_only = _add(conn, "n2 has urgent only", tags=["urgent"])
        review_only = _add(conn, "n3 has review only", tags=["review"])

        options = SearchOptions(query="", tags=["urgent", "review"], tag_mode="AND")
        envelope = light_search(conn, options)

        ids = {r["id"] for r in envelope.results}
        assert ids == {both}
        assert urgent_only not in ids
        assert review_only not in ids

    def test_or_mode_requires_any_tag(self, conn):
        both = _add(conn, "n1 has both tags", tags=["urgent", "review"])
        urgent_only = _add(conn, "n2 has urgent only", tags=["urgent"])
        review_only = _add(conn, "n3 has review only", tags=["review"])
        neither = _add(conn, "n4 has neither tag", tags=["other"])

        options = SearchOptions(query="", tags=["urgent", "review"], tag_mode="OR")
        envelope = light_search(conn, options)

        ids = {r["id"] for r in envelope.results}
        assert ids == {both, urgent_only, review_only}
        assert neither not in ids


# -----------------------------------------------------------------------------
# AC-4 — --type + --tag = intersection
# -----------------------------------------------------------------------------

class TestAC4TypeAndTagIntersection:
    def test_both_facets_intersect(self, conn):
        lesson_urgent = _add(conn, "lesson urgent one", ntype="lesson", tags=["urgent"])
        lesson_other = _add(conn, "lesson not urgent", ntype="lesson", tags=["other"])
        memory_urgent = _add(conn, "memory urgent one", ntype="memory", tags=["urgent"])

        options = SearchOptions(query="", ntype="lesson", tags=["urgent"])
        envelope = light_search(conn, options)

        ids = {r["id"] for r in envelope.results}
        assert ids == {lesson_urgent}
        assert lesson_other not in ids
        assert memory_urgent not in ids


# -----------------------------------------------------------------------------
# AC-5 — INV-A guard: non-facet search still runs the full pipeline
# -----------------------------------------------------------------------------

class TestAC5NonFacetStillEmbeds:
    def test_plain_search_still_calls_get_model(self, conn):
        _add(conn, "python programming tutorial")

        with _get_model_patch() as mock_get_model:
            options = SearchOptions(query="python", fan_out_depth=0)
            envelope = light_search(conn, options)

        mock_get_model.assert_called()
        assert envelope.facet_fast is False


# -----------------------------------------------------------------------------
# AC-6 — INV-C: empty query + --type ranks by recency, exit 0
# -----------------------------------------------------------------------------

class TestAC6EmptyQueryRecency:
    def test_empty_query_type_scoped_ranks_by_recency(self, conn):
        oldest = _add(conn, "lesson oldest", ntype="lesson")
        middle = _add(conn, "lesson middle", ntype="lesson")
        newest = _add(conn, "lesson newest", ntype="lesson")
        # Force deterministic created_at ordering (insert order alone isn't
        # a timing guarantee under sub-ms test execution).
        conn.execute("UPDATE neurons SET created_at = 1000 WHERE id = ?", (oldest,))
        conn.execute("UPDATE neurons SET created_at = 2000 WHERE id = ?", (middle,))
        conn.execute("UPDATE neurons SET created_at = 3000 WHERE id = ?", (newest,))
        conn.commit()

        with patch(
            "memory_cli.search.light_search_pipeline_orchestrator.get_model"
        ) as mock_get_model:
            options = SearchOptions(query="", ntype="lesson")
            envelope = light_search(conn, options)

        mock_get_model.assert_not_called()
        assert envelope.exit_code == 0
        assert [r["id"] for r in envelope.results] == [newest, middle, oldest]


# -----------------------------------------------------------------------------
# AC-7 — --semantic opts a facet-scoped query back into the full pipeline
# -----------------------------------------------------------------------------

class TestAC7SemanticOptOut:
    def test_semantic_true_forces_full_pipeline(self, conn):
        _add(conn, "lesson: verify on live path", ntype="lesson")

        with _get_model_patch() as mock_get_model:
            options = SearchOptions(query="verify", ntype="lesson", semantic=True, fan_out_depth=0)
            envelope = light_search(conn, options)

        mock_get_model.assert_called()
        assert envelope.facet_fast is False


# -----------------------------------------------------------------------------
# Bonus — CLI wiring proof: handle_search no longer drops --type/--tag/--semantic
# (BUG-1). Not one of the 7 counted ACs but pins the actual reported bug.
# -----------------------------------------------------------------------------

class TestHandleSearchWiresFacetFlags:
    def test_cli_type_flag_is_no_longer_a_no_op(self):
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_search
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_sqlite_vec
        from memory_cli.db import run_pending_migrations, read_schema_version
        from memory_cli.neuron import neuron_add
        from types import SimpleNamespace
        from unittest.mock import patch as _patch

        db_conn = open_connection(":memory:")
        load_sqlite_vec(db_conn)
        v = read_schema_version(db_conn)
        if v < 4:
            run_pending_migrations(db_conn, v, 4)

        neuron_add(db_conn, "lesson: verify on live path", attrs={"type": "lesson"}, no_embed=True)
        neuron_add(db_conn, "random build note about verify verbs", attrs={"type": "memory"}, no_embed=True)

        flags = SimpleNamespace(config=None, db=None, global_only=False, format="json")
        dummy_config = object()
        with _patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections_with_config",
            return_value=[(db_conn, dummy_config, "LOCAL")],
        ):
            result = handle_search(["verify", "--type", "lesson"], flags)

        assert result.status == "ok"
        assert len(result.data) == 1
        assert "lesson" in result.data[0]["content"]

        db_conn.close()
