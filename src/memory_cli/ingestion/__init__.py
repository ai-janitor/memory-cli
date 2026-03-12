# =============================================================================
# Package: memory_cli.ingestion
# Purpose: Conversation ingestion pipeline — parse Claude Code JSONL sessions,
#   extract entities/facts/relationships via Haiku, and create neurons/edges
#   in the memory graph. Entry point: `memory batch ingest <path>`.
# Rationale: Ingestion is the primary write path for bulk knowledge capture.
#   A Claude Code session contains rich conversational context — decisions,
#   findings, constraints, tool usage — that must be decomposed into discrete
#   graph nodes and relationships. Isolating this pipeline lets it evolve
#   independently (new source formats, different LLM extractors) without
#   touching core neuron/edge CRUD.
# Responsibility:
#   - JSONL parsing: line-by-line extraction of user/assistant messages
#   - Transcript assembly: reconstruct Human:/Assistant: turns, chunk if needed
#   - Haiku extraction: call Haiku to extract entities, facts, relationships
#   - Neuron/edge creation: map extracted items to graph primitives
#   - Context capture: star topology linking all session neurons to a context node
#   - Session dedup: prevent double-ingestion of the same session
# Organization:
#   ingest_orchestrator.py — Main pipeline: parse → assemble → extract → create → link
#   jsonl_parser_claude_code_sessions.py — Line-by-line JSONL parsing, type filtering
#   message_assembler_transcript.py — Build Human:/Assistant: transcript, chunking
#   haiku_extraction_entities_facts_rels.py — Haiku API call, structured extraction
#   neuron_and_edge_creator_from_extraction.py — Map extractions to neurons/edges
#   capture_context_star_topology_edges.py — Session context neuron + star edges
#   session_dedup_guard_by_session_id.py — Duplicate session detection + --force
# =============================================================================

# --- Public API exports ---
# These will be the primary entry points consumed by CLI commands.

from .ingest_orchestrator import ingest_session
from .session_dedup_guard_by_session_id import check_session_already_ingested
