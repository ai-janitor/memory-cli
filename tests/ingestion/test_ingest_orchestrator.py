# =============================================================================
# Module: test_ingest_orchestrator.py
# Purpose: Test the full ingestion pipeline orchestrator — end-to-end flow,
#   dry-run mode, error propagation from each stage, and result aggregation.
# Rationale: The orchestrator coordinates 6 stages with different failure
#   modes. Tests must verify that the pipeline flows correctly end-to-end,
#   that dry-run produces no writes, that critical failures (parse, extract)
#   abort the pipeline, and that non-critical failures (individual neuron/edge)
#   are collected as warnings without aborting.
# Responsibility:
#   - Test full pipeline with mocked stages
#   - Test dry-run mode (no writes, correct report)
#   - Test error propagation from each stage
#   - Test session dedup integration (skip vs force)
#   - Test IngestResult aggregation (counts, warnings)
# Organization:
#   1. Imports and fixtures
#   2. TestIngestSessionFullPipeline — happy path with mocked stages
#   3. TestIngestSessionDryRun — dry-run produces no writes
#   4. TestIngestSessionErrors — error propagation from each stage
#   5. TestIngestSessionDedup — dedup guard integration
#   6. TestIngestResult — result dataclass behavior
# =============================================================================

from __future__ import annotations

import json
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from memory_cli.ingestion.ingest_orchestrator import (
    IngestError,
    IngestResult,
    ingest_session,
)


# -----------------------------------------------------------------------------
# Fixtures / helpers
# -----------------------------------------------------------------------------

def _make_jsonl_file(session_id: str = "sess-test", n_messages: int = 2) -> Path:
    """Create a temp JSONL file with valid user/assistant messages."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for i in range(n_messages):
        role = "user" if i % 2 == 0 else "assistant"
        data = {
            "type": role,
            "message": {"content": f"message {i}"},
            "sessionId": session_id,
            "timestamp": f"2024-01-01T00:00:0{i}Z",
        }
        tmp.write(json.dumps(data) + "\n")
    tmp.close()
    return Path(tmp.name)


def _make_empty_jsonl_file() -> Path:
    """Create a temp JSONL file with no valid messages."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    tmp.write("")
    tmp.close()
    return Path(tmp.name)


@dataclass
class MockDedupResult:
    already_ingested: bool
    existing_neuron_count: int
    session_id: str


@dataclass
class MockCreationResult:
    neuron_count: int = 0
    edge_count: int = 0
    neuron_ids: List[int] = field(default_factory=list)
    local_id_to_neuron_id: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


@dataclass
class MockExtractionResult:
    entities: list = field(default_factory=list)
    facts: list = field(default_factory=list)
    relationships: list = field(default_factory=list)
    raw_response: Optional[Dict] = None


class TestIngestSessionFullPipeline:
    """Test the happy-path full pipeline with all stages mocked."""

    def test_full_pipeline_creates_neurons_and_edges(self):
        """Mock all stages -> IngestResult has correct neuron_count, edge_count."""
        path = _make_jsonl_file("sess-test")
        conn = MagicMock()

        dedup_result = MockDedupResult(already_ingested=False, existing_neuron_count=0, session_id="sess-test")
        extraction = MockExtractionResult()
        creation = MockCreationResult(neuron_count=3, edge_count=1, neuron_ids=[1, 2, 3])

        with patch("memory_cli.ingestion.ingest_orchestrator.check_session_already_ingested",
                   return_value=dedup_result):
            with patch("memory_cli.ingestion.ingest_orchestrator.assemble_transcript_chunks",
                       return_value=["chunk1"]):
                with patch("memory_cli.ingestion.ingest_orchestrator.haiku_extract",
                           return_value=extraction):
                    with patch("memory_cli.ingestion.ingest_orchestrator.create_neurons_and_edges",
                               return_value=creation):
                        with patch("memory_cli.ingestion.ingest_orchestrator.capture_context_star",
                                   return_value=(99, 3)):
                            result = ingest_session(conn, path)

        assert result.neurons_created == 3
        assert not result.skipped
        assert result.session_id == "sess-test"

    def test_pipeline_returns_session_id(self):
        """IngestResult.session_id matches extracted session ID."""
        path = _make_jsonl_file("my-session-id")
        conn = MagicMock()

        dedup_result = MockDedupResult(already_ingested=False, existing_neuron_count=0, session_id="my-session-id")
        extraction = MockExtractionResult()
        creation = MockCreationResult(neuron_count=1, edge_count=0, neuron_ids=[1])

        with patch("memory_cli.ingestion.ingest_orchestrator.check_session_already_ingested",
                   return_value=dedup_result):
            with patch("memory_cli.ingestion.ingest_orchestrator.assemble_transcript_chunks",
                       return_value=["chunk"]):
                with patch("memory_cli.ingestion.ingest_orchestrator.haiku_extract",
                           return_value=extraction):
                    with patch("memory_cli.ingestion.ingest_orchestrator.create_neurons_and_edges",
                               return_value=creation):
                        with patch("memory_cli.ingestion.ingest_orchestrator.capture_context_star",
                                   return_value=(99, 1)):
                            result = ingest_session(conn, path)
        assert result.session_id == "my-session-id"


class TestIngestSessionDryRun:
    """Test that dry-run mode reports what would happen without writing."""

    def test_dry_run_skips_neuron_creation(self):
        """call with dry_run=True -> create_neurons_and_edges never called."""
        path = _make_jsonl_file("sess-dry")
        conn = MagicMock()

        dedup_result = MockDedupResult(already_ingested=False, existing_neuron_count=0, session_id="sess-dry")
        extraction = MockExtractionResult()

        with patch("memory_cli.ingestion.ingest_orchestrator.check_session_already_ingested",
                   return_value=dedup_result):
            with patch("memory_cli.ingestion.ingest_orchestrator.assemble_transcript_chunks",
                       return_value=["chunk"]):
                with patch("memory_cli.ingestion.ingest_orchestrator.haiku_extract",
                           return_value=extraction):
                    with patch("memory_cli.ingestion.ingest_orchestrator.create_neurons_and_edges") as mock_create:
                        with patch("memory_cli.ingestion.ingest_orchestrator.capture_context_star") as mock_star:
                            result = ingest_session(conn, path, dry_run=True)
        mock_create.assert_not_called()
        mock_star.assert_not_called()

    def test_dry_run_still_parses_and_extracts(self):
        """dry_run=True -> parse and extract still called."""
        path = _make_jsonl_file("sess-dry")
        conn = MagicMock()

        dedup_result = MockDedupResult(already_ingested=False, existing_neuron_count=0, session_id="sess-dry")
        extraction = MockExtractionResult()

        with patch("memory_cli.ingestion.ingest_orchestrator.check_session_already_ingested",
                   return_value=dedup_result):
            with patch("memory_cli.ingestion.ingest_orchestrator.assemble_transcript_chunks",
                       return_value=["chunk"]) as mock_assemble:
                with patch("memory_cli.ingestion.ingest_orchestrator.haiku_extract",
                           return_value=extraction) as mock_extract:
                    with patch("memory_cli.ingestion.ingest_orchestrator.create_neurons_and_edges",
                               return_value=MockCreationResult()):
                        with patch("memory_cli.ingestion.ingest_orchestrator.capture_context_star",
                                   return_value=(99, 0)):
                            result = ingest_session(conn, path, dry_run=True)
        mock_assemble.assert_called_once()
        mock_extract.assert_called_once()


class TestIngestSessionErrors:
    """Test error propagation from each pipeline stage."""

    def test_file_not_found_raises_ingest_error(self):
        """Pass nonexistent path -> IngestError."""
        conn = MagicMock()
        with pytest.raises(IngestError) as exc_info:
            ingest_session(conn, Path("/nonexistent/file.jsonl"))
        assert exc_info.value.step == "parse"

    def test_empty_file_raises_ingest_error(self):
        """Parse returns empty message list -> IngestError."""
        path = _make_empty_jsonl_file()
        conn = MagicMock()
        with pytest.raises(IngestError) as exc_info:
            ingest_session(conn, path)
        assert exc_info.value.step == "parse"

    def test_haiku_api_failure_raises_ingest_error(self):
        """Mock haiku_extract to raise -> IngestError with "extract" step."""
        path = _make_jsonl_file("sess-err")
        conn = MagicMock()
        dedup_result = MockDedupResult(already_ingested=False, existing_neuron_count=0, session_id="sess-err")

        with patch("memory_cli.ingestion.ingest_orchestrator.check_session_already_ingested",
                   return_value=dedup_result):
            with patch("memory_cli.ingestion.ingest_orchestrator.assemble_transcript_chunks",
                       return_value=["chunk"]):
                with patch("memory_cli.ingestion.ingest_orchestrator.haiku_extract",
                           side_effect=Exception("API failed")):
                    with pytest.raises(IngestError) as exc_info:
                        ingest_session(conn, path)
        assert exc_info.value.step == "extract"


class TestIngestSessionDedup:
    """Test session dedup guard integration."""

    def test_already_ingested_returns_skipped(self):
        """Mock dedup check returns already_ingested=True -> result.skipped is True."""
        path = _make_jsonl_file("sess-dup")
        conn = MagicMock()
        dedup_result = MockDedupResult(already_ingested=True, existing_neuron_count=5, session_id="sess-dup")

        with patch("memory_cli.ingestion.ingest_orchestrator.check_session_already_ingested",
                   return_value=dedup_result):
            result = ingest_session(conn, path)
        assert result.skipped is True
        assert result.session_id == "sess-dup"

    def test_already_ingested_with_force_proceeds(self):
        """force=True on already-ingested session -> pipeline proceeds."""
        path = _make_jsonl_file("sess-dup")
        conn = MagicMock()
        dedup_result = MockDedupResult(already_ingested=True, existing_neuron_count=5, session_id="sess-dup")
        extraction = MockExtractionResult()
        creation = MockCreationResult(neuron_count=1, edge_count=0, neuron_ids=[1])

        with patch("memory_cli.ingestion.ingest_orchestrator.check_session_already_ingested",
                   return_value=dedup_result):
            with patch("memory_cli.ingestion.ingest_orchestrator.assemble_transcript_chunks",
                       return_value=["chunk"]):
                with patch("memory_cli.ingestion.ingest_orchestrator.haiku_extract",
                           return_value=extraction):
                    with patch("memory_cli.ingestion.ingest_orchestrator.create_neurons_and_edges",
                               return_value=creation):
                        with patch("memory_cli.ingestion.ingest_orchestrator.capture_context_star",
                                   return_value=(99, 1)):
                            result = ingest_session(conn, path, force=True)
        assert result.skipped is False

    def test_new_session_proceeds_normally(self):
        """Dedup check returns False -> pipeline proceeds normally."""
        path = _make_jsonl_file("sess-new")
        conn = MagicMock()
        dedup_result = MockDedupResult(already_ingested=False, existing_neuron_count=0, session_id="sess-new")
        extraction = MockExtractionResult()
        creation = MockCreationResult(neuron_count=2, edge_count=1, neuron_ids=[1, 2])

        with patch("memory_cli.ingestion.ingest_orchestrator.check_session_already_ingested",
                   return_value=dedup_result):
            with patch("memory_cli.ingestion.ingest_orchestrator.assemble_transcript_chunks",
                       return_value=["chunk"]):
                with patch("memory_cli.ingestion.ingest_orchestrator.haiku_extract",
                           return_value=extraction):
                    with patch("memory_cli.ingestion.ingest_orchestrator.create_neurons_and_edges",
                               return_value=creation):
                        with patch("memory_cli.ingestion.ingest_orchestrator.capture_context_star",
                                   return_value=(99, 2)):
                            result = ingest_session(conn, path)
        assert result.skipped is False
        assert result.neurons_created == 2

    def test_force_adds_warning_about_reingestion(self):
        """force=True on already-ingested -> result.warnings includes re-ingestion notice."""
        path = _make_jsonl_file("sess-dup2")
        conn = MagicMock()
        dedup_result = MockDedupResult(already_ingested=True, existing_neuron_count=3, session_id="sess-dup2")
        extraction = MockExtractionResult()
        creation = MockCreationResult(neuron_count=1, edge_count=0, neuron_ids=[1])

        with patch("memory_cli.ingestion.ingest_orchestrator.check_session_already_ingested",
                   return_value=dedup_result):
            with patch("memory_cli.ingestion.ingest_orchestrator.assemble_transcript_chunks",
                       return_value=["chunk"]):
                with patch("memory_cli.ingestion.ingest_orchestrator.haiku_extract",
                           return_value=extraction):
                    with patch("memory_cli.ingestion.ingest_orchestrator.create_neurons_and_edges",
                               return_value=creation):
                        with patch("memory_cli.ingestion.ingest_orchestrator.capture_context_star",
                                   return_value=(99, 1)):
                            result = ingest_session(conn, path, force=True)
        assert any("force" in w.lower() or "re-ingest" in w.lower() or "Re-ingest" in w for w in result.warnings)


class TestIngestResult:
    """Test IngestResult dataclass defaults and behavior."""

    def test_default_values(self):
        """Verify all defaults are as expected."""
        result = IngestResult()
        assert result.neurons_created == 0
        assert result.edges_created == 0
        assert result.context_neuron_id is None
        assert result.warnings == []
        assert result.session_id is None
        assert result.skipped is False

    def test_warnings_list_is_independent(self):
        """Two IngestResult instances don't share the same warnings list."""
        r1 = IngestResult()
        r2 = IngestResult()
        r1.warnings.append("x")
        assert r2.warnings == []
