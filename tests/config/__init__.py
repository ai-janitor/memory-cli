# =============================================================================
# Package: tests.config
# Purpose: Test suite for the memory_cli.config subsystem.
# Rationale: Config is foundational — every CLI command depends on it. Tests
#   cover schema defaults, path resolution, loading/validation, and init.
# Responsibility:
#   - Test config schema and default values
#   - Test path resolution (ancestor walk, global fallback, overrides)
#   - Test config loading pipeline end-to-end
#   - Test memory init for global and project scopes
# Organization:
#   test_config_schema_defaults.py — schema and defaults tests
#   test_config_path_resolution.py — path resolution tests
#   test_config_loader_validator.py — loading pipeline tests
#   test_init_global_and_project.py — init command tests
# =============================================================================
