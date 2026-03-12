# =============================================================================
# Package: tests.ingestion
# Purpose: Test suite for the conversation ingestion pipeline (Spec #11).
#   Covers JSONL parsing, transcript assembly, Haiku extraction, neuron/edge
#   creation, star topology context, and session dedup guard.
# Rationale: Ingestion is the highest-complexity write path — it coordinates
#   6 stages with external API calls, ID resolution, and error recovery.
#   Thorough testing of each stage in isolation plus integration tests of
#   the orchestrator ensures correctness and resilience.
# Organization:
#   test_ingest_orchestrator.py — Full pipeline, dry-run, error propagation
#   test_jsonl_parser.py — JSONL parsing: valid, invalid, type filtering
#   test_message_assembler.py — Transcript format, ordering, chunking
#   test_haiku_extraction.py — API call mocking, response parsing
#   test_neuron_edge_creator.py — Neuron/edge creation, ID resolution
#   test_capture_context_star.py — Star topology, weight 0.5
#   test_session_dedup.py — Dedup detection, --force override
# =============================================================================
