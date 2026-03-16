# =============================================================================
# Module: test_consolidation_extraction.py
# Purpose: Test consolidation extraction — Haiku API call (mocked), prompt
#   construction, and error handling for neuron content extraction.
# Rationale: The consolidation extraction reuses Haiku infrastructure but
#   with a different prompt. Tests verify the prompt is correct, the API
#   is called with the consolidation system prompt, and errors are wrapped
#   in ConsolidationError.
# Organization:
#   1. Imports and fixtures
#   2. TestConsolidationExtract — main entry point with mocked API
#   3. TestBuildConsolidationPrompt — prompt construction
#   4. TestConsolidationError — error wrapping
# =============================================================================

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch, call

import pytest

from memory_cli.ingestion.consolidation_extraction import (
    CONSOLIDATION_SYSTEM_PROMPT,
    ConsolidationError,
    consolidation_extract,
    _build_consolidation_prompt,
)
from memory_cli.ingestion.haiku_extraction_entities_facts_rels import (
    ExtractionResult,
    ExtractedEntity,
    ExtractedFact,
    ExtractedRelationship,
)


class TestConsolidationExtract:
    """Test consolidation_extract() with mocked Haiku API."""

    def test_extract_returns_entities_facts_relationships(self):
        """Mock API to return valid JSON with entities, facts, relationships."""
        mock_raw = {
            "entities": [
                {"id": "e1", "content": "Python programming language"},
                {"id": "e2", "content": "SQLite database"},
            ],
            "facts": [
                {"id": "f1", "content": "Python integrates well with SQLite"},
            ],
            "relationships": [
                {"from_id": "e1", "to_id": "f1", "reason": "Python is subject of fact"},
            ],
        }
        with patch(
            "memory_cli.ingestion.consolidation_extraction._resolve_api_key",
            return_value="sk-test",
        ):
            with patch(
                "memory_cli.ingestion.consolidation_extraction._call_haiku_api",
                return_value=mock_raw,
            ) as mock_call:
                result = consolidation_extract("Python works well with SQLite for embedded databases.")

        assert len(result.entities) == 2
        assert len(result.facts) == 1
        assert len(result.relationships) == 1
        assert result.entities[0].local_id == "e1"
        assert result.entities[0].content == "Python programming language"

    def test_extract_passes_consolidation_system_prompt(self):
        """Haiku API called with CONSOLIDATION_SYSTEM_PROMPT, not ingestion prompt."""
        mock_raw = {"entities": [], "facts": [], "relationships": []}
        with patch(
            "memory_cli.ingestion.consolidation_extraction._resolve_api_key",
            return_value="sk-test",
        ):
            with patch(
                "memory_cli.ingestion.consolidation_extraction._call_haiku_api",
                return_value=mock_raw,
            ) as mock_call:
                consolidation_extract("Some content")

        # Verify system_prompt kwarg was passed
        mock_call.assert_called_once()
        _, kwargs = mock_call.call_args
        assert kwargs.get("system_prompt") == CONSOLIDATION_SYSTEM_PROMPT

    def test_extract_raises_consolidation_error_on_api_key_missing(self):
        """Missing API key raises ConsolidationError with step='resolve_key'."""
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with patch(
                "memory_cli.ingestion.haiku_extraction_entities_facts_rels.load_config",
                side_effect=Exception("no config"),
            ):
                with pytest.raises(ConsolidationError) as exc_info:
                    consolidation_extract("Some content")
                assert exc_info.value.step == "resolve_key"

    def test_extract_raises_consolidation_error_on_api_failure(self):
        """Persistent API failure raises ConsolidationError with step='extract'."""
        with patch(
            "memory_cli.ingestion.consolidation_extraction._resolve_api_key",
            return_value="sk-test",
        ):
            with patch(
                "memory_cli.ingestion.consolidation_extraction._call_haiku_api",
                side_effect=Exception("API down"),
            ):
                with pytest.raises(ConsolidationError) as exc_info:
                    consolidation_extract("Some content")
                assert exc_info.value.step == "extract"

    def test_extract_returns_empty_result_for_empty_response(self):
        """Empty Haiku response -> ExtractionResult with empty lists."""
        mock_raw = {}
        with patch(
            "memory_cli.ingestion.consolidation_extraction._resolve_api_key",
            return_value="sk-test",
        ):
            with patch(
                "memory_cli.ingestion.consolidation_extraction._call_haiku_api",
                return_value=mock_raw,
            ):
                result = consolidation_extract("Trivial content")

        assert result.entities == []
        assert result.facts == []
        assert result.relationships == []


class TestBuildConsolidationPrompt:
    """Test _build_consolidation_prompt() message construction."""

    def test_returns_messages_list(self):
        """Returns a list of message dicts."""
        messages = _build_consolidation_prompt("Some knowledge")
        assert isinstance(messages, list)
        assert len(messages) >= 1

    def test_user_message_contains_content(self):
        """The user message content contains the neuron content."""
        messages = _build_consolidation_prompt("Python is a programming language")
        user_msg = next(m for m in messages if m.get("role") == "user")
        assert "Python is a programming language" in user_msg["content"]

    def test_user_message_has_knowledge_entry_framing(self):
        """The prompt frames the content as a knowledge entry, not a conversation."""
        messages = _build_consolidation_prompt("test content")
        user_msg = next(m for m in messages if m.get("role") == "user")
        assert "knowledge entry" in user_msg["content"]

    def test_system_prompt_differs_from_ingestion(self):
        """CONSOLIDATION_SYSTEM_PROMPT is different from EXTRACTION_SYSTEM_PROMPT."""
        from memory_cli.ingestion.haiku_extraction_entities_facts_rels import (
            EXTRACTION_SYSTEM_PROMPT,
        )
        assert CONSOLIDATION_SYSTEM_PROMPT != EXTRACTION_SYSTEM_PROMPT

    def test_system_prompt_mentions_knowledge_note(self):
        """Consolidation prompt is tuned for knowledge notes, not transcripts."""
        assert "knowledge note" in CONSOLIDATION_SYSTEM_PROMPT or "memory entry" in CONSOLIDATION_SYSTEM_PROMPT


class TestConsolidationError:
    """Test ConsolidationError attributes."""

    def test_has_step_and_details(self):
        """ConsolidationError stores step and details."""
        err = ConsolidationError("extract", "API failed")
        assert err.step == "extract"
        assert err.details == "API failed"
        assert "consolidation:extract" in str(err)

    def test_is_exception(self):
        """ConsolidationError is an Exception subclass."""
        assert issubclass(ConsolidationError, Exception)
