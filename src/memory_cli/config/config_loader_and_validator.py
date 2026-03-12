# =============================================================================
# Module: config_loader_and_validator.py
# Purpose: Load config JSON from disk, merge defaults, apply CLI overrides,
#   validate all fields, and return a typed MemoryConfig object.
# Rationale: This is the single entry point the CLI calls on every invocation.
#   It orchestrates the full pipeline: resolve path -> read file -> parse JSON
#   -> merge defaults -> apply overrides -> validate -> return typed object.
#   Centralizing this avoids scattered config logic across commands.
# Responsibility:
#   - Orchestrate the config loading pipeline end-to-end
#   - Apply --db override after loading (overrides db_path in config)
#   - Surface clear error messages for all failure modes
#   - Return a frozen, validated MemoryConfig (aliased from ConfigSchema)
# Organization:
#   1. Imports
#   2. MemoryConfig type alias
#   3. load_config() — main entry point (pipeline orchestrator)
#   4. _read_config_file() — read and parse JSON
#   5. _apply_overrides() — apply --db and any future CLI overrides
#   6. ConfigLoadError — custom exception for config loading failures
# =============================================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .config_path_resolution_ancestor_walk import resolve_config_path
from .config_schema_and_defaults import (
    ConfigSchema,
    build_config_with_defaults,
    dict_to_config_schema,
    validate_config,
)


# -----------------------------------------------------------------------------
# Type alias — MemoryConfig is the public name for the config object.
# Internal code uses ConfigSchema; consumers use MemoryConfig.
# -----------------------------------------------------------------------------
MemoryConfig = ConfigSchema


class ConfigLoadError(Exception):
    """Raised when config loading fails at any stage.

    Attributes:
        stage: Which pipeline stage failed (resolve, read, parse, validate).
        details: Human-readable description of what went wrong.
    """

    # stage: str
    # details: str

    pass


def load_config(
    config_override: Optional[str] = None,
    db_override: Optional[str] = None,
    cwd: Optional[Path] = None,
) -> MemoryConfig:
    """Load, validate, and return the memory-cli config.

    This is the main entry point called on every CLI invocation.

    Pipeline:
    1. Resolve config path
       - Call resolve_config_path(config_override, db_override, cwd)
       - On FileNotFoundError -> raise ConfigLoadError(stage="resolve")
    2. Read config file
       - Call _read_config_file(resolved_path)
       - On JSON decode error -> raise ConfigLoadError(stage="parse")
       - On I/O error -> raise ConfigLoadError(stage="read")
    3. Merge defaults
       - Call build_config_with_defaults(raw_dict)
       - Fills in any missing keys with defaults
    4. Apply CLI overrides
       - Call _apply_overrides(merged_dict, db_override)
       - --db override replaces db_path in the merged config
    5. Validate
       - Call validate_config(merged_dict)
       - If errors -> raise ConfigLoadError(stage="validate", details=errors)
    6. Convert to typed object
       - Call dict_to_config_schema(validated_dict)
       - Return MemoryConfig instance

    Edge cases:
    - EC-3: config.json is empty file -> parse error
    - EC-4: config.json has invalid JSON -> parse error
    - EC-9: --db with relative path -> validation catches non-absolute path
    - EC-10: config has all defaults (user only ran init) -> valid
    - EC-14: permissions error reading config -> I/O error stage
    - EC-15: config.json is a directory not a file -> I/O error stage

    Args:
        config_override: Value of --config CLI flag, or None.
        db_override: Value of --db CLI flag, or None.
        cwd: Working directory for path resolution. Defaults to cwd.

    Returns:
        MemoryConfig: Validated, typed config object.

    Raises:
        ConfigLoadError: On any failure in the pipeline, with stage and details.
    """
    pass


def _read_config_file(config_path: Path) -> Dict[str, Any]:
    """Read and parse a config.json file.

    Logic flow:
    1. Open file for reading (UTF-8)
    2. Parse JSON
    3. Verify top-level is a dict (not array, string, etc.)
    4. Return parsed dict

    Error handling:
    - FileNotFoundError: config was deleted between resolution and read (race)
    - PermissionError: insufficient permissions
    - json.JSONDecodeError: malformed JSON
    - TypeError: top-level is not a dict

    Args:
        config_path: Absolute path to config.json.

    Returns:
        Parsed config as a dict.

    Raises:
        ConfigLoadError: With appropriate stage on any failure.
    """
    pass


def _apply_overrides(
    config: Dict[str, Any],
    db_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply CLI flag overrides to the config dict.

    Currently supported overrides:
    - --db: replaces config["db_path"] with the provided value

    Future overrides can be added here without touching the pipeline.

    Logic flow:
    1. If db_override is not None:
       a. Set config["db_path"] = db_override
    2. Return modified config (mutates in place for efficiency)

    Args:
        config: Merged config dict (defaults already applied).
        db_override: Value of --db flag, or None.

    Returns:
        Config dict with overrides applied.
    """
    pass
