# Metadata & Integrity

Covers: DB-level metadata tracking (model name, vector dimensions, schema version,
neuron/vector stats), vector dimension enforcement (all vectors must match configured
dimensions), config/DB drift detection on startup (compare config.json against DB
metadata, warn and block inconsistent operations), model change detection (updating
model in config marks all vectors stale).

Requirements traced: §9 Metadata & Integrity (except schema versioning, which is in #3).
Dependencies: #2 Config, #3 Schema (metadata table), #5 Embedding (model info).
