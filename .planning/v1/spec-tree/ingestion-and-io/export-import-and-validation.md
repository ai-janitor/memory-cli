# Export, Import & Validation

Covers: export neurons by tag filter or all (`memory neuron export --tags X
--format json`), import with strict schema enforcement (validates structure, tag
registry consistency, vector dimensions, edge reference integrity), validate-only
dry run mode (--validate-only / --dry-run), backup is copy the .db file (documented,
not a CLI feature). Export/import format is JSON with full neuron data including
tags, attributes, edges, and vectors.

Requirements traced: §7.5 Export/Import.
Dependencies: #6 Neurons, #7 Edges, #4 Tags, #5 Embedding (dimension validation).
