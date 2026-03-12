# =============================================================================
# Module: test_export_envelope.py
# Purpose: Test the export envelope structure — metadata fields, types, count
#   integrity, JSON serialization, and format version handling.
# Rationale: The envelope is the contract between export and import. If the
#   envelope is malformed, import validation will reject it. These tests
#   verify that build_export_envelope() produces a correct envelope every
#   time, and that serialize_envelope_to_json() produces valid, deterministic
#   JSON output.
# Responsibility:
#   - Verify all required metadata fields are present
#   - Verify field types (str, int, bool, list)
#   - Verify neuron_count and edge_count match array lengths
#   - Verify exported_at is valid ISO 8601 UTC
#   - Verify format version is "1.0"
#   - Verify JSON serialization is valid and deterministic
#   - Verify vectors_included flag is correct
#   - Verify vector metadata (model, dimensions) when vectors included
# Organization:
#   1. Imports and fixtures
#   2. Fixture: sample neurons and edges lists
#   3. Tests: required fields present
#   4. Tests: field types
#   5. Tests: count integrity
#   6. Tests: timestamp format
#   7. Tests: format version
#   8. Tests: JSON serialization
#   9. Tests: vector metadata
# =============================================================================

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

from memory_cli.export_import.export_envelope_format_v1 import (
    build_export_envelope,
    serialize_envelope_to_json,
    EXPORT_FORMAT_VERSION,
)


# --- Fixtures ---


@pytest.fixture
def sample_neurons() -> List[Dict[str, Any]]:
    """Sample neuron dicts as they would come from export_neurons().

    Returns 2 sample neurons with tags, attrs, no vectors.
    Each neuron has: id, content, created_at, updated_at, project, source,
    tags (list of str), attributes (dict of str to str).
    """
    return [
        {
            "id": 1,
            "content": "First test neuron",
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
            "project": "test-project",
            "source": None,
            "tags": ["tag-a", "tag-b"],
            "attributes": {"key1": "val1"},
        },
        {
            "id": 2,
            "content": "Second test neuron",
            "created_at": "2025-01-02T00:00:00+00:00",
            "updated_at": "2025-01-02T00:00:00+00:00",
            "project": "test-project",
            "source": None,
            "tags": ["tag-a"],
            "attributes": {},
        },
    ]


@pytest.fixture
def sample_edges() -> List[Dict[str, Any]]:
    """Sample edge dicts as they would come from export_neurons().

    Returns 1 sample edge connecting the two sample neurons.
    Edge has: source_id, target_id, weight, reason, created_at.
    """
    return [
        {
            "source_id": 1,
            "target_id": 2,
            "weight": 0.8,
            "reason": "related",
            "created_at": "2025-01-01T00:00:00+00:00",
        },
    ]


# --- Tests: Required fields ---


class TestEnvelopeRequiredFields:
    """All required metadata fields must be present in the envelope."""

    def test_all_metadata_fields_present(self, sample_neurons, sample_edges):
        """Envelope should have all required top-level keys.

        Required keys: memory_cli_version, export_format_version, exported_at,
        source_db_vector_model, source_db_vector_dimensions, vectors_included,
        neuron_count, edge_count, neurons, edges.

        Steps:
        1. Call build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        2. Assert each required key is present in the returned dict
        """
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        required_keys = [
            "memory_cli_version",
            "export_format_version",
            "exported_at",
            "source_db_vector_model",
            "source_db_vector_dimensions",
            "vectors_included",
            "neuron_count",
            "edge_count",
            "neurons",
            "edges",
        ]
        for key in required_keys:
            assert key in envelope, f"Missing required key: {key}"

    def test_neurons_and_edges_arrays_present(self, sample_neurons, sample_edges):
        """Envelope must contain neurons and edges arrays.

        Steps:
        1. Build envelope
        2. Assert "neurons" in envelope and isinstance(envelope["neurons"], list)
        3. Assert "edges" in envelope and isinstance(envelope["edges"], list)
        """
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        assert "neurons" in envelope and isinstance(envelope["neurons"], list)
        assert "edges" in envelope and isinstance(envelope["edges"], list)


# --- Tests: Field types ---


class TestEnvelopeFieldTypes:
    """Each metadata field must have the correct type."""

    def test_memory_cli_version_is_string(self, sample_neurons, sample_edges):
        """memory_cli_version should be a string.

        Steps:
        1. Build envelope
        2. Assert isinstance(envelope["memory_cli_version"], str)
        """
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        assert isinstance(envelope["memory_cli_version"], str)

    def test_export_format_version_is_string(self, sample_neurons, sample_edges):
        """export_format_version should be a string."""
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        assert isinstance(envelope["export_format_version"], str)

    def test_exported_at_is_string(self, sample_neurons, sample_edges):
        """exported_at should be a string (ISO 8601)."""
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        assert isinstance(envelope["exported_at"], str)

    def test_vectors_included_is_bool(self, sample_neurons, sample_edges):
        """vectors_included should be a boolean."""
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        assert isinstance(envelope["vectors_included"], bool)

    def test_neuron_count_is_int(self, sample_neurons, sample_edges):
        """neuron_count should be an integer."""
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        assert isinstance(envelope["neuron_count"], int)

    def test_edge_count_is_int(self, sample_neurons, sample_edges):
        """edge_count should be an integer."""
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        assert isinstance(envelope["edge_count"], int)


# --- Tests: Count integrity ---


class TestEnvelopeCountIntegrity:
    """neuron_count and edge_count must match actual array lengths."""

    def test_neuron_count_matches_array(self, sample_neurons, sample_edges):
        """neuron_count should equal len(neurons).

        Steps:
        1. Build envelope with sample_neurons (2 neurons)
        2. Assert envelope["neuron_count"] == 2
        3. Assert envelope["neuron_count"] == len(envelope["neurons"])
        """
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        assert envelope["neuron_count"] == 2
        assert envelope["neuron_count"] == len(envelope["neurons"])

    def test_edge_count_matches_array(self, sample_neurons, sample_edges):
        """edge_count should equal len(edges).

        Steps:
        1. Build envelope with sample_edges (1 edge)
        2. Assert envelope["edge_count"] == 1
        """
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        assert envelope["edge_count"] == 1

    def test_empty_arrays_have_zero_counts(self):
        """Empty neurons/edges -> counts should be 0.

        Steps:
        1. Build envelope with empty lists: neurons=[], edges=[]
        2. Assert neuron_count == 0 and edge_count == 0
        """
        envelope = build_export_envelope([], [], vectors_included=False)
        assert envelope["neuron_count"] == 0
        assert envelope["edge_count"] == 0


# --- Tests: Timestamp format ---


class TestEnvelopeTimestamp:
    """exported_at must be a valid ISO 8601 UTC timestamp."""

    def test_exported_at_is_iso8601(self, sample_neurons, sample_edges):
        """exported_at should be parseable by datetime.fromisoformat().

        Steps:
        1. Build envelope
        2. Call datetime.fromisoformat(envelope["exported_at"])
        3. Assert no exception raised
        """
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        # Should not raise
        dt = datetime.fromisoformat(envelope["exported_at"])
        assert dt is not None

    def test_exported_at_is_utc(self, sample_neurons, sample_edges):
        """exported_at should be in UTC timezone.

        Steps:
        1. Build envelope
        2. Parse exported_at timestamp
        3. Assert timezone info is present and is UTC
        """
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        dt = datetime.fromisoformat(envelope["exported_at"])
        assert dt.tzinfo is not None
        # Check UTC offset is zero
        assert dt.utcoffset().total_seconds() == 0


# --- Tests: Format version ---


class TestEnvelopeFormatVersion:
    """export_format_version must be the current version constant."""

    def test_format_version_is_v1(self, sample_neurons, sample_edges):
        """export_format_version should be '1.0'.

        Steps:
        1. Build envelope
        2. Assert envelope["export_format_version"] == "1.0"
        """
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        assert envelope["export_format_version"] == "1.0"
        assert envelope["export_format_version"] == EXPORT_FORMAT_VERSION


# --- Tests: JSON serialization ---


class TestEnvelopeSerialization:
    """serialize_envelope_to_json() must produce valid, deterministic JSON."""

    def test_output_is_valid_json(self, sample_neurons, sample_edges):
        """Serialized output should be parseable by json.loads().

        Steps:
        1. Build envelope, call serialize_envelope_to_json()
        2. Call json.loads() on the result
        3. Assert no exception raised
        """
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        json_str = serialize_envelope_to_json(envelope)
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def test_roundtrip_preserves_data(self, sample_neurons, sample_edges):
        """Serialize then parse should produce identical data.

        Steps:
        1. Build envelope
        2. Serialize to JSON string
        3. Parse JSON string back to dict
        4. Assert parsed dict equals original envelope
        """
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        json_str = serialize_envelope_to_json(envelope)
        parsed = json.loads(json_str)
        assert parsed == envelope

    def test_output_ends_with_newline(self, sample_neurons, sample_edges):
        """JSON output should end with a newline for POSIX compliance.

        Steps:
        1. Build envelope, serialize
        2. Assert json_string.endswith("\\n")
        """
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        json_str = serialize_envelope_to_json(envelope)
        assert json_str.endswith("\n")

    def test_unicode_content_preserved(self):
        """Neurons with Unicode content should survive serialization.

        Steps:
        1. Create neuron with content containing emoji, CJK, accented chars
        2. Build envelope, serialize, parse
        3. Assert content string is byte-identical to original
        """
        unicode_content = "Hello 世界 🌍 café résumé"
        neurons = [{
            "id": 1,
            "content": unicode_content,
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
            "project": "test",
            "source": None,
            "tags": [],
            "attributes": {},
        }]
        envelope = build_export_envelope(neurons, [], vectors_included=False)
        json_str = serialize_envelope_to_json(envelope)
        parsed = json.loads(json_str)
        assert parsed["neurons"][0]["content"] == unicode_content


# --- Tests: Vector metadata ---


class TestEnvelopeVectorMetadata:
    """Vector-related metadata fields when vectors are included/excluded."""

    def test_vectors_included_true(self):
        """When vectors included, vectors_included should be True.

        Steps:
        1. Build envelope with vectors_included=True
        2. Assert envelope["vectors_included"] is True
        """
        envelope = build_export_envelope([], [], vectors_included=True, source_db_vector_model="test-model", source_db_vector_dimensions=768)
        assert envelope["vectors_included"] is True

    def test_vectors_included_false(self, sample_neurons, sample_edges):
        """When vectors not included, vectors_included should be False.

        Steps:
        1. Build envelope with vectors_included=False
        2. Assert envelope["vectors_included"] is False
        """
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        assert envelope["vectors_included"] is False

    def test_vector_model_present_when_vectors_included(self):
        """source_db_vector_model should be set when vectors are included.

        Steps:
        1. Build with vectors_included=True, source_db_vector_model="test-model"
        2. Assert envelope["source_db_vector_model"] == "test-model"
        """
        envelope = build_export_envelope([], [], vectors_included=True, source_db_vector_model="test-model")
        assert envelope["source_db_vector_model"] == "test-model"

    def test_vector_dimensions_present_when_vectors_included(self):
        """source_db_vector_dimensions should be set when vectors included.

        Steps:
        1. Build with vectors_included=True, source_db_vector_dimensions=768
        2. Assert envelope["source_db_vector_dimensions"] == 768
        """
        envelope = build_export_envelope([], [], vectors_included=True, source_db_vector_dimensions=768)
        assert envelope["source_db_vector_dimensions"] == 768

    def test_vector_metadata_null_when_no_vectors(self, sample_neurons, sample_edges):
        """Vector metadata should be null when vectors not included.

        Steps:
        1. Build with vectors_included=False, no model/dims provided
        2. Assert source_db_vector_model is None
        3. Assert source_db_vector_dimensions is None
        """
        envelope = build_export_envelope(sample_neurons, sample_edges, vectors_included=False)
        assert envelope["source_db_vector_model"] is None
        assert envelope["source_db_vector_dimensions"] is None
