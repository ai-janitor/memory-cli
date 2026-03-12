# =============================================================================
# Module: ingest_orchestrator.py
# Purpose: Main ingestion pipeline — coordinates the full flow from JSONL file
#   to graph neurons/edges. This is the single entry point for
#   `memory batch ingest <path>`.
# Rationale: The ingestion pipeline has 6 distinct phases with clear data
#   handoffs. An orchestrator keeps each phase independent and testable while
#   providing a single function that the CLI command calls. Error semantics
#   are fail-fast for critical steps (parse, extract) and warn-continue for
#   non-critical steps (individual neuron/edge creation failures).
# Responsibility:
#   - Check session dedup guard before any work
#   - Parse JSONL file into message list
#   - Assemble messages into transcript chunks
#   - Call Haiku extraction on each chunk
#   - Create neurons and edges from extraction results
#   - Build star topology context links
#   - Report summary (neurons created, edges created, warnings)
# Organization:
#   1. Imports
#   2. IngestResult — dataclass for pipeline results
#   3. IngestError — custom exception
#   4. ingest_session() — main pipeline entry point
#   5. _run_pipeline() — internal pipeline after dedup check passes
# =============================================================================

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# These are imported here so tests can patch them at the module level
# using patch("memory_cli.ingestion.ingest_orchestrator.<func>")
from .jsonl_parser_claude_code_sessions import parse_jsonl_session
from .session_dedup_guard_by_session_id import check_session_already_ingested
from .message_assembler_transcript import assemble_transcript_chunks
from .haiku_extraction_entities_facts_rels import haiku_extract, ExtractionResult
from .neuron_and_edge_creator_from_extraction import create_neurons_and_edges
from .capture_context_star_topology_edges import capture_context_star


@dataclass
class IngestResult:
    """Result summary from a complete ingestion run.

    Tracks counts of created entities and any warnings encountered
    during the pipeline. Returned to the CLI layer for user-facing output.

    Attributes:
        neurons_created: Number of neurons successfully created.
        edges_created: Number of edges successfully created (includes star edges).
        context_neuron_id: ID of the session context neuron.
        warnings: List of non-fatal warning messages.
        session_id: The session ID that was ingested.
        skipped: True if session was already ingested (dedup guard).
    """

    neurons_created: int = 0
    edges_created: int = 0
    context_neuron_id: Optional[int] = None
    warnings: List[str] = field(default_factory=list)
    session_id: Optional[str] = None
    skipped: bool = False


class IngestError(Exception):
    """Raised when the ingestion pipeline fails at a critical step.

    Attributes:
        step: Pipeline phase that failed (parse, assemble, extract, create).
        details: Human-readable failure description.
    """

    def __init__(self, step: str, details: str):
        self.step = step
        self.details = details
        super().__init__(f"[{step}] {details}")


def ingest_session(
    conn: sqlite3.Connection,
    jsonl_path: Path,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    force: bool = False,
    dry_run: bool = False,
) -> IngestResult:
    """Run the full ingestion pipeline on a JSONL session file.

    CLI: `memory batch ingest <path> [--project NAME] [--tags TAG,...]
          [--force] [--dry-run]`

    Pipeline steps:
    1. Parse JSONL file via jsonl_parser to get message list
       - Extract sessionId from first message metadata
       - Fail if file is empty or contains no valid messages
    2. Session dedup guard via check_session_already_ingested()
       - If session already ingested and not --force: return IngestResult(skipped=True)
       - If --force: log warning and proceed
    3. Assemble messages into transcript chunks via message_assembler
       - Chunks respect Haiku context window limits
       - Each chunk is a self-contained Human:/Assistant: transcript
    4. For each chunk: call Haiku extraction via haiku_extract()
       - Collect all entities, facts, relationships across chunks
       - Merge extraction results, dedup entities by ID within chunk
    5. Create neurons and edges via neuron_and_edge_creator
       - Each entity/fact becomes a neuron with ingestion metadata
       - Each relationship becomes an edge between resolved neurons
       - Non-fatal: individual creation failures are warnings
    6. Build star topology context links via capture_context_star()
       - One session context neuron linking to all created neurons
    7. If --dry-run: skip all writes, return what would have been created
    8. Return IngestResult with summary counts

    Error semantics:
    - File not found / not readable -> IngestError
    - JSONL parse yields zero valid messages -> IngestError
    - Haiku API failure -> IngestError (no partial writes)
    - Individual neuron/edge creation failure -> warning, continue
    - Session already ingested (no --force) -> IngestResult(skipped=True)

    Args:
        conn: SQLite connection with full schema.
        jsonl_path: Path to the JSONL session file.
        project: Optional project name override (else detected from messages).
        tags: Optional additional tags to apply to all created neurons.
        force: If True, re-ingest even if session was already processed.
        dry_run: If True, report what would happen without writing.

    Returns:
        IngestResult with counts, context neuron ID, and any warnings.

    Raises:
        IngestError: On critical pipeline failures.
    """
    # --- Step 1: Parse JSONL file ---
    # messages = parse_jsonl_session(jsonl_path)
    # if not messages: raise IngestError("parse", "No valid messages found")
    # session_id = messages[0].session_id or derive from filename
    try:
        parse_result = parse_jsonl_session(jsonl_path)
    except FileNotFoundError as e:
        raise IngestError("parse", f"File not found: {jsonl_path}") from e
    except PermissionError as e:
        raise IngestError("parse", f"Permission denied: {jsonl_path}") from e

    messages = parse_result.messages
    if not messages:
        raise IngestError("parse", f"No valid messages found in {jsonl_path}")

    # Extract session_id from first message or derive from filename
    session_id = None
    for msg in messages:
        if msg.session_id:
            session_id = msg.session_id
            break
    if not session_id:
        session_id = jsonl_path.stem  # use filename stem as fallback

    result = IngestResult(session_id=session_id)

    # --- Step 2: Session dedup guard ---
    # already_ingested = check_session_already_ingested(conn, session_id)
    # if already_ingested and not force:
    #     return IngestResult(skipped=True, session_id=session_id)
    # if already_ingested and force:
    #     result.warnings.append(f"Re-ingesting session {session_id} (--force)")
    dedup = check_session_already_ingested(conn, session_id)
    if dedup.already_ingested and not force:
        return IngestResult(skipped=True, session_id=session_id)
    if dedup.already_ingested and force:
        result.warnings.append(f"Re-ingesting session {session_id} (--force)")

    # --- Step 3-7: Delegate to _run_pipeline ---
    pipeline_result = _run_pipeline(
        conn, messages, session_id, project, tags, str(jsonl_path), dry_run
    )
    pipeline_result.session_id = session_id
    pipeline_result.warnings = result.warnings + pipeline_result.warnings
    return pipeline_result


def _run_pipeline(
    conn: sqlite3.Connection,
    messages: List[Any],
    session_id: str,
    project: Optional[str],
    tags: Optional[List[str]],
    source: str,
    dry_run: bool,
) -> IngestResult:
    """Internal pipeline runner after dedup check passes.

    Separated from ingest_session() so the dedup check and force logic
    stay clean in the outer function while the core pipeline is testable
    independently.

    Logic flow:
    1. Assemble transcript chunks from messages
    2. Run Haiku extraction on each chunk
    3. Merge extraction results across chunks
    4. Create neurons and edges (or simulate for dry_run)
    5. Create star topology context links
    6. Build and return IngestResult

    Args:
        conn: SQLite connection.
        messages: Parsed message list from JSONL parser.
        session_id: Extracted or derived session ID.
        project: Project name (user-provided or detected).
        tags: Additional tags to apply.
        source: Source identifier (file path).
        dry_run: If True, skip writes.

    Returns:
        IngestResult with pipeline outcomes.
    """
    result = IngestResult(session_id=session_id)

    # --- Step 1: Assemble transcript chunks ---
    # chunks = assemble_transcript_chunks(messages)
    chunks = assemble_transcript_chunks(messages)

    # --- Step 2: Haiku extraction on each chunk ---
    # all_extractions = []
    # for chunk in chunks:
    #     extraction = haiku_extract(chunk)
    #     all_extractions.append(extraction)
    all_entities: List[Any] = []
    all_facts: List[Any] = []
    all_relationships: List[Any] = []
    for chunk in chunks:
        try:
            extraction = haiku_extract(chunk)
            all_entities.extend(extraction.entities)
            all_facts.extend(extraction.facts)
            all_relationships.extend(extraction.relationships)
        except Exception as e:
            raise IngestError("extract", f"Haiku extraction failed: {e}") from e

    # Merge extraction results into single ExtractionResult
    merged = ExtractionResult(
        entities=all_entities,
        facts=all_facts,
        relationships=all_relationships,
    )

    # --- Step 3: Create neurons and edges (or simulate for dry_run) ---
    if dry_run:
        # Report what would be created without writing
        result.neurons_created = len(all_entities) + len(all_facts)
        result.edges_created = len(all_relationships)
        return result

    created = create_neurons_and_edges(
        conn, merged, source=source,
        project=project, tags=tags, session_id=session_id
    )
    result.neurons_created = created.neuron_count
    result.edges_created = created.edge_count
    result.warnings.extend(created.warnings)

    # --- Step 4: Star topology context links ---
    if created.neuron_ids:
        ctx_neuron_id, star_edge_count = capture_context_star(
            conn, session_id, created.neuron_ids, project=project
        )
        result.context_neuron_id = ctx_neuron_id
        result.edges_created += star_edge_count

    return result
