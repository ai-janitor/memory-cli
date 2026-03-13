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

import copy
import json
import uuid
from pathlib import Path
from typing import Optional

from .config_schema_and_defaults import CONFIG_DEFAULTS


class InitError(Exception):
    """Raised when memory init fails.

    Attributes:
        reason: What went wrong (already_exists, permission_denied, etc.)
        details: Human-readable message.
    """

    # reason: str
    # details: str

    def __init__(self, reason: str, details: str):
        self.reason = reason
        self.details = details
        super().__init__(details)


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
    # 1. Determine store path
    base = cwd if cwd is not None else Path.cwd()
    if project:
        store_path = base / ".memory"
    else:
        store_path = Path.home() / ".memory"

    # 2. Check existing store
    try:
        store_exists = store_path.exists()
    except PermissionError as e:
        raise InitError(
            reason="permission_denied",
            details=f"Permission denied checking store directory: {e}",
        )

    if store_exists and not force:
        # EC-11: raise InitError if store already exists without --force
        raise InitError(
            reason="already_exists",
            details=(
                f"Memory store already exists at {store_path}. "
                "Use --force to overwrite the config (DB will be preserved)."
            ),
        )

    # 3. Create directory structure
    _create_directory_structure(store_path)

    # 4. Write config.json
    _write_default_config(store_path, force=force)

    # 5. Create empty DB file (preserves existing if present)
    db_path = store_path / "memory.db"
    _create_empty_db_file(db_path)

    # 5b. Bootstrap schema and write store fingerprint
    # Open the DB, run migrations (creates schema if new), then stamp
    # fingerprint, project name, and db_path into meta table.
    _bootstrap_schema_and_fingerprint(db_path, base, project)

    # 6. Print post-init instructions
    _print_post_init_instructions(store_path, project=project)

    # 7. Return store_path
    return store_path


def _derive_project_name(base: Path) -> str:
    """Derive project name from cwd basename or git remote.

    Logic:
    1. Try git remote origin URL -> extract repo name
    2. Fall back to base directory basename
    3. If all else fails, return "unknown"

    Args:
        base: The base directory (cwd or home).

    Returns:
        A human-readable project name string.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=str(base), timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            url = result.stdout.strip()
            # Extract repo name from URL (handles both HTTPS and SSH)
            name = url.rstrip("/").rsplit("/", 1)[-1]
            if name.endswith(".git"):
                name = name[:-4]
            if name:
                return name
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    # Fall back to directory basename
    name = base.name
    return name if name else "unknown"


def _bootstrap_schema_and_fingerprint(
    db_path: Path, base: Path, project: bool
) -> None:
    """Open the DB, run migrations to create schema, then stamp fingerprint.

    This ensures that after `memory init`, the database is fully ready with
    schema, fingerprint, project name, and db_path in the meta table.

    Args:
        db_path: Absolute path to the SQLite DB file.
        base: The base directory used for project name derivation.
        project: Whether this is a project-scoped init.
    """
    try:
        from memory_cli.db import open_connection, run_pending_migrations, read_schema_version
        from memory_cli.db.extension_loader_sqlite_vec import load_sqlite_vec

        conn = open_connection(db_path)
        load_sqlite_vec(conn)
        current = read_schema_version(conn)
        target = 3  # Must match _TARGET_VERSION in db_connection_from_global_flags.py
        if current < target:
            run_pending_migrations(conn, current, target)

        # Stamp fingerprint if not already set (migration v002 uses OR IGNORE,
        # so if init races with migration, the first write wins)
        fingerprint = uuid.uuid4().hex[:8]
        conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('fingerprint', ?)",
            (fingerprint,),
        )

        # Derive and write project name
        project_name = _derive_project_name(base)
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('project', ?)",
            (project_name,),
        )

        # Write absolute db_path
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('db_path', ?)",
            (str(db_path.resolve()),),
        )

        # Seed default manifesto if not already set (migration v003 uses OR IGNORE,
        # so if init races with migration, the first write wins)
        from memory_cli.db.migrations.v003_add_manifesto_to_meta import DEFAULT_MANIFESTO
        conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('manifesto', ?)",
            (DEFAULT_MANIFESTO,),
        )

        conn.commit()
        conn.close()
    except Exception:
        # Non-fatal: init still succeeds even if fingerprint stamping fails.
        # The migration will handle it on first real use.
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
    try:
        store_path.mkdir(parents=True, exist_ok=True)
        (store_path / "models").mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        raise InitError(
            reason="permission_denied",
            details=f"Permission denied creating store directory: {e}",
        )


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
    # 1. Build config dict from CONFIG_DEFAULTS
    config = copy.deepcopy(CONFIG_DEFAULTS)

    # 2. Override db_path with absolute path
    config["db_path"] = str(store_path / "memory.db")

    # 3. Override embedding.model_path
    config["embedding"]["model_path"] = str(store_path / "models" / "default.gguf")

    # 4. Serialize to JSON with indent=2
    config_json = json.dumps(config, indent=2)

    # 5. Write to store_path / "config.json"
    config_path = store_path / "config.json"
    config_path.write_text(config_json, encoding="utf-8")

    return config_path


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
    # If file exists: do nothing (preserve data on --force reinit)
    if db_path.exists():
        return

    # If file doesn't exist: touch (create empty file)
    db_path.touch()


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
    scope = "project" if project else "global"
    print(f"Memory store initialized ({scope}) at: {store_path}")
    print(f"  Config:   {store_path / 'config.json'}")
    print(f"  Database: {store_path / 'memory.db'}")
    print(f"  Models:   {store_path / 'models'}/")
    print()
    model_dest = store_path / "models" / "default.gguf"
    model_url = (
        "https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF"
        "/resolve/main/nomic-embed-text-v1.5.Q8_0.gguf"
    )
    print("Next steps:")
    print("  1. Download the embedding model:")
    print(f"       curl -L -o {model_dest} \\")
    print(f"         {model_url}")
    print(
        f"  2. (Optional) Update embedding.model_path in {store_path / 'config.json'}"
        " if you use a different model file."
    )
    print(f"  3. Add your first memory:")
    print(f"       memory neuron add \"Your first memory\"")
