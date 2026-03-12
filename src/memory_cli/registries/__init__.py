# =============================================================================
# Package: memory_cli.registries
# Purpose: Managed-enum registries for tags and attribute keys — integer-ID
#   backed lookup tables with normalization, auto-creation, and CRUD.
# Rationale: Both tags and attrs follow the same pattern: a small table of
#   unique names with stable integer IDs. Centralizing this pattern avoids
#   duplication and ensures consistent normalization/auto-create semantics
#   across the entire CLI. Tag filtering primitives also live here because
#   they are tightly coupled to the tag registry's resolution logic.
# Responsibility:
#   - Tag CRUD: add/list/remove with normalization and idempotent add
#   - Attr CRUD: identical pattern to tags, separate table
#   - Shared lookup: resolve by name (normalize + auto-create) or by ID (strict)
#   - Tag filtering: AND/OR primitives for the search pipeline
# Organization:
#   tag_registry_crud_normalize_autocreate.py — Tag add/list/remove + auto-create
#   attr_registry_crud_normalize_autocreate.py — Attr add/list/remove + auto-create
#   registry_lookup_by_name_or_id.py — Shared lookup: name→ID, ID→name
#   tag_filter_and_or_primitives.py — AND/OR tag filtering for search
# =============================================================================

# --- Public API exports ---
# These will be the primary entry points consumed by CLI commands and other packages.

# from .tag_registry_crud_normalize_autocreate import tag_add, tag_list, tag_remove
# from .attr_registry_crud_normalize_autocreate import attr_add, attr_list, attr_remove
# from .registry_lookup_by_name_or_id import lookup_by_name, lookup_by_id
# from .tag_filter_and_or_primitives import filter_tags_and, filter_tags_or
