# Task 43 — Add consolidated column and memory meta consolidate command

## Checklist

- [ ] **v005 migration**: `src/memory_cli/db/migrations/v005_add_consolidated_column.py`
  - ALTER TABLE neurons ADD COLUMN consolidated INTEGER (nullable, ms epoch UTC)
  - No BEGIN/COMMIT — caller owns the transaction
  - Register in `__init__.py` MIGRATION_REGISTRY as version 5

- [ ] **meta consolidate verb**: Add to `src/memory_cli/cli/noun_handlers/meta_noun_handler.py`
  - Query: `WHERE status = 'active' AND consolidated IS NULL ORDER BY created_at ASC`
  - Mark each: `UPDATE neurons SET consolidated = ? WHERE id = ?`
  - Detect stale: neurons where `updated_at > consolidated`
  - Return: `{consolidated_count, skipped_count, stale_count, stale_ids}`
  - Idempotent — already-consolidated neurons skipped by WHERE clause

- [ ] **Tests**: `tests/db/test_consolidated_migration_v005.py`
  - Migration adds nullable column
  - Existing neurons get consolidated = NULL
  - Runner migrates v4→v5 and v0→v5
  - Consolidate processes unconsolidated FIFO
  - Already-consolidated skipped
  - Stale neurons flagged

- [ ] Run `uv run pytest`
- [ ] Commit
- [ ] `minion task complete-phase --task-id 43 --agent fighter`
