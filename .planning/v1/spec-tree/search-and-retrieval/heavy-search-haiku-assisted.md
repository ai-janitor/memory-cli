# Heavy Search (Haiku-Assisted)

Covers: Haiku re-ranks light search results for deeper relevance, Haiku generates
query expansion (related search terms), re-runs light search with expanded terms
and merges results, returns raw data only (no synthesis or summarization by the
LLM). Triggered by a flag on the search command (e.g., --heavy or --deep).

Requirements traced: §4.2 Heavy Search.
Dependencies: #8 Light Search (operates on its results, re-invokes with expanded queries), #2 Config (Haiku API key).
