# =============================================================================
# Module: haiku_extraction_entities_facts_rels.py
# Purpose: Call Haiku to extract entities, facts, and relationships from a
#   conversation transcript chunk. Returns structured JSON that downstream
#   stages map to neurons and edges.
# Rationale: Entity/fact/relationship extraction is the core intelligence step
#   in the ingestion pipeline. Haiku is cost-effective for this extraction task
#   and produces structured output reliably with proper prompting. Isolating
#   the API call, prompt construction, and response parsing here makes it easy
#   to swap models, tune prompts, or add retry logic without touching the
#   pipeline orchestration.
# Responsibility:
#   - Load API key from config (haiku.api_key_env_var -> env var lookup)
#   - Construct the extraction prompt with the transcript chunk
#   - Call the Haiku API with structured output request
#   - Parse and validate the response JSON
#   - Return typed ExtractionResult with entities, facts, relationships
# Organization:
#   1. Imports
#   2. Data classes (ExtractedEntity, ExtractedFact, ExtractedRelationship,
#      ExtractionResult)
#   3. Constants (model name, prompt template)
#   4. haiku_extract() — main entry point
#   5. _build_extraction_prompt() — construct the full prompt
#   6. _call_haiku_api() — HTTP call to Anthropic API
#   7. _parse_extraction_response() — validate and parse JSON response
#   8. _resolve_api_key() — config -> env var -> key string
# =============================================================================

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from ..config.config_loader_and_validator import load_config
except ImportError:
    load_config = None  # type: ignore


@dataclass
class ExtractedEntity:
    """An entity extracted by Haiku from a transcript.

    Entities are people, systems, tools, libraries, concepts, or any
    named thing mentioned in the conversation.

    Attributes:
        local_id: Haiku-assigned ID for cross-referencing within this extraction.
        content: Description of the entity.
    """

    local_id: str
    content: str


@dataclass
class ExtractedFact:
    """A fact extracted by Haiku from a transcript.

    Facts are decisions, findings, constraints, conclusions, or any
    discrete piece of knowledge from the conversation.

    Attributes:
        local_id: Haiku-assigned ID for cross-referencing within this extraction.
        content: The fact statement.
    """

    local_id: str
    content: str


@dataclass
class ExtractedRelationship:
    """A relationship between two extracted items.

    Links an entity or fact to another entity or fact, with a reason
    describing the nature of the relationship.

    Attributes:
        from_id: Local ID of the source entity/fact.
        to_id: Local ID of the target entity/fact.
        reason: Human-readable description of the relationship.
    """

    from_id: str
    to_id: str
    reason: str


@dataclass
class ExtractionResult:
    """Complete extraction result from a single Haiku call.

    Contains all entities, facts, and relationships extracted from
    one transcript chunk.

    Attributes:
        entities: List of extracted entities.
        facts: List of extracted facts.
        relationships: List of extracted relationships.
        raw_response: The raw JSON response for debugging.
    """

    entities: List[ExtractedEntity] = field(default_factory=list)
    facts: List[ExtractedFact] = field(default_factory=list)
    relationships: List[ExtractedRelationship] = field(default_factory=list)
    raw_response: Optional[Dict[str, Any]] = None


# -----------------------------------------------------------------------------
# Constants — model configuration and prompt template.
# -----------------------------------------------------------------------------
HAIKU_MODEL = "claude-haiku-4-20250414"
MAX_TOKENS = 4096

# The extraction prompt instructs Haiku to produce structured JSON.
# Placeholders: {transcript} will be filled with the actual transcript chunk.
EXTRACTION_SYSTEM_PROMPT = """You are an extraction engine. Given a conversation transcript, extract:
1. **Entities**: people, systems, tools, libraries, projects, concepts mentioned.
2. **Facts**: decisions made, findings discovered, constraints identified, conclusions reached.
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
- Do not include trivial conversational artifacts (greetings, acknowledgments)"""


# Local error class to avoid circular import with ingest_orchestrator
# IngestError is the canonical class defined in ingest_orchestrator.py.
# We use a late import when raising to use the actual IngestError.
class _LocalIngestError(Exception):
    """Local placeholder until ingest_orchestrator.IngestError can be imported."""
    def __init__(self, step: str, details: str):
        self.step = step
        self.details = details
        super().__init__(f"[{step}] {details}")


def haiku_extract(transcript_chunk: str) -> ExtractionResult:
    """Extract entities, facts, and relationships from a transcript chunk.

    Main entry point for the Haiku extraction stage. Handles the full
    flow: resolve API key, build prompt, call API, parse response.

    Logic flow:
    1. Resolve API key via _resolve_api_key()
       - Raises IngestError if key not configured or env var not set
    2. Build extraction prompt via _build_extraction_prompt(transcript_chunk)
    3. Call Haiku API via _call_haiku_api(api_key, prompt)
       - Retry once on transient errors (5xx, timeout)
       - Raise IngestError on persistent failure
    4. Parse response via _parse_extraction_response(raw_response)
       - Validate JSON structure
       - Handle malformed responses gracefully (warn + return partial)
    5. Return ExtractionResult

    Args:
        transcript_chunk: A Human:/Assistant: transcript string to extract from.

    Returns:
        ExtractionResult with extracted entities, facts, relationships.

    Raises:
        IngestError: On API key issues or persistent API failures.
    """
    # --- Step 1: Resolve API key ---
    # api_key = _resolve_api_key()
    api_key = _resolve_api_key()

    # --- Step 2: Build prompt ---
    # messages = _build_extraction_prompt(transcript_chunk)
    messages = _build_extraction_prompt(transcript_chunk)

    # --- Step 3: Call Haiku API ---
    # raw_response = _call_haiku_api(api_key, messages)
    raw_response = _call_haiku_api(api_key, messages)

    # --- Step 4: Parse response ---
    # result = _parse_extraction_response(raw_response)
    result = _parse_extraction_response(raw_response)

    # --- Step 5: Return ---
    # return result
    return result


def _build_extraction_prompt(transcript_chunk: str) -> List[Dict[str, str]]:
    """Construct the messages list for the Haiku API call.

    The prompt consists of:
    - System message with extraction instructions (passed separately via system param)
    - User message with the actual transcript

    Args:
        transcript_chunk: The transcript text to include in the user message.

    Returns:
        List of message dicts for the Anthropic API.
    """
    # --- Build messages list ---
    # return [
    #     {"role": "user", "content": f"Extract entities, facts, and relationships from this conversation:\n\n{transcript_chunk}"}
    # ]
    # Note: system prompt is passed separately in the API call, not as a message
    return [
        {
            "role": "user",
            "content": f"Extract entities, facts, and relationships from this conversation:\n\n{transcript_chunk}",
        }
    ]


def _call_haiku_api(
    api_key: str,
    messages: List[Dict[str, str]],
    system_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Call the Anthropic API with Haiku model.

    Uses the anthropic Python SDK if available, falls back to httpx/requests.

    Logic flow:
    1. Create Anthropic client with api_key
    2. Call client.messages.create(
           model=HAIKU_MODEL,
           max_tokens=MAX_TOKENS,
           system=system_prompt or EXTRACTION_SYSTEM_PROMPT,
           messages=messages
       )
    3. Extract text content from response
    4. Parse text as JSON
    5. Return parsed dict

    Retry logic:
    - On 5xx status or timeout: wait 2s, retry once
    - On 4xx (auth, rate limit): raise immediately
    - On second failure: raise IngestError

    Args:
        api_key: Anthropic API key.
        messages: Messages list for the API.
        system_prompt: Optional override for the system prompt.
            Defaults to EXTRACTION_SYSTEM_PROMPT if not provided.

    Returns:
        Parsed JSON dict from Haiku's response.

    Raises:
        IngestError: On persistent API failures.
    """
    # --- Create client and call API ---
    # import anthropic
    # client = anthropic.Anthropic(api_key=api_key)
    # response = client.messages.create(
    #     model=HAIKU_MODEL, max_tokens=MAX_TOKENS,
    #     system=EXTRACTION_SYSTEM_PROMPT, messages=messages
    # )
    import anthropic as _anthropic
    effective_system_prompt = system_prompt if system_prompt is not None else EXTRACTION_SYSTEM_PROMPT

    def _do_call() -> Dict[str, Any]:
        client = _anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=MAX_TOKENS,
            system=effective_system_prompt,
            messages=messages,
        )
        response_text = response.content[0].text
        return json.loads(response_text)

    try:
        return _do_call()
    except (_anthropic.APIStatusError,) as e:
        # If it's a 4xx, fail immediately
        if hasattr(e, "status_code") and 400 <= e.status_code < 500:
            try:
                from .ingest_orchestrator import IngestError
            except ImportError:
                IngestError = _LocalIngestError  # type: ignore
            raise IngestError("extract", f"Haiku API error: {e}") from e
        # On 5xx or timeout: retry once
        import time
        time.sleep(2)
        try:
            return _do_call()
        except Exception as e2:
            try:
                from .ingest_orchestrator import IngestError
            except ImportError:
                IngestError = _LocalIngestError  # type: ignore
            raise IngestError("extract", f"Haiku API persistent failure: {e2}") from e2
    except Exception as e:
        # On any other error: retry once
        import time
        time.sleep(2)
        try:
            return _do_call()
        except Exception as e2:
            try:
                from .ingest_orchestrator import IngestError
            except ImportError:
                IngestError = _LocalIngestError  # type: ignore
            raise IngestError("extract", f"Haiku API persistent failure: {e2}") from e2

    # --- Extract and parse response text ---
    # response_text = response.content[0].text
    # return json.loads(response_text)


def _parse_extraction_response(raw: Dict[str, Any]) -> ExtractionResult:
    """Validate and parse the raw Haiku response into an ExtractionResult.

    Handles malformed responses gracefully — missing fields get empty lists,
    individual malformed items are skipped with warnings logged.

    Logic flow:
    1. Extract "entities" list from raw (default: [])
       - For each item: validate has "id" and "content" keys
       - Create ExtractedEntity for valid items, skip invalid
    2. Extract "facts" list from raw (default: [])
       - For each item: validate has "id" and "content" keys
       - Create ExtractedFact for valid items, skip invalid
    3. Extract "relationships" list from raw (default: [])
       - For each item: validate has "from_id", "to_id", "reason" keys
       - Create ExtractedRelationship for valid items, skip invalid
    4. Return ExtractionResult with parsed lists and raw_response

    Args:
        raw: Parsed JSON dict from Haiku's response.

    Returns:
        ExtractionResult with validated entities, facts, relationships.
    """
    # --- Parse entities ---
    # entities = []
    # for item in raw.get("entities", []):
    #     if "id" in item and "content" in item:
    #         entities.append(ExtractedEntity(local_id=item["id"], content=item["content"]))
    entities: List[ExtractedEntity] = []
    for item in raw.get("entities", []):
        if isinstance(item, dict) and "id" in item and "content" in item:
            entities.append(ExtractedEntity(local_id=item["id"], content=item["content"]))

    # --- Parse facts ---
    # facts = []
    # for item in raw.get("facts", []):
    #     if "id" in item and "content" in item:
    #         facts.append(ExtractedFact(local_id=item["id"], content=item["content"]))
    facts: List[ExtractedFact] = []
    for item in raw.get("facts", []):
        if isinstance(item, dict) and "id" in item and "content" in item:
            facts.append(ExtractedFact(local_id=item["id"], content=item["content"]))

    # --- Parse relationships ---
    # relationships = []
    # for item in raw.get("relationships", []):
    #     if "from_id" in item and "to_id" in item and "reason" in item:
    #         relationships.append(ExtractedRelationship(
    #             from_id=item["from_id"], to_id=item["to_id"], reason=item["reason"]
    #         ))
    relationships: List[ExtractedRelationship] = []
    for item in raw.get("relationships", []):
        if isinstance(item, dict) and "from_id" in item and "to_id" in item and "reason" in item:
            relationships.append(ExtractedRelationship(
                from_id=item["from_id"], to_id=item["to_id"], reason=item["reason"]
            ))

    # --- Return result ---
    # return ExtractionResult(
    #     entities=entities, facts=facts,
    #     relationships=relationships, raw_response=raw
    # )
    return ExtractionResult(
        entities=entities,
        facts=facts,
        relationships=relationships,
        raw_response=raw,
    )


def _resolve_api_key() -> str:
    """Resolve the Anthropic API key from config and environment.

    Logic flow:
    1. Load config to get haiku.api_key_env_var setting
       - Default env var name: "ANTHROPIC_API_KEY"
    2. Look up the env var value from os.environ
    3. If not found or empty: raise IngestError with helpful message
    4. Return the API key string

    Returns:
        The Anthropic API key string.

    Raises:
        IngestError: If API key is not configured or env var is not set.
    """
    # --- Load config for env var name ---
    # env_var_name = config.haiku.api_key_env_var (or default "ANTHROPIC_API_KEY")
    env_var_name = "ANTHROPIC_API_KEY"
    try:
        if load_config is not None:
            cfg = load_config()
            try:
                env_var_name = cfg.haiku.api_key_env_var
            except AttributeError:
                env_var_name = cfg.get("haiku", {}).get("api_key_env_var", "ANTHROPIC_API_KEY")
    except Exception:
        pass  # Use default

    # --- Look up env var ---
    # import os
    # api_key = os.environ.get(env_var_name, "").strip()
    # if not api_key:
    #     raise IngestError("extract", f"API key not found in ${env_var_name}")
    api_key = os.environ.get(env_var_name, "").strip()
    if not api_key:
        try:
            from .ingest_orchestrator import IngestError
        except ImportError:
            IngestError = _LocalIngestError  # type: ignore
        raise IngestError("extract", f"API key not found in ${env_var_name}")

    # return api_key
    return api_key
