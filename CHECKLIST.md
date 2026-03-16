# Task 47: Edge Type Normalization Janitor Pass

## Checklist

- [ ] **v006 migration** — `edge_types` table (id, name, parent_id, description) + `canonical_reason` column on `edges`
- [ ] **Synonym mapping** — Built-in synonym clusters (e.g., has_interviewer/interviewed_by/interviewer → interviewer)
- [ ] **Janitor logic** — `edge_normalize_janitor_pass.py` in `src/memory_cli/edge/` — scans edges, clusters synonyms, writes canonical_reason
- [ ] **Original reason preserved** — `reason` column untouched (provenance); `canonical_reason` is the normalized form
- [ ] **CLI verb** — `memory edge normalize` triggers the janitor pass
- [ ] **Query support** — edge list returns canonical_reason when present
- [ ] **Tests** — migration, janitor logic, CLI handler
- [ ] **Run pytest** — all green
- [ ] **Commit**

## Design Decisions

- **canonical_reason** is nullable — NULL means "not yet normalized"
- **edge_types** has parent_id for hierarchy (e.g., `interviewer` parent of `has_interviewer`)
- **Synonym resolution** is deterministic: lowercase, strip whitespace, lookup in synonym map
- **Original reason preserved** as provenance — janitor never modifies `reason` column
- **edge_types seeded** with common relationship types during migration
