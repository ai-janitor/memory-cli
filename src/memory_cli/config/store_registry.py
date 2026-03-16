# =============================================================================
# FILE: src/memory_cli/config/store_registry.py
# PURPOSE: Global registry of known memory stores, persisted as
#          ~/.memory/stores.json. Maps fingerprints to DB paths for
#          cross-store discovery and fingerprint:id handle resolution.
# RATIONALE: Each memory store gets a UUID fingerprint at init time. The
#            registry lets agents discover and reference neurons across
#            projects using fingerprint:id handles (e.g., a3f2b7c1:42).
#            The registry file lives in the global store directory so it
#            is accessible regardless of which project store is active.
# RESPONSIBILITY:
#   - load_registry() -> dict: Read ~/.memory/stores.json (return {} if missing)
#   - save_registry(data): Write ~/.memory/stores.json with indent=2
#   - register_store(fingerprint, db_path, project): Add/update entry
#   - unregister_store(fingerprint): Remove entry
#   - resolve_store(fingerprint) -> str | None: Look up db_path by fingerprint
#   - list_stores() -> list[dict]: Return all registered stores
# ORGANIZATION:
#   1. Path resolution
#   2. Load/save primitives
#   3. Public API functions
# =============================================================================

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# =============================================================================
# PATH RESOLUTION
# =============================================================================

def _registry_path() -> Path:
    """Return the path to ~/.memory/stores.json."""
    return Path.home() / ".memory" / "stores.json"


# =============================================================================
# LOAD / SAVE PRIMITIVES
# =============================================================================

def load_registry() -> Dict[str, Any]:
    """Read ~/.memory/stores.json and return its contents.

    Returns:
        Dict mapping fingerprint -> {"db_path": ..., "project": ..., "registered_at": ...}.
        Returns empty dict if file is missing or unreadable.
    """
    path = _registry_path()
    if not path.is_file():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        return data
    except (OSError, json.JSONDecodeError):
        return {}


def save_registry(data: Dict[str, Any]) -> None:
    """Write data to ~/.memory/stores.json.

    Creates the ~/.memory/ directory if it does not exist.

    Args:
        data: The registry dict to persist.
    """
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# =============================================================================
# PUBLIC API
# =============================================================================

def register_store(fingerprint: str, db_path: str, project: str) -> None:
    """Add or update a store entry in the global registry.

    Args:
        fingerprint: 8-char hex fingerprint of the store.
        db_path: Absolute path to the store's memory.db file.
        project: Human-readable project name.
    """
    registry = load_registry()
    registry[fingerprint] = {
        "db_path": db_path,
        "project": project,
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    save_registry(registry)


def unregister_store(fingerprint: str) -> bool:
    """Remove a store entry from the global registry.

    Args:
        fingerprint: 8-char hex fingerprint of the store to remove.

    Returns:
        True if the entry was found and removed, False if not found.
    """
    registry = load_registry()
    if fingerprint not in registry:
        return False
    del registry[fingerprint]
    save_registry(registry)
    return True


def resolve_store(fingerprint: str) -> Optional[str]:
    """Look up a store's db_path by its fingerprint.

    Args:
        fingerprint: 8-char hex fingerprint.

    Returns:
        Absolute path to the store's memory.db, or None if not registered.
    """
    registry = load_registry()
    entry = registry.get(fingerprint)
    if entry is None:
        return None
    return entry.get("db_path")


def list_stores() -> List[Dict[str, Any]]:
    """Return all registered stores as a list of dicts.

    Each dict includes: fingerprint, db_path, project, registered_at.

    Returns:
        List of store entry dicts.
    """
    registry = load_registry()
    result = []
    for fp, entry in sorted(registry.items()):
        item = {"fingerprint": fp}
        item.update(entry)
        result.append(item)
    return result
