# =============================================================================
# Module: test_neuron_edge_creator.py
# Purpose: Test neuron and edge creation from Haiku extraction results —
#   neuron creation with metadata, edge creation with local ID resolution,
#   handling of unresolvable references, and tag/attr construction.
# Rationale: The creator bridges Haiku's abstract output and the graph's
#   concrete CRUD. Local ID resolution is the trickiest part — references
#   may point to items that failed to create. Each failure mode needs
#   explicit coverage to ensure warnings are captured (not crashes).
# Responsibility:
#   - Test neuron creation for entities and facts
#   - Test edge creation with successful ID resolution
#   - Test unresolvable ID references produce warnings
#   - Test ingestion tag construction (with and without project)
#   - Test ingestion attr construction
#   - Test CreationResult aggregation
# Organization:
#   1. Imports and fixtures
#   2. TestCreateNeuronsAndEdges — main entry point
#   3. TestCreateNeuronFromItem — single neuron creation
#   4. TestCreateEdgesFromRelationships — edge creation + ID resolution
#   5. TestBuildIngestionTags — tag list construction
#   6. TestBuildIngestionAttrs — attr dict construction
# =============================================================================

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from memory_cli.ingestion.haiku_extraction_entities_facts_rels import (
    ExtractedEntity,
    ExtractedFact,
    ExtractedRelationship,
    ExtractionResult,
)
from memory_cli.ingestion.neuron_and_edge_creator_from_extraction import (
    CreationResult,
    _build_ingestion_attrs,
    _build_ingestion_tags,
    _create_edges_from_relationships,
    _create_neuron_from_item,
    create_neurons_and_edges,
)


class TestCreateNeuronsAndEdges:
    """Test create_neurons_and_edges() end-to-end with mocked CRUD."""

    def test_creates_neurons_for_entities_and_facts(self):
        """Extraction with 2 entities + 1 fact -> 3 neurons created."""
        extraction = ExtractionResult(
            entities=[ExtractedEntity("e1", "Python"), ExtractedEntity("e2", "SQLite")],
            facts=[ExtractedFact("f1", "SQLite is embedded")],
            relationships=[],
        )
        conn = MagicMock()
        call_count = {"n": 0}

        def mock_neuron_add(c, content, **kwargs):
            call_count["n"] += 1
            return {"id": call_count["n"]}

        with patch("memory_cli.ingestion.neuron_and_edge_creator_from_extraction._create_neuron_from_item",
                   side_effect=lambda c, content, role, tags, attrs, lid: call_count.__setitem__("n", call_count["n"] + 1) or call_count["n"]):
            result = create_neurons_and_edges(conn, extraction, "/path/file.jsonl", None, None, "sess-123")
        assert result.neuron_count == 3
        assert len(result.neuron_ids) == 3

    def test_creates_edges_for_relationships(self):
        """1 relationship between two entities -> 1 edge created."""
        extraction = ExtractionResult(
            entities=[ExtractedEntity("e1", "A"), ExtractedEntity("e2", "B")],
            facts=[],
            relationships=[ExtractedRelationship("e1", "e2", "related")],
        )
        conn = MagicMock()
        id_counter = {"n": 0}

        def mock_create_neuron(c, content, role, tags, attrs, lid):
            id_counter["n"] += 1
            return id_counter["n"]

        with patch("memory_cli.ingestion.neuron_and_edge_creator_from_extraction._create_neuron_from_item",
                   side_effect=mock_create_neuron):
            with patch("memory_cli.ingestion.neuron_and_edge_creator_from_extraction._create_edges_from_relationships",
                       return_value=(1, [])):
                result = create_neurons_and_edges(conn, extraction, "/path/file.jsonl", None, None, "sess-123")
        assert result.edge_count == 1

    def test_neuron_failure_is_warning(self):
        """Mock neuron creation to fail for second entity -> warning present."""
        extraction = ExtractionResult(
            entities=[ExtractedEntity("e1", "A"), ExtractedEntity("e2", "B")],
            facts=[ExtractedFact("f1", "C")],
            relationships=[],
        )
        conn = MagicMock()
        call_count = {"n": 0}

        def mock_create_neuron(c, content, role, tags, attrs, lid):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise Exception("creation failed")
            return call_count["n"]

        with patch("memory_cli.ingestion.neuron_and_edge_creator_from_extraction._create_neuron_from_item",
                   side_effect=mock_create_neuron):
            result = create_neurons_and_edges(conn, extraction, "/path/file.jsonl", None, None, "sess-123")
        assert result.neuron_count == 2  # 2 succeeded, 1 failed
        assert len(result.warnings) > 0

    def test_local_id_to_neuron_id_mapping(self):
        """result.local_id_to_neuron_id maps Haiku IDs to neuron IDs."""
        extraction = ExtractionResult(
            entities=[ExtractedEntity("e1", "A")],
            facts=[],
            relationships=[],
        )
        conn = MagicMock()

        def mock_create_neuron(c, content, role, tags, attrs, lid):
            return 42

        with patch("memory_cli.ingestion.neuron_and_edge_creator_from_extraction._create_neuron_from_item",
                   side_effect=mock_create_neuron):
            result = create_neurons_and_edges(conn, extraction, "/path/file.jsonl", None, None, "sess-123")
        assert result.local_id_to_neuron_id == {"e1": 42}


class TestCreateNeuronFromItem:
    """Test _create_neuron_from_item() delegation to neuron_add."""

    def test_returns_neuron_id(self):
        """Mock neuron_add to return {"id": 42} -> returns 42."""
        conn = MagicMock()
        with patch("memory_cli.ingestion.neuron_and_edge_creator_from_extraction.neuron_add",
                   return_value={"id": 42}):
            result = _create_neuron_from_item(
                conn, "content", "entity", ["ingested"], {"source": "/f.jsonl"}, "e1"
            )
        assert result == 42

    def test_adds_ingest_role_to_attrs(self):
        """attrs passed to neuron_add include ingest_role="entity"."""
        conn = MagicMock()
        captured_attrs = {}

        def mock_neuron_add(c, content, tags=None, attrs=None, source=None):
            captured_attrs.update(attrs or {})
            return {"id": 1}

        with patch("memory_cli.ingestion.neuron_and_edge_creator_from_extraction.neuron_add",
                   side_effect=mock_neuron_add):
            _create_neuron_from_item(
                conn, "content", "entity", ["ingested"], {"source": "/f.jsonl"}, "e1"
            )
        assert captured_attrs.get("ingest_role") == "entity"

    def test_adds_ingest_local_id_to_attrs(self):
        """attrs include ingest_local_id matching the local_id arg."""
        conn = MagicMock()
        captured_attrs = {}

        def mock_neuron_add(c, content, tags=None, attrs=None, source=None):
            captured_attrs.update(attrs or {})
            return {"id": 1}

        with patch("memory_cli.ingestion.neuron_and_edge_creator_from_extraction.neuron_add",
                   side_effect=mock_neuron_add):
            _create_neuron_from_item(
                conn, "content", "fact", ["ingested"], {"source": "/f.jsonl"}, "f99"
            )
        assert captured_attrs.get("ingest_local_id") == "f99"

    def test_propagates_exception(self):
        """Mock neuron_add to raise -> exception propagates."""
        conn = MagicMock()
        with patch("memory_cli.ingestion.neuron_and_edge_creator_from_extraction.neuron_add",
                   side_effect=RuntimeError("db error")):
            with pytest.raises(RuntimeError):
                _create_neuron_from_item(
                    conn, "content", "entity", [], {}, "e1"
                )


class TestCreateEdgesFromRelationships:
    """Test _create_edges_from_relationships() ID resolution and edge creation."""

    def test_resolves_ids_and_creates_edge(self):
        """edge_add called with resolved IDs."""
        conn = MagicMock()
        relationships = [ExtractedRelationship("e1", "e2", "related")]
        id_map = {"e1": 10, "e2": 20}
        captured_calls = []

        def mock_edge_add(c, src, tgt, reason, weight=None):
            captured_calls.append((src, tgt, reason))
            return {"id": 1}

        with patch("memory_cli.ingestion.neuron_and_edge_creator_from_extraction.edge_add",
                   side_effect=mock_edge_add):
            count, warnings = _create_edges_from_relationships(conn, relationships, id_map)
        assert count == 1
        assert warnings == []
        assert captured_calls == [(10, 20, "related")]

    def test_unresolvable_from_id_produces_warning(self):
        """from_id "e1" not in id_map -> warning, edge not created."""
        conn = MagicMock()
        relationships = [ExtractedRelationship("e1", "e2", "related")]
        id_map = {"e2": 20}  # e1 missing
        count, warnings = _create_edges_from_relationships(conn, relationships, id_map)
        assert count == 0
        assert len(warnings) == 1
        assert "e1" in warnings[0]

    def test_unresolvable_to_id_produces_warning(self):
        """to_id "e2" not in id_map -> warning, edge not created."""
        conn = MagicMock()
        relationships = [ExtractedRelationship("e1", "e2", "related")]
        id_map = {"e1": 10}  # e2 missing
        count, warnings = _create_edges_from_relationships(conn, relationships, id_map)
        assert count == 0
        assert len(warnings) == 1
        assert "e2" in warnings[0]

    def test_edge_add_failure_produces_warning(self):
        """Mock edge_add to raise -> warning present, edge_count == 0."""
        conn = MagicMock()
        relationships = [ExtractedRelationship("e1", "e2", "related")]
        id_map = {"e1": 10, "e2": 20}
        with patch("memory_cli.ingestion.neuron_and_edge_creator_from_extraction.edge_add",
                   side_effect=RuntimeError("db error")):
            count, warnings = _create_edges_from_relationships(conn, relationships, id_map)
        assert count == 0
        assert len(warnings) == 1

    def test_multiple_relationships_partial_success(self):
        """3 relationships: 1 succeeds, 1 unresolvable, 1 fails -> edge_count==1, 2 warnings."""
        conn = MagicMock()
        relationships = [
            ExtractedRelationship("e1", "e2", "ok"),
            ExtractedRelationship("e3", "e4", "missing"),  # e3 not in map
            ExtractedRelationship("e1", "e2", "fails"),
        ]
        id_map = {"e1": 10, "e2": 20, "e4": 40}  # e3 missing
        call_count = {"n": 0}

        def mock_edge_add(c, src, tgt, reason, weight=None):
            call_count["n"] += 1
            if call_count["n"] == 2:  # second valid call fails
                raise RuntimeError("fail")
            return {"id": 1}

        with patch("memory_cli.ingestion.neuron_and_edge_creator_from_extraction.edge_add",
                   side_effect=mock_edge_add):
            count, warnings = _create_edges_from_relationships(conn, relationships, id_map)
        assert count == 1
        assert len(warnings) == 2


class TestBuildIngestionTags:
    """Test _build_ingestion_tags() tag list construction."""

    def test_always_includes_ingested_tag(self):
        """'ingested' always in result."""
        tags = _build_ingestion_tags(None, None)
        assert "ingested" in tags

    def test_includes_project_tag_when_provided(self):
        """project="myproj" -> "project:myproj" in result."""
        tags = _build_ingestion_tags("myproj", None)
        assert "project:myproj" in tags

    def test_no_project_tag_when_none(self):
        """project=None -> no "project:" tag in result."""
        tags = _build_ingestion_tags(None, None)
        assert not any(t.startswith("project:") for t in tags)

    def test_includes_user_tags(self):
        """user_tags=["custom1", "custom2"] -> both in result."""
        tags = _build_ingestion_tags(None, ["custom1", "custom2"])
        assert "custom1" in tags
        assert "custom2" in tags

    def test_deduplicates(self):
        """user_tags=["ingested", "custom"] -> "ingested" appears only once."""
        tags = _build_ingestion_tags(None, ["ingested", "custom"])
        assert tags.count("ingested") == 1


class TestBuildIngestionAttrs:
    """Test _build_ingestion_attrs() attr dict construction."""

    def test_includes_source_and_session_id(self):
        """'source' and 'ingested_session_id' keys present."""
        attrs = _build_ingestion_attrs("/path/file.jsonl", None, "sess-123")
        assert attrs["source"] == "/path/file.jsonl"
        assert attrs["ingested_session_id"] == "sess-123"

    def test_includes_project_when_provided(self):
        """project="myproj" -> 'project' key with value "myproj"."""
        attrs = _build_ingestion_attrs("/path/file.jsonl", "myproj", "sess-123")
        assert attrs.get("project") == "myproj"

    def test_no_project_when_none(self):
        """project=None -> 'project' key absent."""
        attrs = _build_ingestion_attrs("/path/file.jsonl", None, "sess-123")
        assert "project" not in attrs
