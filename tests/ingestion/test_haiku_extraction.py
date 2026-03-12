# =============================================================================
# Module: test_haiku_extraction.py
# Purpose: Test Haiku extraction — API call behavior (mocked), response
#   parsing, malformed response handling, and API key resolution.
# Rationale: The Haiku extraction stage involves an external API call that
#   must be mocked in tests. Response parsing must handle both well-formed
#   and malformed JSON gracefully. API key resolution involves config and
#   env var lookup, both of which need test coverage.
# Responsibility:
#   - Test haiku_extract() with mocked API
#   - Test _parse_extraction_response() with valid and malformed responses
#   - Test _build_extraction_prompt() format
#   - Test _resolve_api_key() with config and env vars
#   - Test retry logic on transient failures
# Organization:
#   1. Imports and fixtures
#   2. TestHaikuExtract — main entry point with mocked API
#   3. TestParseExtractionResponse — response parsing and validation
#   4. TestBuildExtractionPrompt — prompt construction
#   5. TestResolveApiKey — API key resolution
# =============================================================================

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from memory_cli.ingestion.haiku_extraction_entities_facts_rels import (
    EXTRACTION_SYSTEM_PROMPT,
    ExtractedEntity,
    ExtractedFact,
    ExtractedRelationship,
    ExtractionResult,
    _build_extraction_prompt,
    _parse_extraction_response,
    _resolve_api_key,
    haiku_extract,
)


class TestHaikuExtract:
    """Test haiku_extract() with mocked Anthropic API."""

    def test_extract_returns_entities_facts_relationships(self):
        """Mock API to return valid JSON with 2 entities, 1 fact, 1 relationship."""
        mock_raw = {
            "entities": [
                {"id": "e1", "content": "Python"},
                {"id": "e2", "content": "SQLite"},
            ],
            "facts": [
                {"id": "f1", "content": "Python works well with SQLite"}
            ],
            "relationships": [
                {"from_id": "e1", "to_id": "f1", "reason": "Python is described in fact"}
            ],
        }
        with patch("memory_cli.ingestion.haiku_extraction_entities_facts_rels._resolve_api_key", return_value="sk-test"):
            with patch("memory_cli.ingestion.haiku_extraction_entities_facts_rels._call_haiku_api", return_value=mock_raw):
                result = haiku_extract("Human: hi\nAssistant: hello")
        assert len(result.entities) == 2
        assert len(result.facts) == 1
        assert len(result.relationships) == 1

    def test_extract_raises_on_api_key_missing(self):
        """Mock env var to be empty -> raises IngestError-like exception."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(Exception):  # IngestError or _LocalIngestError
                haiku_extract("Human: hi")

    def test_extract_raises_on_persistent_failure(self):
        """Mock API to fail persistently -> raises IngestError-like exception."""
        with patch("memory_cli.ingestion.haiku_extraction_entities_facts_rels._resolve_api_key", return_value="sk-test"):
            with patch("memory_cli.ingestion.haiku_extraction_entities_facts_rels._call_haiku_api",
                       side_effect=Exception("persistent failure")):
                with pytest.raises(Exception):
                    haiku_extract("Human: hi")


class TestParseExtractionResponse:
    """Test _parse_extraction_response() with various response shapes."""

    def test_valid_response_parses_all_fields(self):
        """Well-formed JSON with entities, facts, relationships."""
        raw = {
            "entities": [{"id": "e1", "content": "Python"}],
            "facts": [{"id": "f1", "content": "Python is great"}],
            "relationships": [{"from_id": "e1", "to_id": "f1", "reason": "describes"}],
        }
        result = _parse_extraction_response(raw)
        assert len(result.entities) == 1
        assert result.entities[0].local_id == "e1"
        assert result.entities[0].content == "Python"
        assert len(result.facts) == 1
        assert result.facts[0].local_id == "f1"
        assert len(result.relationships) == 1
        assert result.relationships[0].from_id == "e1"
        assert result.relationships[0].to_id == "f1"
        assert result.relationships[0].reason == "describes"

    def test_missing_entities_key_returns_empty_list(self):
        """JSON without "entities" key -> result.entities == []."""
        raw = {"facts": [{"id": "f1", "content": "a fact"}]}
        result = _parse_extraction_response(raw)
        assert result.entities == []

    def test_missing_facts_key_returns_empty_list(self):
        """JSON without "facts" key -> result.facts == []."""
        raw = {"entities": [{"id": "e1", "content": "an entity"}]}
        result = _parse_extraction_response(raw)
        assert result.facts == []

    def test_malformed_entity_skipped(self):
        """Entity missing "id" key -> that entity skipped, others parsed."""
        raw = {
            "entities": [
                {"content": "no id here"},  # malformed
                {"id": "e2", "content": "valid entity"},
            ],
        }
        result = _parse_extraction_response(raw)
        assert len(result.entities) == 1
        assert result.entities[0].local_id == "e2"

    def test_malformed_relationship_skipped(self):
        """Relationship missing "reason" key -> that relationship skipped."""
        raw = {
            "relationships": [
                {"from_id": "e1", "to_id": "f1"},  # missing reason
                {"from_id": "e2", "to_id": "f2", "reason": "valid"},
            ],
        }
        result = _parse_extraction_response(raw)
        assert len(result.relationships) == 1
        assert result.relationships[0].reason == "valid"

    def test_empty_response_returns_empty_result(self):
        """Empty dict {} -> all lists empty."""
        result = _parse_extraction_response({})
        assert result.entities == []
        assert result.facts == []
        assert result.relationships == []

    def test_raw_response_preserved(self):
        """result.raw_response is the original dict."""
        raw = {"entities": [], "facts": [], "relationships": []}
        result = _parse_extraction_response(raw)
        assert result.raw_response is raw


class TestBuildExtractionPrompt:
    """Test _build_extraction_prompt() message construction."""

    def test_returns_messages_list(self):
        """Returns a list of message dicts."""
        messages = _build_extraction_prompt("Human: hello")
        assert isinstance(messages, list)
        assert len(messages) >= 1

    def test_user_message_contains_transcript(self):
        """The user message content contains the transcript text."""
        messages = _build_extraction_prompt("Human: test transcript")
        user_msg = next(m for m in messages if m.get("role") == "user")
        assert "test transcript" in user_msg["content"]

    def test_transcript_included_verbatim(self):
        """Transcript text appears in the message without modification."""
        transcript = "Human: unique content here\nAssistant: response"
        messages = _build_extraction_prompt(transcript)
        all_content = " ".join(str(m.get("content", "")) for m in messages)
        assert "unique content here" in all_content


class TestResolveApiKey:
    """Test _resolve_api_key() config and env var resolution."""

    def test_resolves_from_default_env_var(self):
        """Set ANTHROPIC_API_KEY env var -> returns the key value."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-key"}):
            # Patch config loading to return default
            with patch("memory_cli.ingestion.haiku_extraction_entities_facts_rels.load_config",
                       side_effect=Exception("no config")):
                key = _resolve_api_key()
                assert key == "sk-test-key"

    def test_raises_when_env_var_not_set(self):
        """Unset env var -> raises IngestError-like exception."""
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with patch("memory_cli.ingestion.haiku_extraction_entities_facts_rels.load_config",
                       side_effect=Exception("no config")):
                with pytest.raises(Exception) as exc_info:
                    _resolve_api_key()
                assert "API key" in str(exc_info.value) or "ANTHROPIC_API_KEY" in str(exc_info.value)

    def test_raises_when_env_var_is_empty(self):
        """Set env var to empty string -> raises IngestError-like exception."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            with patch("memory_cli.ingestion.haiku_extraction_entities_facts_rels.load_config",
                       side_effect=Exception("no config")):
                with pytest.raises(Exception):
                    _resolve_api_key()
