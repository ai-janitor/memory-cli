# Task 45: Entity Extraction Consolidation Pass with Haiku

## Checklist

- [ ] **Consolidation extraction module** (`src/memory_cli/ingestion/consolidation_extraction.py`)
  - Haiku prompt tuned for neuron content (not conversation transcripts)
  - Reuses `ExtractionResult` data classes from existing extraction
  - Extracts entities, facts, relationships from neuron content blobs

- [ ] **Consolidation orchestrator** (`src/memory_cli/ingestion/consolidation_orchestrator.py`)
  - Find unconsolidated neurons (no `consolidated_at` attr)
  - For each: call Haiku extraction on neuron content
  - Create sub-neurons with provenance attrs: `extracted_by=haiku`, `extraction_method=consolidation`, `parent_neuron_id=<id>`
  - Wire edges: parent→child with reason, weight < 1.0 (confidence)
  - Set `consolidated_at` timestamp attr on parent neuron
  - Idempotent: skip neurons that already have `consolidated_at`

- [ ] **Meta consolidate verb** (modify `meta_noun_handler.py`)
  - `memory meta consolidate` — run consolidation on all unconsolidated neurons
  - `memory meta consolidate --neuron-id <id>` — consolidate a single neuron
  - `memory meta consolidate --dry-run` — show what would be consolidated

- [ ] **Tests**
  - `tests/ingestion/test_consolidation_extraction.py` — Haiku call mocked, response parsing
  - `tests/ingestion/test_consolidation_orchestrator.py` — end-to-end with mocked Haiku

- [ ] **Acceptance criteria verification**
  - Haiku extracts entities and relationships from neuron content
  - Sub-neurons created with `extracted_by` provenance metadata
  - Extracted edges carry confidence < 1.0 (via weight)
  - Authored edges (batch load) retain confidence 1.0
  - Parent neuron `consolidated_at` timestamp set after extraction
  - Re-running on already-consolidated neurons is idempotent

## Design Decisions

- **Edge confidence**: Use existing `weight` field. Extracted edges get `weight=0.85`, authored edges keep `weight=1.0`
- **Sub-neuron provenance**: Store via `neuron_attrs`: `extracted_by`, `extraction_method`, `parent_neuron_id`
- **Consolidation timestamp**: `consolidated_at` attr on parent neuron (ISO 8601)
- **Idempotency**: Check for `consolidated_at` attr presence before processing
- **Haiku model**: Same `claude-haiku-4-20250414` as ingestion extraction
