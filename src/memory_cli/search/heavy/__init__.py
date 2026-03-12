# =============================================================================
# Package: memory_cli.search.heavy
# Purpose: Haiku-assisted heavy/deep search — re-ranking and query expansion
#   on top of the light search pipeline for higher-quality results when the
#   user opts into LLM-assisted search via --heavy or --deep.
# Rationale: Heavy search is a superset of light search. Keeping it in a
#   sub-package isolates the Haiku API dependency, prompt engineering, and
#   merge logic from the deterministic light search pipeline. The heavy
#   package can be entirely disabled/skipped without affecting light search.
# Responsibility:
#   - heavy_search_orchestrator.py — Main flow: inflate limit, run light,
#     call Haiku (rerank + expand), merge, paginate
#   - haiku_api_key_resolution.py — Resolve API key from config env var
#   - haiku_rerank_by_neuron_ids.py — Build rerank prompt, call Haiku,
#     parse ordered ID list
#   - haiku_query_expansion_terms.py — Build expansion prompt, call Haiku,
#     parse term list
#   - heavy_search_merge_and_paginate.py — Merge reranked + expansion
#     results, deduplicate, apply user limit/offset
# Organization:
#   Orchestrator is the single entry point. It delegates to the four
#   helper modules. All Haiku calls are single-turn, stateless, structured
#   output only. Failures in Haiku calls degrade gracefully to light search.
# =============================================================================

# --- Public API exports ---
# The orchestrator is the only public entry point for this package.

from .heavy_search_orchestrator import heavy_search
