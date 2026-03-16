# =============================================================================
# Module: test_consolidation_orchestrator.py
# Purpose: Test consolidation orchestrator — find unconsolidated neurons,
#   single/batch consolidation, sub-neuron creation, edge wiring, idempotency.
# Rationale: The orchestrator coordinates multiple subsystems (extraction,
#   neuron creation, edge wiring, attr setting). Each step and failure mode
#   needs explicit coverage to ensure robustness and idempotency.
# Organization:
#   1. Imports and fixtures
#   2. TestFindUnconsolidatedNeurons — query logic
#   3. TestIsConsolidated — idempotency check
#   4. TestConsolidateNeuron — single neuron consolidation
#   5. TestConsolidateAll — batch consolidation
#   6. TestCreateSubNeuronsAndEdges — sub-neuron and edge creation
#   7. TestSetConsolidatedTimestamp — timestamp marking
# =============================================================================

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from memory_cli.ingestion.haiku_extraction_entities_facts_rels import (
    ExtractedEntity,
    ExtractedFact,
    ExtractedRelationship,
    ExtractionResult,
)
from memory_cli.ingestion.consolidation_orchestrator import (
    EXTRACTED_EDGE_WEIGHT,
    ConsolidationResult,
    consolidate_neuron,
    consolidate_all,
    find_unconsolidated_neurons,
    _is_consolidated,
    _create_sub_neurons_and_edges,
    _set_consolidated_timestamp,
)


# ---------------------------------------------------------------------------
# Helpers — in-memory SQLite with full schema for integration-style tests
# ---------------------------------------------------------------------------
def _make_db() -> sqlite3.Connection:
    """Create an in-memory SQLite DB with the required tables for testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
        CREATE TABLE neurons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL CHECK(length(content) > 0),
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            project TEXT NOT NULL,
            source TEXT,
            embedding_updated_at INTEGER,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'archived'))
        );
        CREATE TABLE edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL REFERENCES neurons(id) ON DELETE CASCADE,
            target_id INTEGER NOT NULL REFERENCES neurons(id) ON DELETE CASCADE,
            reason TEXT NOT NULL CHECK(length(reason) > 0),
            weight REAL NOT NULL DEFAULT 1.0 CHECK(weight > 0),
            created_at INTEGER NOT NULL
        );
        CREATE TABLE tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE neuron_tags (
            neuron_id INTEGER NOT NULL REFERENCES neurons(id),
            tag_id INTEGER NOT NULL REFERENCES tags(id),
            PRIMARY KEY (neuron_id, tag_id)
        );
        CREATE TABLE attr_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE neuron_attrs (
            neuron_id INTEGER NOT NULL REFERENCES neurons(id),
            attr_key_id INTEGER NOT NULL REFERENCES attr_keys(id),
            value TEXT NOT NULL,
            PRIMARY KEY (neuron_id, attr_key_id)
        );
        CREATE TABLE meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS neurons_fts USING fts5(
            content, tags_blob, content='neurons', content_rowid='id'
        );
    """)
    return conn


def _insert_neuron(conn: sqlite3.Connection, content: str, status: str = "active") -> int:
    """Insert a minimal neuron and return its ID."""
    import time
    now_ms = int(time.time() * 1000)
    cursor = conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) VALUES (?, ?, ?, 'test', ?)",
        (content, now_ms, now_ms, status),
    )
    conn.commit()
    return cursor.lastrowid


def _set_attr(conn: sqlite3.Connection, neuron_id: int, key: str, value: str) -> None:
    """Set an attribute on a neuron."""
    import time
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT OR IGNORE INTO attr_keys (name, created_at) VALUES (?, ?)",
        (key, now_ms),
    )
    row = conn.execute("SELECT id FROM attr_keys WHERE name = ?", (key,)).fetchone()
    attr_key_id = row[0]
    conn.execute(
        "INSERT OR REPLACE INTO neuron_attrs (neuron_id, attr_key_id, value) VALUES (?, ?, ?)",
        (neuron_id, attr_key_id, value),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestFindUnconsolidatedNeurons:
    """Test find_unconsolidated_neurons() query logic."""

    def test_returns_all_active_neurons_without_consolidated_at(self):
        """3 neurons, none consolidated -> returns all 3 IDs."""
        conn = _make_db()
        id1 = _insert_neuron(conn, "content 1")
        id2 = _insert_neuron(conn, "content 2")
        id3 = _insert_neuron(conn, "content 3")

        ids = find_unconsolidated_neurons(conn)
        assert set(ids) == {id1, id2, id3}

    def test_excludes_consolidated_neurons(self):
        """2 neurons, 1 consolidated -> returns only the unconsolidated one."""
        conn = _make_db()
        id1 = _insert_neuron(conn, "content 1")
        id2 = _insert_neuron(conn, "content 2")
        _set_attr(conn, id1, "consolidated_at", "2025-01-01T00:00:00Z")

        ids = find_unconsolidated_neurons(conn)
        assert ids == [id2]

    def test_excludes_archived_neurons(self):
        """Archived neuron -> not returned."""
        conn = _make_db()
        _insert_neuron(conn, "active content")
        _insert_neuron(conn, "archived content", status="archived")

        ids = find_unconsolidated_neurons(conn)
        assert len(ids) == 1

    def test_limit_parameter(self):
        """limit=2 with 5 neurons -> returns only 2."""
        conn = _make_db()
        for i in range(5):
            _insert_neuron(conn, f"content {i}")

        ids = find_unconsolidated_neurons(conn, limit=2)
        assert len(ids) == 2

    def test_empty_database(self):
        """No neurons -> returns empty list."""
        conn = _make_db()
        ids = find_unconsolidated_neurons(conn)
        assert ids == []


class TestIsConsolidated:
    """Test _is_consolidated() check."""

    def test_returns_false_for_unconsolidated(self):
        """Neuron without consolidated_at attr -> False."""
        conn = _make_db()
        nid = _insert_neuron(conn, "content")
        assert _is_consolidated(conn, nid) is False

    def test_returns_true_for_consolidated(self):
        """Neuron with consolidated_at attr -> True."""
        conn = _make_db()
        nid = _insert_neuron(conn, "content")
        _set_attr(conn, nid, "consolidated_at", "2025-01-01T00:00:00Z")
        assert _is_consolidated(conn, nid) is True


class TestConsolidateNeuron:
    """Test consolidate_neuron() single neuron consolidation."""

    def test_skips_already_consolidated_neuron(self):
        """Neuron with consolidated_at -> skipped, neurons_skipped=1."""
        conn = _make_db()
        nid = _insert_neuron(conn, "content")
        _set_attr(conn, nid, "consolidated_at", "2025-01-01T00:00:00Z")

        with patch("memory_cli.ingestion.consolidation_extraction.consolidation_extract") as mock:
            result = consolidate_neuron(conn, nid)

        assert result.neurons_skipped == 1
        assert result.neurons_processed == 0
        mock.assert_not_called()

    def test_force_reprocesses_consolidated_neuron(self):
        """force=True -> processes even if consolidated_at exists."""
        conn = _make_db()
        nid = _insert_neuron(conn, "meaningful content about Python and databases")
        _set_attr(conn, nid, "consolidated_at", "2025-01-01T00:00:00Z")

        extraction = ExtractionResult(
            entities=[ExtractedEntity("e1", "Python")],
            facts=[],
            relationships=[],
        )

        with patch(
            "memory_cli.ingestion.consolidation_extraction.consolidation_extract",
            return_value=extraction,
        ):
            with patch(
                "memory_cli.ingestion.consolidation_orchestrator.neuron_add",
                return_value={"id": 100},
            ):
                with patch("memory_cli.ingestion.consolidation_orchestrator.edge_add"):
                    result = consolidate_neuron(conn, nid, force=True)

        assert result.neurons_processed == 1

    def test_error_for_nonexistent_neuron(self):
        """Neuron ID that doesn't exist -> error in result."""
        conn = _make_db()
        result = consolidate_neuron(conn, 9999)
        assert 9999 in result.errors

    def test_error_for_archived_neuron(self):
        """Archived neuron -> error in result."""
        conn = _make_db()
        nid = _insert_neuron(conn, "content", status="archived")
        result = consolidate_neuron(conn, nid)
        assert nid in result.errors

    def test_marks_consolidated_even_when_nothing_extracted(self):
        """Empty extraction result -> still sets consolidated_at."""
        conn = _make_db()
        nid = _insert_neuron(conn, "trivial content")

        extraction = ExtractionResult(entities=[], facts=[], relationships=[])

        with patch(
            "memory_cli.ingestion.consolidation_extraction.consolidation_extract",
            return_value=extraction,
        ):
            result = consolidate_neuron(conn, nid)

        assert result.neurons_processed == 1
        assert _is_consolidated(conn, nid)

    def test_successful_consolidation_creates_sub_neurons_and_edges(self):
        """Full extraction -> sub-neurons created, edges wired, parent marked."""
        conn = _make_db()
        nid = _insert_neuron(conn, "Python is great for working with SQLite databases")

        extraction = ExtractionResult(
            entities=[
                ExtractedEntity("e1", "Python"),
                ExtractedEntity("e2", "SQLite"),
            ],
            facts=[ExtractedFact("f1", "Python integrates well with SQLite")],
            relationships=[
                ExtractedRelationship("e1", "f1", "Python is subject of fact"),
            ],
        )

        neuron_id_counter = {"n": nid}  # start after parent

        def mock_neuron_add(c, content, tags=None, attrs=None, **kwargs):
            neuron_id_counter["n"] += 1
            new_id = neuron_id_counter["n"]
            # Insert a real neuron so edge_add can find it
            import time
            now_ms = int(time.time() * 1000)
            c.execute(
                "INSERT INTO neurons (id, content, created_at, updated_at, project, status) VALUES (?, ?, ?, ?, 'test', 'active')",
                (new_id, content, now_ms, now_ms),
            )
            c.commit()
            return {"id": new_id}

        with patch(
            "memory_cli.ingestion.consolidation_extraction.consolidation_extract",
            return_value=extraction,
        ):
            with patch(
                "memory_cli.ingestion.consolidation_orchestrator.neuron_add",
                side_effect=mock_neuron_add,
            ):
                result = consolidate_neuron(conn, nid)

        assert result.neurons_processed == 1
        assert result.sub_neurons_created == 3  # 2 entities + 1 fact
        assert result.edges_created == 4  # 3 parent->child + 1 relationship
        assert _is_consolidated(conn, nid)

    def test_extraction_error_captured_in_result(self):
        """Haiku API failure -> error in result, not an exception."""
        conn = _make_db()
        nid = _insert_neuron(conn, "content")

        from memory_cli.ingestion.consolidation_extraction import ConsolidationError

        with patch(
            "memory_cli.ingestion.consolidation_extraction.consolidation_extract",
            side_effect=ConsolidationError("extract", "API down"),
        ):
            result = consolidate_neuron(conn, nid)

        assert nid in result.errors
        assert "API down" in result.errors[nid]


class TestConsolidateAll:
    """Test consolidate_all() batch consolidation."""

    def test_processes_all_unconsolidated(self):
        """3 unconsolidated neurons -> all processed."""
        conn = _make_db()
        for i in range(3):
            _insert_neuron(conn, f"content {i}")

        extraction = ExtractionResult(entities=[], facts=[], relationships=[])

        with patch(
            "memory_cli.ingestion.consolidation_extraction.consolidation_extract",
            return_value=extraction,
        ):
            result = consolidate_all(conn)

        assert result.neurons_processed == 3

    def test_skips_already_consolidated(self):
        """2 neurons, 1 already consolidated -> 1 processed, 0 skipped in batch."""
        conn = _make_db()
        id1 = _insert_neuron(conn, "content 1")
        id2 = _insert_neuron(conn, "content 2")
        _set_attr(conn, id1, "consolidated_at", "2025-01-01T00:00:00Z")

        extraction = ExtractionResult(entities=[], facts=[], relationships=[])

        with patch(
            "memory_cli.ingestion.consolidation_extraction.consolidation_extract",
            return_value=extraction,
        ):
            result = consolidate_all(conn)

        # Only id2 found as unconsolidated, so only id2 processed
        assert result.neurons_processed == 1

    def test_limit_parameter(self):
        """limit=2 with 5 neurons -> only 2 processed."""
        conn = _make_db()
        for i in range(5):
            _insert_neuron(conn, f"content {i}")

        extraction = ExtractionResult(entities=[], facts=[], relationships=[])

        with patch(
            "memory_cli.ingestion.consolidation_extraction.consolidation_extract",
            return_value=extraction,
        ):
            result = consolidate_all(conn, limit=2)

        assert result.neurons_processed == 2

    def test_aggregates_results_across_neurons(self):
        """Results from multiple neurons are summed."""
        conn = _make_db()
        id1 = _insert_neuron(conn, "content about Python and databases")
        id2 = _insert_neuron(conn, "content about JavaScript and React")

        extraction = ExtractionResult(
            entities=[ExtractedEntity("e1", "Thing")],
            facts=[],
            relationships=[],
        )

        neuron_id_counter = {"n": max(id1, id2)}

        def mock_neuron_add(c, content, tags=None, attrs=None, **kwargs):
            neuron_id_counter["n"] += 1
            new_id = neuron_id_counter["n"]
            import time
            now_ms = int(time.time() * 1000)
            c.execute(
                "INSERT INTO neurons (id, content, created_at, updated_at, project, status) VALUES (?, ?, ?, ?, 'test', 'active')",
                (new_id, content, now_ms, now_ms),
            )
            c.commit()
            return {"id": new_id}

        with patch(
            "memory_cli.ingestion.consolidation_extraction.consolidation_extract",
            return_value=extraction,
        ):
            with patch(
                "memory_cli.ingestion.consolidation_orchestrator.neuron_add",
                side_effect=mock_neuron_add,
            ):
                result = consolidate_all(conn)

        assert result.neurons_processed == 2
        assert result.sub_neurons_created == 2  # 1 entity per neuron


class TestCreateSubNeuronsAndEdges:
    """Test _create_sub_neurons_and_edges() creation and edge wiring."""

    def test_creates_entity_sub_neuron_with_provenance(self):
        """Entity sub-neuron gets extracted_by, extraction_method, parent_neuron_id attrs."""
        conn = _make_db()
        parent_id = _insert_neuron(conn, "parent content")

        extraction = ExtractionResult(
            entities=[ExtractedEntity("e1", "Python")],
            facts=[],
            relationships=[],
        )

        captured_attrs = {}

        def mock_neuron_add(c, content, tags=None, attrs=None, **kwargs):
            captured_attrs.update(attrs or {})
            return {"id": parent_id + 1}

        with patch(
            "memory_cli.ingestion.consolidation_orchestrator.neuron_add",
            side_effect=mock_neuron_add,
        ):
            with patch("memory_cli.ingestion.consolidation_orchestrator.edge_add"):
                sub_count, edge_count, warnings = _create_sub_neurons_and_edges(
                    conn, parent_id, extraction
                )

        assert captured_attrs["extracted_by"] == "haiku"
        assert captured_attrs["extraction_method"] == "consolidation"
        assert captured_attrs["parent_neuron_id"] == str(parent_id)
        assert sub_count == 1

    def test_wires_parent_to_sub_neuron_edge_with_low_weight(self):
        """Edge from parent to sub-neuron has weight < 1.0."""
        conn = _make_db()
        parent_id = _insert_neuron(conn, "parent content")

        extraction = ExtractionResult(
            entities=[ExtractedEntity("e1", "Python")],
            facts=[],
            relationships=[],
        )

        captured_edge_calls = []

        def mock_neuron_add(c, content, tags=None, attrs=None, **kwargs):
            return {"id": parent_id + 1}

        def mock_edge_add(c, source, target, reason, weight=None):
            captured_edge_calls.append({"source": source, "target": target, "reason": reason, "weight": weight})
            return {"id": 1}

        with patch(
            "memory_cli.ingestion.consolidation_orchestrator.neuron_add",
            side_effect=mock_neuron_add,
        ):
            with patch(
                "memory_cli.ingestion.consolidation_orchestrator.edge_add",
                side_effect=mock_edge_add,
            ):
                _create_sub_neurons_and_edges(conn, parent_id, extraction)

        assert len(captured_edge_calls) == 1
        assert captured_edge_calls[0]["source"] == parent_id
        assert captured_edge_calls[0]["target"] == parent_id + 1
        assert captured_edge_calls[0]["weight"] == EXTRACTED_EDGE_WEIGHT
        assert captured_edge_calls[0]["weight"] < 1.0

    def test_sub_neurons_tagged_as_extracted(self):
        """Sub-neurons get the 'extracted' tag."""
        conn = _make_db()
        parent_id = _insert_neuron(conn, "parent content")

        extraction = ExtractionResult(
            entities=[ExtractedEntity("e1", "Python")],
            facts=[],
            relationships=[],
        )

        captured_tags = []

        def mock_neuron_add(c, content, tags=None, attrs=None, **kwargs):
            captured_tags.extend(tags or [])
            return {"id": parent_id + 1}

        with patch(
            "memory_cli.ingestion.consolidation_orchestrator.neuron_add",
            side_effect=mock_neuron_add,
        ):
            with patch("memory_cli.ingestion.consolidation_orchestrator.edge_add"):
                _create_sub_neurons_and_edges(conn, parent_id, extraction)

        assert "extracted" in captured_tags

    def test_relationship_edges_created_between_sub_neurons(self):
        """Relationships between extracted items -> edges between sub-neurons."""
        conn = _make_db()
        parent_id = _insert_neuron(conn, "parent content")

        extraction = ExtractionResult(
            entities=[
                ExtractedEntity("e1", "Python"),
                ExtractedEntity("e2", "SQLite"),
            ],
            facts=[],
            relationships=[
                ExtractedRelationship("e1", "e2", "Python uses SQLite"),
            ],
        )

        sub_id_counter = {"n": parent_id}
        captured_edge_calls = []

        def mock_neuron_add(c, content, tags=None, attrs=None, **kwargs):
            sub_id_counter["n"] += 1
            return {"id": sub_id_counter["n"]}

        def mock_edge_add(c, source, target, reason, weight=None):
            captured_edge_calls.append({"source": source, "target": target, "reason": reason, "weight": weight})
            return {"id": 1}

        with patch(
            "memory_cli.ingestion.consolidation_orchestrator.neuron_add",
            side_effect=mock_neuron_add,
        ):
            with patch(
                "memory_cli.ingestion.consolidation_orchestrator.edge_add",
                side_effect=mock_edge_add,
            ):
                sub_count, edge_count, warnings = _create_sub_neurons_and_edges(
                    conn, parent_id, extraction
                )

        # 2 parent->child edges + 1 relationship edge
        assert edge_count == 3
        # The relationship edge should be between sub-neurons, not parent
        rel_edge = captured_edge_calls[2]
        assert rel_edge["source"] == parent_id + 1  # e1's neuron ID
        assert rel_edge["target"] == parent_id + 2  # e2's neuron ID
        assert rel_edge["reason"] == "Python uses SQLite"
        assert rel_edge["weight"] == EXTRACTED_EDGE_WEIGHT

    def test_unresolvable_relationship_produces_warning(self):
        """Relationship with unknown local_id -> warning, edge not created."""
        conn = _make_db()
        parent_id = _insert_neuron(conn, "parent content")

        extraction = ExtractionResult(
            entities=[ExtractedEntity("e1", "Python")],
            facts=[],
            relationships=[
                ExtractedRelationship("e1", "e99", "references unknown"),
            ],
        )

        def mock_neuron_add(c, content, tags=None, attrs=None, **kwargs):
            return {"id": parent_id + 1}

        with patch(
            "memory_cli.ingestion.consolidation_orchestrator.neuron_add",
            side_effect=mock_neuron_add,
        ):
            with patch("memory_cli.ingestion.consolidation_orchestrator.edge_add"):
                sub_count, edge_count, warnings = _create_sub_neurons_and_edges(
                    conn, parent_id, extraction
                )

        assert any("e99" in w for w in warnings)

    def test_neuron_creation_failure_produces_warning(self):
        """Failed neuron_add -> warning, continue with other items."""
        conn = _make_db()
        parent_id = _insert_neuron(conn, "parent content")

        extraction = ExtractionResult(
            entities=[
                ExtractedEntity("e1", "Will fail"),
                ExtractedEntity("e2", "Will succeed"),
            ],
            facts=[],
            relationships=[],
        )

        call_count = {"n": 0}

        def mock_neuron_add(c, content, tags=None, attrs=None, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("creation failed")
            return {"id": parent_id + 1}

        with patch(
            "memory_cli.ingestion.consolidation_orchestrator.neuron_add",
            side_effect=mock_neuron_add,
        ):
            with patch("memory_cli.ingestion.consolidation_orchestrator.edge_add"):
                sub_count, edge_count, warnings = _create_sub_neurons_and_edges(
                    conn, parent_id, extraction
                )

        assert sub_count == 1  # only second succeeded
        assert len(warnings) >= 1
        assert any("e1" in w for w in warnings)


class TestSetConsolidatedTimestamp:
    """Test _set_consolidated_timestamp() attr setting."""

    def test_sets_consolidated_at_attribute(self):
        """After calling, neuron has consolidated_at attr."""
        conn = _make_db()
        nid = _insert_neuron(conn, "content")

        _set_consolidated_timestamp(conn, nid)

        assert _is_consolidated(conn, nid)

    def test_timestamp_is_iso_format(self):
        """consolidated_at value is ISO 8601 formatted."""
        conn = _make_db()
        nid = _insert_neuron(conn, "content")

        _set_consolidated_timestamp(conn, nid)

        row = conn.execute(
            """SELECT na.value FROM neuron_attrs na
               JOIN attr_keys ak ON na.attr_key_id = ak.id
               WHERE na.neuron_id = ? AND ak.name = 'consolidated_at'""",
            (nid,),
        ).fetchone()
        # Should parse as ISO 8601
        timestamp = row[0]
        dt = datetime.fromisoformat(timestamp)
        assert dt.tzinfo is not None  # Should have timezone info

    def test_upsert_on_force_reconsolidate(self):
        """Calling twice updates the timestamp (upsert behavior)."""
        conn = _make_db()
        nid = _insert_neuron(conn, "content")

        _set_consolidated_timestamp(conn, nid)

        # Get first timestamp
        row1 = conn.execute(
            """SELECT na.value FROM neuron_attrs na
               JOIN attr_keys ak ON na.attr_key_id = ak.id
               WHERE na.neuron_id = ? AND ak.name = 'consolidated_at'""",
            (nid,),
        ).fetchone()

        import time
        time.sleep(0.01)  # Ensure different timestamp

        _set_consolidated_timestamp(conn, nid)

        row2 = conn.execute(
            """SELECT na.value FROM neuron_attrs na
               JOIN attr_keys ak ON na.attr_key_id = ak.id
               WHERE na.neuron_id = ? AND ak.name = 'consolidated_at'""",
            (nid,),
        ).fetchone()

        # Should be updated (different timestamp)
        assert row2[0] >= row1[0]


class TestExtractedEdgeWeight:
    """Test that extracted edges have confidence < 1.0."""

    def test_extracted_edge_weight_is_less_than_one(self):
        """EXTRACTED_EDGE_WEIGHT constant is < 1.0."""
        assert EXTRACTED_EDGE_WEIGHT < 1.0

    def test_extracted_edge_weight_is_positive(self):
        """EXTRACTED_EDGE_WEIGHT constant is > 0."""
        assert EXTRACTED_EDGE_WEIGHT > 0
