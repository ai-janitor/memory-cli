# Edge Management

Covers: edge add (with reason and weight, default weight 1.0), edge remove, edge
list (by neuron — show all connections with reasons), --link integration with
neuron add, write-and-wire flow (new neuron linked to previously retrieved neuron,
edge reason references bridging conversation), circular references valid, capture
context linking (neurons co-occurring in a session are connected).

Requirements traced: §2.2 Edges, §2.3 Capture Context.
Dependencies: #3 Schema (edges table), #6 Neuron CRUD (neurons must exist).
