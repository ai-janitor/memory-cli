# Conversation Ingestion from JSONL

Covers: parsing Claude Code session transcript files (JSONL format from .claude/
session files), calling Haiku to extract entities, facts, and relationships from
the conversation, creating neurons from extracted entities/facts, creating edges
from extracted relationships (with reasons), bulk operation via `memory batch
ingest` command, source attribution tracking.

Requirements traced: §3.2 Conversation Ingestion.
Dependencies: #6 Neuron CRUD, #7 Edge Management, #5 Embedding, #2 Config (Haiku API key).
