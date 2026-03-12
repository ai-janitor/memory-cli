# =============================================================================
# Purpose: Top-level package for memory-cli
# Rationale: Single entry point for the memory_cli package. Exposes version
#   and the main() entry point for console_scripts in pyproject.toml.
# Responsibility: Package identity and version string
# Organization: Minimal — just version and main import
# =============================================================================

# --- Version ---
# Semantic version string, read by pyproject.toml dynamic version or hardcoded
__version__ = "0.1.0"

# --- Public API ---
# from memory_cli.cli.entrypoint_and_argv_dispatch import main
