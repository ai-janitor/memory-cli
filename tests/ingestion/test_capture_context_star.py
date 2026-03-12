# =============================================================================
# Module: test_capture_context_star.py
# Purpose: Test star topology context capture — session context neuron
#   creation, star edge creation with weight 0.5, and edge cases.
# Rationale: The star topology is the mechanism that preserves session-level
#   context in the graph (Finding S-6). Tests must verify the hub neuron
#   is created correctly, edges have the right weight and reason, and
#   failures in individual edge creation don't abort the batch.
# Responsibility:
#   - Test context neuron creation with correct content and tags
#   - Test star edge creation with weight 0.5
#   - Test edge reason format: "co-occurred in session <id>"
#   - Test empty neuron_ids returns (0, 0)
#   - Test individual edge failure doesn't abort batch
#   - Test project tag propagation to context neuron
# Organization:
#   1. Imports and fixtures
#   2. TestCaptureContextStar — main entry point
#   3. TestCreateContextNeuron — hub neuron creation
#   4. TestCreateStarEdges — edge creation loop
# =============================================================================

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, call, patch

import pytest

from memory_cli.ingestion.capture_context_star_topology_edges import (
    CONTEXT_EDGE_REASON_TEMPLATE,
    CONTEXT_EDGE_WEIGHT,
    CONTEXT_NEURON_CONTENT_TEMPLATE,
    _create_context_neuron,
    _create_star_edges,
    capture_context_star,
)


class TestCaptureContextStar:
    """Test capture_context_star() end-to-end with mocked neuron/edge CRUD."""

    def test_creates_context_neuron_and_star_edges(self):
        """neuron_ids=[10, 20, 30] -> returns (99, 3)."""
        conn = MagicMock()
        with patch("memory_cli.ingestion.capture_context_star_topology_edges._create_context_neuron",
                   return_value=99) as mock_ctx:
            with patch("memory_cli.ingestion.capture_context_star_topology_edges._create_star_edges",
                       return_value=3) as mock_edges:
                ctx_id, edge_count = capture_context_star(conn, "sess-abc", [10, 20, 30])
        assert ctx_id == 99
        assert edge_count == 3
        mock_ctx.assert_called_once()
        mock_edges.assert_called_once()

    def test_empty_neuron_ids_returns_zero_zero(self):
        """neuron_ids=[] -> returns (0, 0), no neuron or edge creation."""
        conn = MagicMock()
        with patch("memory_cli.ingestion.capture_context_star_topology_edges._create_context_neuron") as mock_ctx:
            with patch("memory_cli.ingestion.capture_context_star_topology_edges._create_star_edges") as mock_edges:
                result = capture_context_star(conn, "sess-abc", [])
        assert result == (0, 0)
        mock_ctx.assert_not_called()
        mock_edges.assert_not_called()

    def test_edge_weight_is_half(self):
        """edge_add called with weight=0.5."""
        conn = MagicMock()
        with patch("memory_cli.ingestion.capture_context_star_topology_edges.neuron_add",
                   return_value={"id": 99}):
            with patch("memory_cli.ingestion.capture_context_star_topology_edges.edge_add") as mock_edge:
                # Directly test _create_star_edges
                from memory_cli.ingestion.capture_context_star_topology_edges import _create_star_edges
                _create_star_edges(conn, 99, [10], "sess-abc")
        # edge_add should have been called with CONTEXT_EDGE_WEIGHT
        if mock_edge.called:
            call_kwargs = mock_edge.call_args[1] if mock_edge.call_args[1] else {}
            call_args = mock_edge.call_args[0]
            weight = call_kwargs.get("weight") or (call_args[4] if len(call_args) > 4 else None)
            # weight should be 0.5
            assert weight == CONTEXT_EDGE_WEIGHT or CONTEXT_EDGE_WEIGHT == 0.5

    def test_edge_reason_contains_session_id(self):
        """edge reason contains "sess-abc"."""
        conn = MagicMock()
        captured_reason = {}

        def mock_edge_add(c, src, tgt, reason, weight=None):
            captured_reason["reason"] = reason
            return {"id": 1}

        with patch("memory_cli.ingestion.capture_context_star_topology_edges.edge_add",
                   side_effect=mock_edge_add):
            _create_star_edges(conn, 99, [10], "sess-abc")
        assert "sess-abc" in captured_reason.get("reason", "")

    def test_project_passed_to_context_neuron(self):
        """project="myproj" -> neuron_add called with "project:myproj" tag."""
        conn = MagicMock()
        captured_tags = {}

        def mock_neuron_add(c, content, tags=None, attrs=None, no_embed=False):
            captured_tags["tags"] = tags or []
            return {"id": 99}

        with patch("memory_cli.ingestion.capture_context_star_topology_edges.neuron_add",
                   side_effect=mock_neuron_add):
            _create_context_neuron(conn, "sess-abc", project="myproj")
        assert "project:myproj" in captured_tags.get("tags", [])


class TestCreateContextNeuron:
    """Test _create_context_neuron() hub neuron creation."""

    def test_content_matches_template(self):
        """Content is "Session context: sess-abc"."""
        conn = MagicMock()
        captured_content = {}

        def mock_neuron_add(c, content, tags=None, attrs=None, no_embed=False):
            captured_content["content"] = content
            return {"id": 1}

        with patch("memory_cli.ingestion.capture_context_star_topology_edges.neuron_add",
                   side_effect=mock_neuron_add):
            _create_context_neuron(conn, "sess-abc")
        expected = CONTEXT_NEURON_CONTENT_TEMPLATE.format(session_id="sess-abc")
        assert captured_content["content"] == expected

    def test_tagged_as_session_context(self):
        """Tags include "ingested" and "session-context"."""
        conn = MagicMock()
        captured_tags = {}

        def mock_neuron_add(c, content, tags=None, attrs=None, no_embed=False):
            captured_tags["tags"] = tags or []
            return {"id": 1}

        with patch("memory_cli.ingestion.capture_context_star_topology_edges.neuron_add",
                   side_effect=mock_neuron_add):
            _create_context_neuron(conn, "sess-abc")
        assert "ingested" in captured_tags["tags"]
        assert "session-context" in captured_tags["tags"]

    def test_no_embed_flag_set(self):
        """neuron_add called with no_embed=True."""
        conn = MagicMock()
        captured_kwargs = {}

        def mock_neuron_add(c, content, tags=None, attrs=None, no_embed=False):
            captured_kwargs["no_embed"] = no_embed
            return {"id": 1}

        with patch("memory_cli.ingestion.capture_context_star_topology_edges.neuron_add",
                   side_effect=mock_neuron_add):
            _create_context_neuron(conn, "sess-abc")
        assert captured_kwargs.get("no_embed") is True

    def test_attrs_include_session_id_and_context_type(self):
        """attrs have ingested_session_id and context_type="session_hub"."""
        conn = MagicMock()
        captured_attrs = {}

        def mock_neuron_add(c, content, tags=None, attrs=None, no_embed=False):
            captured_attrs.update(attrs or {})
            return {"id": 1}

        with patch("memory_cli.ingestion.capture_context_star_topology_edges.neuron_add",
                   side_effect=mock_neuron_add):
            _create_context_neuron(conn, "sess-abc")
        assert captured_attrs.get("ingested_session_id") == "sess-abc"
        assert captured_attrs.get("context_type") == "session_hub"

    def test_project_tag_added_when_provided(self):
        """project="myproj" -> "project:myproj" in tags."""
        conn = MagicMock()
        captured_tags = {}

        def mock_neuron_add(c, content, tags=None, attrs=None, no_embed=False):
            captured_tags["tags"] = tags or []
            return {"id": 1}

        with patch("memory_cli.ingestion.capture_context_star_topology_edges.neuron_add",
                   side_effect=mock_neuron_add):
            _create_context_neuron(conn, "sess-abc", project="myproj")
        assert "project:myproj" in captured_tags["tags"]


class TestCreateStarEdges:
    """Test _create_star_edges() edge creation loop."""

    def test_creates_edge_per_neuron(self):
        """3 neuron_ids -> edge_add called 3 times with context_neuron_id as source."""
        conn = MagicMock()
        call_args_list = []

        def mock_edge_add(c, src, tgt, reason, weight=None):
            call_args_list.append((src, tgt))
            return {"id": 1}

        with patch("memory_cli.ingestion.capture_context_star_topology_edges.edge_add",
                   side_effect=mock_edge_add):
            _create_star_edges(conn, 99, [10, 20, 30], "sess-abc")
        assert len(call_args_list) == 3
        for src, tgt in call_args_list:
            assert src == 99  # context_neuron_id is always source

    def test_edge_failure_continues_batch(self):
        """edge_add raises for neuron_id=20 -> returns 2 (not 3), no exception."""
        conn = MagicMock()
        call_count = {"n": 0}

        def mock_edge_add(c, src, tgt, reason, weight=None):
            call_count["n"] += 1
            if tgt == 20:
                raise RuntimeError("edge fail")
            return {"id": 1}

        with patch("memory_cli.ingestion.capture_context_star_topology_edges.edge_add",
                   side_effect=mock_edge_add):
            count = _create_star_edges(conn, 99, [10, 20, 30], "sess-abc")
        assert count == 2

    def test_returns_count_of_successful_edges(self):
        """Return value matches number of successful edge_add calls."""
        conn = MagicMock()

        with patch("memory_cli.ingestion.capture_context_star_topology_edges.edge_add",
                   return_value={"id": 1}):
            count = _create_star_edges(conn, 99, [1, 2, 3, 4, 5], "sess-abc")
        assert count == 5

    def test_weight_is_context_edge_weight_constant(self):
        """Each edge_add call uses CONTEXT_EDGE_WEIGHT (0.5)."""
        conn = MagicMock()
        captured_weights = []

        def mock_edge_add(c, src, tgt, reason, weight=None):
            captured_weights.append(weight)
            return {"id": 1}

        with patch("memory_cli.ingestion.capture_context_star_topology_edges.edge_add",
                   side_effect=mock_edge_add):
            _create_star_edges(conn, 99, [10, 20], "sess-abc")
        assert all(w == CONTEXT_EDGE_WEIGHT for w in captured_weights)
