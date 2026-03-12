# =============================================================================
# Module: init_create_global_or_project_store.py
# Purpose: Implement the `memory init` command — bootstrap a new memory store
#   at either the global location (~/.memory/) or project-scoped (.memory/).
# Rationale: Init is the only command that WRITES config. Every other command
#   is config-read-only. Init creates the directory structure, writes a default
#   config.json with paths relative to the store location, creates an empty DB
#   file, and creates a models/ dir for GGUF files.
# Responsibility:
#   - Create the store directory structure
#   - Write config.json with correct absolute paths for db_path and model_path
#   - Create empty SQLite DB file (touch, not schema — DB module owns schema)
#   - Create models/ directory for embedding model files
#   - Handle --force (overwrite config, preserve DB)
#   - Handle --project (use .memory/ in cwd instead of ~/.memory/)
#   - Print human-readable instructions after init
# Organization:
#   1. Imports
#   2. init_memory_store() — main entry point
#   3. _create_directory_structure() — mkdir -p for store dirs
#   4. _write_default_config() — serialize defaults with store-relative paths
#   5. _create_empty_db_file() — touch the DB file
#   6. _print_post_init_instructions() — user-facing guidance
# =============================================================================

from __future__ import annotations

from pathlib import Path
from typing import Optional


class InitError(Exception):
    """Raised when memory init fails.

    Attributes:
        reason: What went wrong (already_exists, permission_denied, etc.)
        details: Human-readable message.
    """

    # reason: str
    # details: str

    pass


def init_memory_store(
    project: bool = False,
    force: bool = False,
    cwd: Optional[Path] = None,
) -> Path:
    """Initialize a new memory store (global or project-scoped).

    This is the implementation behind `memory init`.

    Logic flow:
    1. Determine store path:
       - If project=True: store_path = cwd / ".memory"
       - If project=False: store_path = Path.home() / ".memory"
    2. Check existing store:
       - If store_path exists AND force=False:
         raise InitError("already_exists") with message to use --force
       - If store_path exists AND force=True:
         proceed but preserve existing DB file (only overwrite config)
    3. Create directory structure:
       - store_path/                    (root)
       - store_path/models/             (for GGUF embedding models)
    4. Write config.json:
       - Start from CONFIG_DEFAULTS
       - Set db_path = str(store_path / "memory.db") — absolute path
       - Set embedding.model_path = str(store_path / "models" / "default.gguf")
       - Write as formatted JSON (indent=2 for human readability)
       - If force=True, overwrite existing config.json
    5. Create empty DB file:
       - If DB file doesn't exist: touch it (create empty file)
       - If DB file exists (force reinit): leave it alone — don't destroy data
    6. Print post-init instructions:
       - Where the store was created
       - How to download an embedding model
       - How to start using memory-cli
    7. Return store_path

    Edge cases:
    - EC-11: init when store already exists without --force -> error
    - EC-13: --force reinit preserves DB data, only overwrites config
    - EC-14: permission denied creating dirs -> InitError("permission_denied")
    - EC-15: cwd is read-only filesystem -> InitError("permission_denied")
    - Project init in a dir that already has .memory/ from another tool -> warn

    Args:
        project: If True, create .memory/ in cwd. If False, create ~/.memory/.
        force: If True, overwrite existing config (preserve DB).
        cwd: Working directory for project-scoped init. Defaults to Path.cwd().

    Returns:
        Path to the created store directory.

    Raises:
        InitError: If store already exists (without --force) or permissions fail.
    """
    pass


def _create_directory_structure(store_path: Path) -> None:
    """Create the store directory and subdirectories.

    Creates:
    - store_path/           (root of the memory store)
    - store_path/models/    (for GGUF embedding model files)

    Uses mkdir(parents=True, exist_ok=True) so it's idempotent.

    Args:
        store_path: Root directory of the memory store.

    Raises:
        InitError: On permission errors.
    """
    pass


def _write_default_config(store_path: Path, force: bool = False) -> Path:
    """Write config.json with defaults and store-relative absolute paths.

    Logic flow:
    1. Build config dict from CONFIG_DEFAULTS
    2. Override db_path with absolute path: store_path / "memory.db"
    3. Override embedding.model_path: store_path / "models" / "default.gguf"
    4. Serialize to JSON with indent=2
    5. Write to store_path / "config.json"
       - If file exists and force=False: this shouldn't happen (caller checks)
       - If file exists and force=True: overwrite

    Args:
        store_path: Root directory of the memory store.
        force: Whether to overwrite existing config.json.

    Returns:
        Path to the written config.json.
    """
    pass


def _create_empty_db_file(db_path: Path) -> None:
    """Create an empty DB file if it doesn't already exist.

    Does NOT create schema — the DB module owns schema creation.
    This just ensures the file exists so config validation passes.

    Logic:
    - If file exists: do nothing (preserve data on --force reinit)
    - If file doesn't exist: touch (create empty file)

    Args:
        db_path: Absolute path to the SQLite DB file.
    """
    pass


def _print_post_init_instructions(store_path: Path, project: bool) -> None:
    """Print human-readable post-init instructions to stdout.

    Tells the user:
    1. Where the store was created (global vs project)
    2. The path to config.json for customization
    3. How to download/place an embedding model in models/
    4. The next command to try (e.g., `memory neuron add`)

    Args:
        store_path: Root directory of the created memory store.
        project: Whether this was a project-scoped init.
    """
    pass
