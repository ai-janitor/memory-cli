# =============================================================================
# Package: memory_cli.traversal
# Purpose: Graph traversal commands — deterministic navigation of the neuron
#   graph by time (timeline) and by edge (goto). These are read-only,
#   non-scoring, non-ranking commands. They complement search by giving agents
#   a structured way to walk the graph without invoking embeddings or LLMs.
# Rationale: Search finds relevant neurons by semantic/keyword similarity.
#   Traversal navigates the graph structurally — "what happened after this?"
#   (timeline) and "what is this connected to?" (goto). Separating traversal
#   from search keeps the search package focused on scoring/ranking and avoids
#   loading the embedding model for simple navigation.
# Responsibility:
#   - timeline: chronological walk forward/backward from a reference neuron
#   - goto: single-hop edge traversal from a reference neuron
#   - Both commands: pagination, JSON envelope output, exit code conventions
#   - Neither command modifies data, loads embeddings, or invokes LLMs
# Organization:
#   timeline_walk_forward_backward.py — Chronological navigation from reference
#   goto_follow_edges_single_hop.py — Edge-following navigation from reference
# =============================================================================

# --- Public API exports ---
# These will be the primary entry points consumed by CLI commands.

from .timeline_walk_forward_backward import timeline_walk
from .goto_follow_edges_single_hop import goto_follow_edges
