# =============================================================================
# Module: test_neuron_list.py
# Purpose: Test filtered, paginated neuron listing — AND/OR tag filters,
#   status filter, project filter, pagination, empty results, and combined
#   filter scenarios.
# Rationale: List is the primary discovery command and its dynamic SQL
#   construction with multiple optional filters is the most error-prone
#   part. Each filter and filter combination needs explicit test coverage
#   to catch WHERE clause construction bugs.
# Responsibility:
#   - Test unfiltered list returns all active neurons
#   - Test AND tag filter (must have ALL tags)
#   - Test OR tag filter (must have ANY tag)
#   - Test combined AND+OR (must satisfy both)
#   - Test status filter (active, archived, all)
#   - Test project filter
#   - Test pagination (limit, offset)
#   - Test empty results return empty list (not error)
#   - Test non-existent tag in AND filter -> empty results
#   - Test non-existent tag in OR filter -> filtered out
#   - Test invalid status raises ValueError
# Organization:
#   1. Imports and fixtures
#   2. Unfiltered list tests
#   3. AND tag filter tests
#   4. OR tag filter tests
#   5. Combined filter tests
#   6. Status filter tests
#   7. Project filter tests
#   8. Pagination tests
#   9. Edge case tests
# =============================================================================

from __future__ import annotations

import time
import pytest

sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec required for full schema (vec0 table)"
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """In-memory SQLite with full migrated schema including neurons_vec."""
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
    yield conn
    conn.close()


def _insert_neuron(conn, content="test", project="proj-a", status="active",
                   tags=None, created_at=None):
    """Helper: insert a neuron directly for test setup. Returns neuron_id."""
    from memory_cli.registries import tag_autocreate

    now_ms = created_at if created_at is not None else int(time.time() * 1000)
    cursor = conn.execute(
        """INSERT INTO neurons (content, created_at, updated_at, project, source, status)
           VALUES (?, ?, ?, ?, NULL, ?)""",
        (content, now_ms, now_ms, project, status)
    )
    neuron_id = cursor.lastrowid

    for tag_name in (tags or []):
        tag_id = tag_autocreate(conn, tag_name)
        conn.execute(
            "INSERT OR IGNORE INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)",
            (neuron_id, tag_id)
        )

    conn.commit()
    return neuron_id


@pytest.fixture
def populated_db(migrated_conn):
    """Database with multiple neurons, various tags, projects, statuses.

    Creates test dataset:
    - Neuron 1: tags=[python, ai], project=proj-a, status=active
    - Neuron 2: tags=[python, web], project=proj-a, status=active
    - Neuron 3: tags=[ai, ml], project=proj-b, status=active
    - Neuron 4: tags=[python], project=proj-a, status=archived
    - Neuron 5: tags=[web], project=proj-b, status=active
    """
    base_time = int(time.time() * 1000)

    ids = {}
    ids["n1"] = _insert_neuron(migrated_conn, "Neuron 1", "proj-a", "active",
                                ["python", "ai"], created_at=base_time + 1000)
    ids["n2"] = _insert_neuron(migrated_conn, "Neuron 2", "proj-a", "active",
                                ["python", "web"], created_at=base_time + 2000)
    ids["n3"] = _insert_neuron(migrated_conn, "Neuron 3", "proj-b", "active",
                                ["ai", "ml"], created_at=base_time + 3000)
    ids["n4"] = _insert_neuron(migrated_conn, "Neuron 4", "proj-a", "archived",
                                ["python"], created_at=base_time + 4000)
    ids["n5"] = _insert_neuron(migrated_conn, "Neuron 5", "proj-b", "active",
                                ["web"], created_at=base_time + 5000)
    return migrated_conn, ids


# -----------------------------------------------------------------------------
# Unfiltered list tests
# -----------------------------------------------------------------------------

class TestNeuronListUnfiltered:
    """Test listing without any filters."""

    def test_list_default_returns_active_neurons(self, populated_db):
        """Verify default list returns only active neurons.

        Default status filter is 'active'.
        """
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn)
        result_ids = {n["id"] for n in results}

        assert ids["n1"] in result_ids
        assert ids["n2"] in result_ids
        assert ids["n3"] in result_ids
        assert ids["n5"] in result_ids
        # Archived neuron should NOT be in default results
        assert ids["n4"] not in result_ids

    def test_list_ordered_most_recent_first(self, populated_db):
        """Verify results are ordered by created_at DESC."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, status="all")
        timestamps = [n["created_at"] for n in results]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_list_returns_hydrated_records(self, populated_db):
        """Verify each result is a fully hydrated neuron dict."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn)
        for n in results:
            assert "tags" in n
            assert "attrs" in n
            assert isinstance(n["tags"], list)
            assert isinstance(n["attrs"], dict)


# -----------------------------------------------------------------------------
# AND tag filter tests
# -----------------------------------------------------------------------------

class TestNeuronListAndFilter:
    """Test AND tag filter (--tags) — neurons must have ALL specified tags."""

    def test_and_single_tag(self, populated_db):
        """Filter by one tag — returns neurons with that tag."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, tags_and=["python"])
        result_ids = {n["id"] for n in results}

        # n1 and n2 have python (active); n4 has python but archived
        assert ids["n1"] in result_ids
        assert ids["n2"] in result_ids
        assert ids["n3"] not in result_ids  # no python tag

    def test_and_multiple_tags(self, populated_db):
        """Filter by multiple tags — returns only neurons with ALL tags.

        e.g., --tags python,ai -> only neurons with BOTH python AND ai.
        """
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, tags_and=["python", "ai"])
        result_ids = {n["id"] for n in results}

        # Only n1 has both python AND ai
        assert ids["n1"] in result_ids
        assert ids["n2"] not in result_ids  # python only, no ai
        assert ids["n3"] not in result_ids  # ai only, no python

    def test_and_nonexistent_tag_returns_empty(self, populated_db):
        """AND filter with non-existent tag returns empty list.

        If any AND tag doesn't exist, no neuron can satisfy the filter.
        """
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, tags_and=["nonexistent-tag-xyz"])
        assert results == []


# -----------------------------------------------------------------------------
# OR tag filter tests
# -----------------------------------------------------------------------------

class TestNeuronListOrFilter:
    """Test OR tag filter (--tags-any) — neurons must have ANY specified tag."""

    def test_or_single_tag(self, populated_db):
        """Filter by one tag — same as AND for single tag."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, tags_any=["ml"])
        result_ids = {n["id"] for n in results}
        assert ids["n3"] in result_ids

    def test_or_multiple_tags(self, populated_db):
        """Filter by multiple tags — returns neurons with ANY of the tags.

        e.g., --tags-any python,ml -> neurons with python OR ml (or both).
        """
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, tags_any=["python", "ml"])
        result_ids = {n["id"] for n in results}

        # n1 has python, n2 has python, n3 has ml
        assert ids["n1"] in result_ids
        assert ids["n2"] in result_ids
        assert ids["n3"] in result_ids

    def test_or_all_nonexistent_returns_empty(self, populated_db):
        """OR filter where all tags are non-existent returns empty list."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, tags_any=["nonexistent-1", "nonexistent-2"])
        assert results == []

    def test_or_some_nonexistent_still_works(self, populated_db):
        """OR filter with mix of existing and non-existent tags works.

        Non-existent tags are filtered out, remaining tags used for query.
        """
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, tags_any=["ml", "nonexistent-xyz"])
        result_ids = {n["id"] for n in results}
        assert ids["n3"] in result_ids  # has ml


# -----------------------------------------------------------------------------
# Combined filter tests
# -----------------------------------------------------------------------------

class TestNeuronListCombinedFilters:
    """Test combining multiple filter types."""

    def test_and_plus_or_filters(self, populated_db):
        """Combine --tags and --tags-any — must satisfy BOTH.

        e.g., --tags python --tags-any ai,web
        -> neurons with python AND (ai OR web)
        """
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, tags_and=["python"], tags_any=["ai", "web"])
        result_ids = {n["id"] for n in results}

        # n1 has python AND ai -> YES
        # n2 has python AND web -> YES
        # n3 has ai but no python -> NO
        assert ids["n1"] in result_ids
        assert ids["n2"] in result_ids
        assert ids["n3"] not in result_ids

    def test_tags_and_project_filter(self, populated_db):
        """Combine tag filter with project filter."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, tags_and=["python"], project="proj-a")
        result_ids = {n["id"] for n in results}

        assert ids["n1"] in result_ids
        assert ids["n2"] in result_ids
        assert ids["n3"] not in result_ids  # wrong project

    def test_tags_and_status_filter(self, populated_db):
        """Combine tag filter with status filter."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, tags_and=["python"], status="archived")
        result_ids = {n["id"] for n in results}

        # Only n4 is archived with python tag
        assert ids["n4"] in result_ids
        assert ids["n1"] not in result_ids  # active, not archived


# -----------------------------------------------------------------------------
# Status filter tests
# -----------------------------------------------------------------------------

class TestNeuronListStatusFilter:
    """Test status filter options."""

    def test_status_active_default(self, populated_db):
        """Verify default status='active' excludes archived neurons."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, status="active")
        result_ids = {n["id"] for n in results}
        assert ids["n4"] not in result_ids  # archived

    def test_status_archived(self, populated_db):
        """Verify status='archived' returns only archived neurons."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, status="archived")
        result_ids = {n["id"] for n in results}
        assert ids["n4"] in result_ids
        assert ids["n1"] not in result_ids
        assert ids["n2"] not in result_ids

    def test_status_all(self, populated_db):
        """Verify status='all' returns both active and archived neurons."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, status="all")
        result_ids = {n["id"] for n in results}
        assert ids["n1"] in result_ids
        assert ids["n4"] in result_ids

    def test_invalid_status_raises_error(self, migrated_conn):
        """Verify invalid status value raises ValueError."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        with pytest.raises(ValueError):
            neuron_list(migrated_conn, status="invalid_status")


# -----------------------------------------------------------------------------
# Project filter tests
# -----------------------------------------------------------------------------

class TestNeuronListProjectFilter:
    """Test project filter."""

    def test_filter_by_project(self, populated_db):
        """Verify --project returns only neurons from that project."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, project="proj-b")
        result_ids = {n["id"] for n in results}

        assert ids["n3"] in result_ids
        assert ids["n5"] in result_ids
        assert ids["n1"] not in result_ids  # proj-a
        assert ids["n2"] not in result_ids  # proj-a

    def test_filter_by_nonexistent_project_returns_empty(self, populated_db):
        """Verify filtering by non-existent project returns empty list."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, project="nonexistent-project-xyz")
        assert results == []


# -----------------------------------------------------------------------------
# Pagination tests
# -----------------------------------------------------------------------------

class TestNeuronListPagination:
    """Test limit and offset pagination."""

    def test_limit_restricts_results(self, populated_db):
        """Verify --limit N returns at most N results."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, status="all", limit=2)
        assert len(results) <= 2

    def test_offset_skips_results(self, populated_db):
        """Verify --offset M skips the first M results."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        all_results = neuron_list(conn, status="all", limit=100)
        offset_results = neuron_list(conn, status="all", limit=100, offset=2)

        # offset_results should skip first 2
        assert len(offset_results) == len(all_results) - 2
        assert all_results[0]["id"] not in {n["id"] for n in offset_results}
        assert all_results[1]["id"] not in {n["id"] for n in offset_results}

    def test_limit_and_offset_together(self, populated_db):
        """Verify pagination with both limit and offset."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, status="all", limit=2, offset=1)
        assert len(results) <= 2

    def test_offset_beyond_results_returns_empty(self, populated_db):
        """Verify large offset returns empty list (not error)."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, status="all", limit=50, offset=10000)
        assert results == []


# -----------------------------------------------------------------------------
# Edge case tests
# -----------------------------------------------------------------------------

class TestNeuronListEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_database_returns_empty_list(self, migrated_conn):
        """Verify listing on empty DB returns [] (exit 0, not exit 1)."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        results = neuron_list(migrated_conn)
        assert results == []

    def test_all_filtered_out_returns_empty_list(self, populated_db):
        """Verify when all neurons are filtered out, returns []."""
        from memory_cli.neuron.neuron_list_filtered_paginated import neuron_list

        conn, ids = populated_db
        results = neuron_list(conn, tags_and=["python", "ml"])  # no neuron has both
        assert results == []
