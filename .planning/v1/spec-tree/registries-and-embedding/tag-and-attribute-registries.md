# Tag & Attribute Registries

Covers: tag registry CRUD (tag add/list/remove), attribute registry CRUD (attr
add/list/remove), integer ID assignment, lowercase normalization on write,
auto-create on reference (tag name → ID, created if not exists), tag filtering
primitives (AND and OR logic), no empty tags enforcement. Both registries share
the same pattern: name → integer ID, managed enum.

Requirements traced: §5 Tags, §6 Attributes.
Dependencies: #3 Schema (registry tables must exist).
