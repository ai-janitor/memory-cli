# =============================================================================
# Module: config_path_resolution_ancestor_walk.py
# Purpose: Resolve which config.json to use for the current CLI invocation.
# Rationale: memory-cli supports project-scoped (.memory/) and global
#   (~/.memory/) configs. The resolution order is:
#     1. Explicit --config flag (highest priority)
#     2. Ancestor directory walk: from cwd upward, find .memory/config.json
#     3. Global fallback: ~/.memory/config.json
#   This mirrors tools like .git/ discovery — familiar UX for developers.
# Responsibility:
#   - Implement the 3-tier resolution strategy
#   - Return the resolved path or raise if no config found anywhere
#   - Never create or modify files — read-only path discovery
# Organization:
#   1. Imports
#   2. Constants (config dir name, config file name)
#   3. resolve_config_path() — main entry point
#   4. _walk_ancestors() — helper for directory traversal
#   5. _global_config_path() — helper for ~/.memory/ path
# =============================================================================

from __future__ import annotations

from pathlib import Path
from typing import Optional


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
# MEMORY_DIR_NAME = ".memory"
# CONFIG_FILE_NAME = "config.json"


def resolve_config_path(
    config_override: Optional[str] = None,
    db_override: Optional[str] = None,
    cwd: Optional[Path] = None,
) -> Path:
    """Resolve the config.json path for the current CLI invocation.

    Resolution order (first match wins):
    1. --config flag: if provided, use exactly this path
       - Must exist and be a file, else raise FileNotFoundError
    2. Ancestor walk: starting from cwd, walk up parent directories
       looking for .memory/config.json
       - Stop at filesystem root
       - First match wins (closest ancestor = project scope)
    3. Global fallback: ~/.memory/config.json
       - If exists, use it
    4. If none found: raise FileNotFoundError with helpful message
       telling user to run `memory init`

    Edge cases:
    - EC-1: --config points to nonexistent file -> FileNotFoundError
    - EC-2: no config anywhere -> FileNotFoundError("run memory init")
    - EC-7: cwd is deeply nested -> ancestor walk still finds .memory/ at project root
    - EC-8: both project and global exist -> project wins (ancestor walk runs first)
    - EC-13: --config flag with relative path -> resolve to absolute before checking

    Note: --db override is NOT handled here — it's a config value override
    applied after loading. We accept it as a parameter only to pass through
    to the caller's context, not to affect path resolution.

    Args:
        config_override: Value of --config flag, or None.
        db_override: Value of --db flag (passed through, not used here).
        cwd: Working directory to start ancestor walk from. Defaults to Path.cwd().

    Returns:
        Path to the resolved config.json file.

    Raises:
        FileNotFoundError: If no config file can be found.
    """
    pass


def _walk_ancestors(start_dir: Path) -> Optional[Path]:
    """Walk from start_dir upward looking for .memory/config.json.

    Logic flow:
    1. current = start_dir
    2. While current != current.parent (not at root):
       a. Check current / .memory / config.json exists
       b. If yes, return that path
       c. current = current.parent
    3. Also check root itself (for / or C:\\)
    4. Return None if nothing found

    Args:
        start_dir: Directory to start the upward walk from.

    Returns:
        Path to .memory/config.json if found, else None.
    """
    pass


def _global_config_path() -> Path:
    """Return the path to the global config: ~/.memory/config.json.

    Uses Path.home() to resolve ~ portably.

    Returns:
        Path to ~/.memory/config.json (may or may not exist).
    """
    pass
