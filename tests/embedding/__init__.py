# =============================================================================
# tests.embedding — Test suite for the embedding engine package
# =============================================================================
# Purpose:     Contains all tests for the embedding subsystem: model loading,
#              task prefixes, input construction, single/batch embedding,
#              vector storage, staleness detection, batch re-embed, and
#              dimension enforcement.
# Rationale:   Mirrors the src/memory_cli/embedding/ package structure.
#              Each source module has a corresponding test module.
# Organization:
#   test_model_loader.py              — lazy load, singleton, missing file, config
#   test_task_prefix.py               — prefix values, prepend logic
#   test_embedding_input_construction.py — content+tags assembly
#   test_embed_single_and_batch.py    — single/batch embed, empty, normalization
#   test_vector_storage.py            — vec0 write, binary format, atomic timestamp
#   test_stale_blank_detection.py     — blank/stale queries, filters
#   test_batch_reembed.py             — full re-embed flow, progress, partial
#   test_dimension_enforcement.py     — correct dims pass, wrong dims rejected
# =============================================================================
