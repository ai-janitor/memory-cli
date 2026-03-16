# Task 50 — Tag Hierarchy Conventions Documentation

## Checklist

- [ ] Add `_TAG_CONVENTIONS` content constant to manpage_noun_handler.py
  - Structural types: category, pipeline, system-rule, feedback, contact, person
  - Domain groupings: career, email, cli, infra, tooling
  - Temporal: auto-generated YYYY-MM-DD, manual YYYY-MM ranges
  - Good vs bad tag examples
  - Revisit thresholds / tag hygiene recommendations
- [ ] Create handler and register in verb map, descriptions, flag defs
- [ ] Update `_OVERVIEW` manpage to list `tag-conventions` in the topic index
- [ ] Run `uv run pytest` — all tests pass
- [ ] Commit
- [ ] Run `minion task complete-phase --task-id 50 --agent thief`
