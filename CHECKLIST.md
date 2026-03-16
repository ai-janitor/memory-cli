# Task 49 — Tag Usage Audit Command (`memory tag audit`)

## Checklist

- [ ] **Registry: `tag_audit_statistics` query** — `src/memory_cli/registries/tag_registry_crud_normalize_autocreate.py`
  - New function `tag_audit(conn) -> Dict` returning:
    - `tags`: list of `{name, count, type_pattern}` sorted by count DESC
    - `total_tags`: int
    - `total_neurons`: int
    - `noise_candidates`: list of tags with count=1 (singleton tags)
  - `type_pattern` classification: "date" (YYYY-MM-DD), "project" (auto-tag project), "user" (everything else)

- [ ] **CLI: `handle_audit` verb** — `src/memory_cli/cli/noun_handlers/tag_noun_handler.py`
  - Register "audit" verb in `_VERB_MAP`, `_VERB_DESCRIPTIONS`, `_FLAG_DEFS`
  - Handler: merge audit data across layered connections
  - Return `Result(status="ok", data=audit_report)`

- [ ] **Export** — `src/memory_cli/registries/__init__.py`
  - Add `tag_audit` to imports and `__all__`

- [ ] **Tests** — `tests/registries/test_tag_audit.py`
  - Empty DB returns zero counts
  - Tags with neurons counted correctly
  - Noise candidates identified (count=1)
  - Type pattern classification (date, project, user)
  - Sort order: count DESC

- [ ] **Run `uv run pytest`** — all tests pass

- [ ] **Commit** — `git commit`

- [ ] **Complete phase** — `minion task complete-phase --task-id 49 --agent blackmage`
