# =============================================================================
# Package: memory_cli.edge
# Purpose: Edge CRUD & query — directed relationships between neurons in the
#   memory graph. Edges encode why two neurons are related, with a reason
#   string and a numeric weight for spreading activation scoring.
# Rationale: Edges are the connective tissue of the graph. They enable
#   traversal (goto), spreading activation search, and context capture during
#   ingestion. Isolating edge logic from neuron CRUD avoids circular
#   dependencies and keeps relationship semantics in one place.
# Responsibility:
#   - edge add: validate endpoints + reason, insert with weight
#   - edge remove: lookup by (source, target), delete without affecting neurons
#   - edge list: directional query with pagination and content snippets
#   - link flag: atomic neuron+edge creation for --link on neuron add
# Organization:
#   edge_add_with_reason_and_weight.py — Validate + insert edge
#   edge_remove_by_source_target.py — Lookup + delete edge
#   edge_list_by_neuron_direction.py — List edges with direction filter, snippets, pagination
#   link_flag_atomic_neuron_plus_edge.py — Atomic neuron+edge creation for --link flag
#   edge_splice_atomic_insert_between.py — Atomic splice: insert neuron between existing edge
#   edge_update_by_source_target.py — Update reason/weight on existing edge in place
# =============================================================================

# --- Public API exports ---
# These will be the primary entry points consumed by CLI commands and other packages.

from .edge_add_with_reason_and_weight import edge_add
from .edge_remove_by_source_target import edge_remove
from .edge_list_by_neuron_direction import edge_list
from .link_flag_atomic_neuron_plus_edge import link_flag_atomic_create
from .edge_splice_atomic_insert_between import edge_splice
from .edge_update_by_source_target import edge_update
