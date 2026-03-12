# =============================================================================
# Package: memory_cli.neuron
# Purpose: Neuron CRUD & storage — the core data entity of the memory graph.
#   Neurons are content nodes with tags, attributes, embeddings, and lifecycle
#   state. This package owns creation, retrieval, listing, mutation, and
#   archive/restore of neuron records.
# Rationale: Neurons are the central abstraction — every other subsystem
#   (edges, search, spreading activation) operates on neurons. Isolating
#   neuron CRUD into its own package keeps the data-owner logic cohesive and
#   avoids circular dependencies with edges, embeddings, and search.
# Responsibility:
#   - neuron add: full pipeline (validate, auto-tag, write, embed, optional link)
#   - neuron get: single lookup with tag/attr hydration
#   - neuron list: filtered, paginated listing
#   - neuron update: content/tags/attrs mutation with re-embed on content change
#   - neuron archive/restore: lifecycle transitions
#   - auto-tag capture: timestamp and project auto-tags
#   - project detection: git remote / git dir / cwd fallback
# Organization:
#   neuron_add_with_autotags_and_embed.py — Full add pipeline
#   neuron_get_by_id.py — Single neuron lookup with hydration
#   neuron_list_filtered_paginated.py — Filtered list with pagination
#   neuron_update_content_tags_attrs.py — Mutation with re-embed
#   neuron_archive_and_restore.py — Archive/restore lifecycle
#   auto_tag_capture_timestamp_and_project.py — Auto-tag generation
#   project_detection_git_or_cwd.py — Project name detection
# =============================================================================

# --- Public API exports ---
# These will be the primary entry points consumed by CLI commands.

# from .neuron_add_with_autotags_and_embed import neuron_add
# from .neuron_get_by_id import neuron_get
# from .neuron_list_filtered_paginated import neuron_list
# from .neuron_update_content_tags_attrs import neuron_update
# from .neuron_archive_and_restore import neuron_archive, neuron_restore
# from .auto_tag_capture_timestamp_and_project import capture_auto_tags
# from .project_detection_git_or_cwd import detect_project
