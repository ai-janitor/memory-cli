# Embedding Engine

Covers: llama-cpp-python wrapper for in-process embedding, model loading
(nomic-embed-text-v1.5 Q8_0 GGUF, 768 dims), task prefix handling (search_document:
for indexing, search_query: for queries), single and batch embed() calls, vector
storage to vec0 table, batch re-embed (finds blank and stale vectors), embedding
decoupled from storage (can store without embedding, re-embed later), model loads
once per CLI invocation.

Requirements traced: §8 Embedding.
Dependencies: #2 Config (model path, settings), #3 Schema (vec0 table).
