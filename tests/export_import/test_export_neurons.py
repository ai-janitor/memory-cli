# =============================================================================
# Module: test_export_neurons.py
# Purpose: Test the neuron export pipeline — querying with tag filters,
#   resolving tags/attrs to names, filtering edges to the export set, and
#   optionally including vector embeddings.
# Rationale: Export is the primary data-out path. Bugs here mean data loss
#   (missing neurons), data leaks (extra neurons), or broken imports
#   (malformed output). Edge filtering is especially critical — edges to
#   neurons outside the export set must be silently dropped.
# Responsibility:
#   - Verify export with no filters returns all neurons
#   - Verify --tags AND filter returns only neurons with ALL specified tags
#   - Verify --tags-any OR filter returns neurons with ANY specified tags
#   - Verify tags_and and tags_any are mutually exclusive
#   - Verify tags are exported as name strings, not integer IDs
#   - Verify attributes are exported as key-value strings
#   - Verify edges are included only when BOTH endpoints are in export set
#   - Verify edges to outside neurons are silently dropped
#   - Verify --include-vectors adds vector and vector_model per neuron
#   - Verify export without --include-vectors omits vector fields
#   - Verify empty result (zero neurons) is valid, not an error
#   - Verify ordering is by created_at ascending
# Organization:
#   1. Imports and fixtures
#   2. Fixture: in-memory DB with sample neurons, edges, tags, attrs, vectors
#   3. Tests: no-filter export
#   4. Tests: AND tag filter
#   5. Tests: OR tag filter
#   6. Tests: mutually exclusive filter error
#   7. Tests: tag/attr name resolution
#   8. Tests: edge filtering
#   9. Tests: vector inclusion
#   10. Tests: empty export
#   11. Tests: ordering
# =============================================================================

from __future__ import annotations

import sqlite3
import struct
import time
from typing import Any, Dict, List

import pytest

from memory_cli.export_import.export_neurons_tags_edges_to_json import export_neurons


# --- Fixtures ---


sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec package required for export neuron tests (vec0 virtual table)",
)


def _apply_migration(conn: sqlite3.Connection) -> None:
    """Apply the baseline migration to an in-memory DB (with sqlite-vec extension)."""
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations import MIGRATION_REGISTRY
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    MIGRATION_REGISTRY[1](conn)
    conn.execute("COMMIT")


def _insert_neuron(conn: sqlite3.Connection, content: str, project: str = "test-project",
                   created_at_ms: int = None, source: str = None) -> int:
    """Insert a neuron and return its ID."""
    if created_at_ms is None:
        created_at_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, source, status) "
        "VALUES (?, ?, ?, ?, ?, 'active')",
        (content, created_at_ms, created_at_ms, project, source),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _add_tag(conn: sqlite3.Connection, neuron_id: int, tag_name: str) -> None:
    """Add a tag to a neuron, creating the tag if needed."""
    now_ms = int(time.time() * 1000)
    conn.execute("INSERT OR IGNORE INTO tags (name, created_at) VALUES (?, ?)", (tag_name, now_ms))
    tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()[0]
    conn.execute("INSERT OR IGNORE INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)", (neuron_id, tag_id))


def _add_attr(conn: sqlite3.Connection, neuron_id: int, key: str, value: str) -> None:
    """Add an attribute to a neuron, creating the attr_key if needed."""
    now_ms = int(time.time() * 1000)
    conn.execute("INSERT OR IGNORE INTO attr_keys (name, created_at) VALUES (?, ?)", (key, now_ms))
    key_id = conn.execute("SELECT id FROM attr_keys WHERE name = ?", (key,)).fetchone()[0]
    conn.execute(
        "INSERT OR REPLACE INTO neuron_attrs (neuron_id, attr_key_id, value) VALUES (?, ?, ?)",
        (neuron_id, key_id, value),
    )


def _add_vector(conn: sqlite3.Connection, neuron_id: int, dims: int = 768) -> List[float]:
    """Add a fake vector to a neuron."""
    vector = [float(i % 100) / 100.0 for i in range(dims)]
    blob = struct.pack(f"<{dims}f", *vector)
    conn.execute(
        "INSERT OR REPLACE INTO neurons_vec (neuron_id, embedding) VALUES (?, ?)",
        (neuron_id, blob),
    )
    return vector


@pytest.fixture
def sample_db():
    """Create an in-memory DB with sample neurons, edges, tags, attrs, vectors.

    Setup:
    - 3 neurons with staggered created_at for ordering tests:
      - neuron_c: oldest, tags: [type:note]
      - neuron_a: middle, tags: [project:test, type:note], attrs: {language: en}
      - neuron_b: newest, tags: [project:test, type:code], attrs: {language: py, priority: high}
    - 3 edges: a->b, b->c, a->c
    - Vectors for neuron_a and neuron_b
    - Meta: vector_model, vector_dimensions
    """
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    conn = open_connection(":memory:")

    _apply_migration(conn)

    # Use distinct timestamps to control ordering
    base_ms = 1735689600000  # 2025-01-01T00:00:00Z in ms
    with conn:
        nid_c = _insert_neuron(conn, "Neuron C", created_at_ms=base_ms)
        nid_a = _insert_neuron(conn, "Neuron A", created_at_ms=base_ms + 86400000)
        nid_b = _insert_neuron(conn, "Neuron B", created_at_ms=base_ms + 172800000)

        _add_tag(conn, nid_c, "type:note")
        _add_tag(conn, nid_a, "project:test")
        _add_tag(conn, nid_a, "type:note")
        _add_tag(conn, nid_b, "project:test")
        _add_tag(conn, nid_b, "type:code")

        _add_attr(conn, nid_a, "language", "en")
        _add_attr(conn, nid_b, "language", "py")
        _add_attr(conn, nid_b, "priority", "high")

        # Insert edges
        now_ms = base_ms
        conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, weight, created_at) VALUES (?, ?, 'related', 1.0, ?)",
            (nid_a, nid_b, now_ms),
        )
        conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, weight, created_at) VALUES (?, ?, 'related', 1.0, ?)",
            (nid_b, nid_c, now_ms),
        )
        conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, weight, created_at) VALUES (?, ?, 'related', 1.0, ?)",
            (nid_a, nid_c, now_ms),
        )

        # Add vectors for nid_a and nid_b
        _add_vector(conn, nid_a)
        _add_vector(conn, nid_b)

        # Store vector config in meta
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('vector_model', 'test-model')")
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('vector_dimensions', '768')")

    yield conn, nid_a, nid_b, nid_c
    conn.close()


# --- Tests: No-filter export ---


class TestExportNoFilter:
    """Export with no tag filters should return all neurons."""

    def test_export_all_neurons_returned(self, sample_db):
        """All 3 neurons should be in the export.

        Steps:
        1. Call export_neurons(sample_db) with no filters
        2. Assert len(result["neurons"]) == 3
        """
        conn, nid_a, nid_b, nid_c = sample_db
        result = export_neurons(conn)
        assert len(result["neurons"]) == 3

    def test_export_all_edges_between_exported_neurons(self, sample_db):
        """All 3 edges should be included (all neurons are in set).

        Steps:
        1. Call export_neurons(sample_db) with no filters
        2. Assert len(result["edges"]) == 3
        """
        conn, nid_a, nid_b, nid_c = sample_db
        result = export_neurons(conn)
        assert len(result["edges"]) == 3

    def test_export_ordered_by_created_at_ascending(self, sample_db):
        """Neurons should be ordered oldest first.

        Steps:
        1. Call export_neurons(sample_db) with no filters
        2. Assert neurons[0] is oldest (nid_c), neurons[2] is newest (nid_b)
        """
        conn, nid_a, nid_b, nid_c = sample_db
        result = export_neurons(conn)
        ids = [n["id"] for n in result["neurons"]]
        assert ids[0] == nid_c
        assert ids[1] == nid_a
        assert ids[2] == nid_b


# --- Tests: AND tag filter ---


class TestExportTagsAnd:
    """Export with --tags AND filter requires ALL specified tags."""

    def test_and_filter_single_tag(self, sample_db):
        """Filter by [project:test] should return neuron_a and neuron_b.

        Steps:
        1. Call export_neurons(sample_db, tags_and=["project:test"])
        2. Assert 2 neurons returned
        3. Assert returned IDs are {nid_a, nid_b}
        """
        conn, nid_a, nid_b, nid_c = sample_db
        result = export_neurons(conn, tags_and=["project:test"])
        assert len(result["neurons"]) == 2
        ids = {n["id"] for n in result["neurons"]}
        assert ids == {nid_a, nid_b}

    def test_and_filter_multiple_tags(self, sample_db):
        """Filter by [project:test, type:note] should return only neuron_a.

        Steps:
        1. Call export_neurons(sample_db, tags_and=["project:test", "type:note"])
        2. Assert 1 neuron returned
        3. Assert returned ID is nid_a
        """
        conn, nid_a, nid_b, nid_c = sample_db
        result = export_neurons(conn, tags_and=["project:test", "type:note"])
        assert len(result["neurons"]) == 1
        assert result["neurons"][0]["id"] == nid_a

    def test_and_filter_no_match(self, sample_db):
        """Filter requiring tags no single neuron has -> empty result.

        Steps:
        1. Call export_neurons(sample_db, tags_and=["project:test", "type:note", "type:code"])
        2. Assert 0 neurons, 0 edges
        """
        conn, nid_a, nid_b, nid_c = sample_db
        result = export_neurons(conn, tags_and=["project:test", "type:note", "type:code"])
        assert result["neurons"] == []
        assert result["edges"] == []


# --- Tests: OR tag filter ---


class TestExportTagsAny:
    """Export with --tags-any OR filter requires ANY specified tag."""

    def test_any_filter_returns_union(self, sample_db):
        """Filter by [type:note, type:code] should return all 3 neurons.

        neuron_a has type:note, neuron_b has type:code, neuron_c has type:note.

        Steps:
        1. Call export_neurons(sample_db, tags_any=["type:note", "type:code"])
        2. Assert 3 neurons returned
        """
        conn, nid_a, nid_b, nid_c = sample_db
        result = export_neurons(conn, tags_any=["type:note", "type:code"])
        assert len(result["neurons"]) == 3

    def test_any_filter_single_tag(self, sample_db):
        """Filter by [type:code] should return only neuron_b.

        Steps:
        1. Call export_neurons(sample_db, tags_any=["type:code"])
        2. Assert 1 neuron returned with id nid_b
        """
        conn, nid_a, nid_b, nid_c = sample_db
        result = export_neurons(conn, tags_any=["type:code"])
        assert len(result["neurons"]) == 1
        assert result["neurons"][0]["id"] == nid_b


# --- Tests: Mutual exclusion ---


class TestExportFilterMutualExclusion:
    """tags_and and tags_any cannot both be provided."""

    def test_both_filters_raises_value_error(self, sample_db):
        """Providing both tags_and and tags_any should raise ValueError.

        Steps:
        1. Call export_neurons(sample_db, tags_and=["a"], tags_any=["b"])
        2. Assert pytest.raises(ValueError)
        """
        conn, nid_a, nid_b, nid_c = sample_db
        with pytest.raises(ValueError):
            export_neurons(conn, tags_and=["project:test"], tags_any=["type:note"])


# --- Tests: Tag/attr name resolution ---


class TestExportNameResolution:
    """Tags and attrs are exported as string names, not integer IDs."""

    def test_tags_are_strings(self, sample_db):
        """Each neuron's tags should be a list of strings.

        Steps:
        1. Export all neurons
        2. For each neuron, assert all items in tags list are str
        3. Verify tag values match expected names (e.g., "project:test")
        """
        conn, nid_a, nid_b, nid_c = sample_db
        result = export_neurons(conn)
        for neuron in result["neurons"]:
            assert isinstance(neuron["tags"], list)
            for tag in neuron["tags"]:
                assert isinstance(tag, str), f"Tag should be str, got {type(tag)}: {tag}"

        # Verify specific neuron tags
        neuron_a = next(n for n in result["neurons"] if n["id"] == nid_a)
        assert "project:test" in neuron_a["tags"]
        assert "type:note" in neuron_a["tags"]

    def test_attrs_are_string_pairs(self, sample_db):
        """Each neuron's attributes should be {str: str} dict.

        Steps:
        1. Export all neurons
        2. For each neuron, assert attributes is a dict
        3. Assert all keys and values are str instances
        4. Verify specific values (e.g., neuron_b attrs: language=py, priority=high)
        """
        conn, nid_a, nid_b, nid_c = sample_db
        result = export_neurons(conn)
        for neuron in result["neurons"]:
            assert isinstance(neuron["attributes"], dict)
            for k, v in neuron["attributes"].items():
                assert isinstance(k, str)
                assert isinstance(v, str)

        neuron_b = next(n for n in result["neurons"] if n["id"] == nid_b)
        assert neuron_b["attributes"].get("language") == "py"
        assert neuron_b["attributes"].get("priority") == "high"


# --- Tests: Edge filtering ---


class TestExportEdgeFiltering:
    """Edges are only included if BOTH endpoints are in the export set."""

    def test_edges_filtered_when_subset_exported(self, sample_db):
        """Exporting only [project:test] neurons drops edges to neuron_c.

        Steps:
        1. Export with tags_and=["project:test"] -> neuron_a, neuron_b
        2. Only edge a->b should be included (b->c and a->c dropped)
        3. Assert len(result["edges"]) == 1
        4. Assert the one edge has source and target within the export set
        """
        conn, nid_a, nid_b, nid_c = sample_db
        result = export_neurons(conn, tags_and=["project:test"])
        assert len(result["edges"]) == 1
        edge = result["edges"][0]
        assert edge["source_id"] == nid_a
        assert edge["target_id"] == nid_b

    def test_edges_silently_dropped_no_error(self, sample_db):
        """Dropped edges should not cause errors or warnings.

        Steps:
        1. Export with tags_and=["project:test"]
        2. Assert no exceptions raised
        3. Assert result is a valid dict with neurons and edges keys
        """
        conn, nid_a, nid_b, nid_c = sample_db
        result = export_neurons(conn, tags_and=["project:test"])
        assert "neurons" in result
        assert "edges" in result


# --- Tests: Vector inclusion ---


class TestExportVectorInclusion:
    """--include-vectors adds vector and vector_model to neuron dicts."""

    def test_vectors_included_when_requested(self, sample_db):
        """Neurons with vectors should have vector and vector_model fields.

        Steps:
        1. Export with include_vectors=True
        2. Find neuron_a and neuron_b in result
        3. Assert both have "vector" key with list value
        4. Assert both have "vector_model" key with str value
        5. neuron_c has no stored vector -> vector should be None or absent
        """
        conn, nid_a, nid_b, nid_c = sample_db
        result = export_neurons(conn, include_vectors=True)
        neuron_a = next(n for n in result["neurons"] if n["id"] == nid_a)
        neuron_b = next(n for n in result["neurons"] if n["id"] == nid_b)
        assert "vector" in neuron_a and neuron_a["vector"] is not None
        assert "vector_model" in neuron_a
        assert "vector" in neuron_b and neuron_b["vector"] is not None
        assert "vector_model" in neuron_b

    def test_vectors_omitted_when_not_requested(self, sample_db):
        """Without --include-vectors, vector fields should be absent.

        Steps:
        1. Export with include_vectors=False (default)
        2. For each neuron, assert "vector" key is NOT present
        3. For each neuron, assert "vector_model" key is NOT present
        """
        conn, nid_a, nid_b, nid_c = sample_db
        result = export_neurons(conn)
        for neuron in result["neurons"]:
            assert "vector" not in neuron
            assert "vector_model" not in neuron

    def test_vector_is_list_of_floats(self, sample_db):
        """Vector should be a list of 768 floats.

        Steps:
        1. Export with include_vectors=True
        2. Get vector from neuron_a
        3. Assert isinstance(vector, list)
        4. Assert len(vector) == 768
        5. Assert all(isinstance(v, float) for v in vector)
        """
        conn, nid_a, nid_b, nid_c = sample_db
        result = export_neurons(conn, include_vectors=True)
        neuron_a = next(n for n in result["neurons"] if n["id"] == nid_a)
        vector = neuron_a["vector"]
        assert isinstance(vector, list)
        assert len(vector) == 768
        assert all(isinstance(v, float) for v in vector)


# --- Tests: Empty export ---


class TestExportEmpty:
    """Exporting zero neurons is valid."""

    def test_no_match_returns_empty_lists(self, sample_db):
        """Tag filter that matches nothing -> empty neurons and edges lists.

        Steps:
        1. Export with tags_and=["nonexistent-tag"]
        2. Assert result["neurons"] == []
        3. Assert result["edges"] == []
        """
        conn, nid_a, nid_b, nid_c = sample_db
        result = export_neurons(conn, tags_and=["nonexistent-tag"])
        assert result["neurons"] == []
        assert result["edges"] == []

    def test_empty_db_returns_empty_lists(self):
        """Exporting from an empty DB -> empty neurons and edges lists.

        Steps:
        1. Create in-memory DB with schema but no data
        2. Export with no filters
        3. Assert result["neurons"] == [] and result["edges"] == []
        4. Assert no exceptions raised
        """
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        conn = open_connection(":memory:")
        _apply_migration(conn)
        try:
            result = export_neurons(conn)
            assert result["neurons"] == []
            assert result["edges"] == []
        finally:
            conn.close()
