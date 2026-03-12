# Neuron CRUD & Storage

Covers: neuron add (one-liner quick capture), neuron get (by ID), neuron list
(with filters), neuron update (content, tags, attrs), neuron archive (soft state
change), auto-tagging on write (timestamp, current project from pwd/git), user
tags additive, --link flag with reason at write time (delegates to edge module),
embed immediately on write via embedding engine, FTS5 auto-sync via triggers.

Requirements traced: §2.1 Neurons, §3.1 Manual Quick Capture, §3.3 Write-and-Wire.
Dependencies: #3 Schema, #4 Tag/Attr Registries, #5 Embedding Engine.
