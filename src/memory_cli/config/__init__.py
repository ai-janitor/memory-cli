# =============================================================================
# Package: memory_cli.config
# Purpose: Config & initialization subsystem for memory-cli
# Rationale: Every CLI invocation needs config — this package owns the full
#   lifecycle: schema definition, path resolution, loading/validation, and
#   the `memory init` command that bootstraps global or project stores.
# Responsibility:
#   - Define the canonical config schema and defaults
#   - Resolve which config file to use (ancestor walk, global fallback, overrides)
#   - Load, merge defaults, validate, and return a frozen config object
#   - Create new memory stores (global ~/.memory/ or project .memory/)
# Organization:
#   config_schema_and_defaults.py — schema + defaults as data structures
#   config_path_resolution_ancestor_walk.py — path resolution logic
#   config_loader_and_validator.py — load, merge, validate pipeline
#   init_create_global_or_project_store.py — `memory init` implementation
# =============================================================================

# --- Public API exports ---
# These will be the primary entry points consumed by the CLI layer and other packages.

from .config_schema_and_defaults import CONFIG_DEFAULTS, ConfigSchema
from .config_path_resolution_ancestor_walk import resolve_config_path, resolve_all_config_paths
from .config_loader_and_validator import load_config, MemoryConfig, ConfigLoadError
from .init_create_global_or_project_store import init_memory_store, InitError
