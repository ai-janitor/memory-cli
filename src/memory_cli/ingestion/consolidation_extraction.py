# =============================================================================
# Module: consolidation_extraction.py
# Purpose: Call Haiku to extract entities, facts, and relationships from an
#   existing neuron's content blob. This is the consolidation counterpart to
#   haiku_extraction_entities_facts_rels.py (which extracts from conversation
#   transcripts). Returns the same ExtractionResult type for downstream reuse.
# Rationale: Neuron content is structurally different from conversation
#   transcripts — it's typically a single knowledge blob, not Human:/Assistant:
#   turns. The extraction prompt must be tuned accordingly to extract entities,
#   facts, and relationships from freeform text rather than conversational flow.
# Responsibility:
#   - Build a consolidation-specific prompt for neuron content
#   - Call Haiku API (reusing existing API call + parse infrastructure)
#   - Return ExtractionResult with entities, facts, relationships
# Organization:
#   1. Imports
#   2. Constants (consolidation-specific prompt)
#   3. consolidation_extract() — main entry point
#   4. _build_consolidation_prompt() — prompt construction
# =============================================================================

from __future__ import annotations

from typing import Any, Dict, List

from .haiku_extraction_entities_facts_rels import (
    ExtractionResult,
    HAIKU_MODEL,
    MAX_TOKENS,
    _call_haiku_api,
    _parse_extraction_response,
    _resolve_api_key,
)


# -----------------------------------------------------------------------------
# Constants — consolidation-specific prompt for neuron content extraction.
# Different from the ingestion prompt: optimized for standalone knowledge blobs.
# -----------------------------------------------------------------------------
CONSOLIDATION_SYSTEM_PROMPT = """You are an extraction engine. Given a knowledge note or memory entry, extract:
1. **Entities**: people, systems, tools, libraries, projects, concepts, organizations mentioned.
2. **Facts**: decisions, findings, constraints, conclusions, rules, preferences stated.
3. **Relationships**: connections between entities/facts with a reason.

Output ONLY valid JSON with this exact structure:
{
  "entities": [{"id": "<unique-id>", "content": "<description>"}],
  "facts": [{"id": "<unique-id>", "content": "<fact statement>"}],
  "relationships": [{"from_id": "<id>", "to_id": "<id>", "reason": "<why related>"}]
}

Rules:
- IDs must be short, unique strings (e.g., "e1", "e2", "f1", "f2")
- Entity content should be a clear, concise description
- Fact content should be a complete, standalone statement
- Relationships must reference IDs from the entities or facts lists
- Extract ALL meaningful entities and facts, not just a few
- If the text is very short or has no extractable structure, return empty lists
- Do not fabricate entities or facts not present in the source text"""


class ConsolidationError(Exception):
    """Raised when consolidation extraction fails.

    Attributes:
        step: Which step failed (resolve_key, extract, parse).
        details: Human-readable description of the failure.
    """

    def __init__(self, step: str, details: str):
        self.step = step
        self.details = details
        super().__init__(f"[consolidation:{step}] {details}")


def consolidation_extract(neuron_content: str) -> ExtractionResult:
    """Extract entities, facts, and relationships from a neuron's content.

    Main entry point for the consolidation extraction stage. Reuses the
    Haiku API infrastructure from the ingestion pipeline but with a
    consolidation-specific prompt tuned for standalone knowledge blobs.

    Logic flow:
    1. Resolve API key via _resolve_api_key() (shared with ingestion)
    2. Build consolidation prompt via _build_consolidation_prompt(neuron_content)
    3. Call Haiku API via _call_haiku_api() (shared with ingestion)
    4. Parse response via _parse_extraction_response() (shared with ingestion)
    5. Return ExtractionResult

    Args:
        neuron_content: The neuron's content text to extract from.

    Returns:
        ExtractionResult with extracted entities, facts, relationships.

    Raises:
        ConsolidationError: On API key issues or persistent API failures.
    """
    try:
        api_key = _resolve_api_key()
    except Exception as e:
        raise ConsolidationError("resolve_key", str(e)) from e

    messages = _build_consolidation_prompt(neuron_content)

    try:
        raw_response = _call_haiku_api(api_key, messages, system_prompt=CONSOLIDATION_SYSTEM_PROMPT)
    except Exception as e:
        raise ConsolidationError("extract", f"Haiku API failure: {e}") from e

    result = _parse_extraction_response(raw_response)
    return result


def _build_consolidation_prompt(neuron_content: str) -> List[Dict[str, str]]:
    """Construct the messages list for the consolidation Haiku API call.

    The prompt uses CONSOLIDATION_SYSTEM_PROMPT (not the ingestion one)
    and wraps the neuron content as the user message.

    Args:
        neuron_content: The neuron's content text.

    Returns:
        List of message dicts for the Anthropic API.
    """
    return [
        {
            "role": "user",
            "content": (
                "Extract entities, facts, and relationships from this "
                "knowledge entry:\n\n"
                f"{neuron_content}"
            ),
        }
    ]
