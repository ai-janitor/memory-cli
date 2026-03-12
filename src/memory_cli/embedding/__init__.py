# =============================================================================
# memory_cli.embedding — Embedding engine package
# =============================================================================
# Purpose:     Public API surface for all embedding operations: model loading,
#              text embedding (single/batch), vector storage, staleness detection,
#              and batch re-embedding of blank/stale neurons.
# Rationale:   Single import point so callers never reach into submodules.
#              The embedding engine is in-process via llama-cpp-python using
#              nomic-embed-text-v1.5 Q8_0 GGUF, producing 768-dim L2-normalized
#              vectors. Callers specify operation type (index vs query) and the
#              engine handles task prefixes transparently.
# Responsibility:
#   - Re-export the primary embedding entry points
#   - Re-export vector storage and staleness detection utilities
#   - Re-export batch re-embed orchestrator
#   - Hide internal wiring (model loading, prefix logic, serialization)
# Organization:
#   model_loader_lazy_singleton.py        — lazy singleton Llama loader
#   task_prefix_search_document_query.py  — prefix constants and prepend logic
#   embedding_input_content_plus_tags.py  — build embedding input from content + tags
#   embed_single_and_batch.py             — single and batch embedding via Llama.embed()
#   vector_storage_vec0_write.py          — write vectors to vec0, binary serialization
#   stale_and_blank_vector_detection.py   — query for blank/stale neuron IDs
#   batch_reembed_blank_and_stale.py      — orchestrate batch re-embed operation
#   dimension_enforcement_768.py          — validate vector dimensions before write
# =============================================================================

# --- Public API exports (to be populated during implementation) ---
# from .model_loader_lazy_singleton import get_model
# from .embed_single_and_batch import embed_single, embed_batch
# from .vector_storage_vec0_write import write_vector, write_vectors_batch
# from .stale_and_blank_vector_detection import get_blank_neuron_ids, get_stale_neuron_ids
# from .batch_reembed_blank_and_stale import batch_reembed
# from .embedding_input_content_plus_tags import build_embedding_input

__all__: list[str] = [
    # "get_model",
    # "embed_single",
    # "embed_batch",
    # "write_vector",
    # "write_vectors_batch",
    # "get_blank_neuron_ids",
    # "get_stale_neuron_ids",
    # "batch_reembed",
    # "build_embedding_input",
]
