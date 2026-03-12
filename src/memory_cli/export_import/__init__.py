# =============================================================================
# Package: memory_cli.export_import
# Purpose: Portable JSON export and import of the memory graph — neurons, edges,
#   tags, attributes, and optionally vectors. Enables backup, migration between
#   databases, and cross-agent memory sharing.
# Rationale: AI agents need to move memory between hosts, share context, and
#   recover from DB loss. A self-contained JSON envelope with referential
#   integrity checks makes this safe and portable. String-based tag/attr names
#   (not internal IDs) ensure the export is DB-independent.
# Responsibility:
#   - Export: query neurons with optional tag filters, resolve tags/attrs to
#     names, filter edges to only those within the export set, build the
#     versioned envelope, write JSON to stdout or file.
#   - Import: validate structure, types, referential integrity, vector dims;
#     collect all errors before writing; transactional write (all-or-nothing);
#     conflict resolution (skip/overwrite/error).
#   - Validation: 18 discrete checks, dry-run mode, error collection.
# Organization:
#   export_neurons_tags_edges_to_json.py — Query, resolve, filter, build export
#   export_envelope_format_v1.py — Build the versioned envelope JSON structure
#   import_validate_structure_refs_dims.py — All 18 validation checks
#   import_write_transactional.py — Transactional import write pipeline
#   conflict_handler_skip_overwrite_error.py — --on-conflict mode logic
# =============================================================================

# --- Public API exports ---
# These will be the primary entry points consumed by CLI commands.

# from .export_neurons_tags_edges_to_json import export_neurons
# from .import_validate_structure_refs_dims import validate_import_file
# from .import_write_transactional import import_neurons
# from .conflict_handler_skip_overwrite_error import ConflictHandler
