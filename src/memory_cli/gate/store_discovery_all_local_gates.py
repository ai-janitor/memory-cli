# =============================================================================
# FILE: src/memory_cli/gate/store_discovery_all_local_gates.py
# PURPOSE: Discover all memory stores (local + global) and compute each store's
#          gate neuron.
# RATIONALE: The "gate show" command needs to display all known stores and their
#            densest nodes. This module handles the discovery and aggregation.
# RESPONSIBILITY:
#   - discover_all_local_gates(cwd=None) -> List[StoreGateResult]
#   - _compute_gate_for_config(config_path, scope) -> Optional[StoreGateResult]
# ORGANIZATION:
#   1. StoreGateResult NamedTuple
#   2. discover_all_local_gates — public API
#   3. _compute_gate_for_config — per-store helper
# =============================================================================

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List, NamedTuple, Optional

from ..config.config_path_resolution_ancestor_walk import resolve_all_config_paths
from ..db.connection_setup_wal_fk_busy import open_connection
from .gate_compute_densest_node import GateResult, compute_densest_node


# =============================================================================
# DATA TYPES
# =============================================================================
class StoreGateResult(NamedTuple):
    """One discovered store and its gate neuron (if any)."""

    store_path: Path
    scope: str
    gate_neuron_id: Optional[int]
    edge_count: int


def discover_all_local_gates(cwd: Optional[Path] = None) -> List[StoreGateResult]:
    """Discover all memory stores and compute each store's gate neuron.

    Uses ancestor walk from cwd to find local .memory/ stores, plus the global
    ~/.memory/ store. For each store, opens its database and computes the gate
    (densest node by edge count).

    Logic flow:
    1. Call resolve_all_config_paths(cwd=start_dir) to get all config paths
       with their scope labels.
    2. For each (config_path, scope):
       a. Call _compute_gate_for_config(config_path, scope).
       b. If result is not None, append to results list.
    3. Return results list.

    Args:
        cwd: Starting directory for ancestor walk. Defaults to Path.cwd().

    Returns:
        List of StoreGateResult, one per discovered store that could be opened.
    """
    start_dir = cwd if cwd is not None else Path.cwd()
    config_paths = resolve_all_config_paths(cwd=start_dir)

    results = []
    for config_path, scope in config_paths:
        result = _compute_gate_for_config(config_path, scope)
        if result is None:
            continue
        results.append(result)
    return results


def _compute_gate_for_config(
    config_path: Path,
    scope: str,
) -> Optional[StoreGateResult]:
    """Load config, open DB, compute gate, return StoreGateResult.

    Logic:
    1. Read config JSON from config_path.
       - On any error (missing, malformed) -> return None (skip this store).
    2. Extract db_path from config dict.
       - If missing or None -> return None.
    3. Check that the DB file exists.
       - If missing -> return None.
    4. Open connection, compute gate.
       - On any exception -> return None (skip broken stores).
    5. Build and return StoreGateResult.

    Args:
        config_path: Path to config.json for this store.
        scope: Scope label ("LOCAL" or "GLOBAL").

    Returns:
        StoreGateResult or None if the store cannot be opened.
    """
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    db_path_str = raw.get("db_path")
    if not db_path_str:
        return None
    db_path = Path(db_path_str)

    if not db_path.is_file():
        return None

    conn = None
    gate = None
    try:
        conn = open_connection(db_path)

        gate = compute_densest_node(conn)
    except Exception:
        if conn is not None:
            conn.close()
        return None
    finally:
        if conn is not None:
            conn.close()

    store_path = config_path.parent.parent

    return StoreGateResult(
        store_path=store_path,
        scope=scope,
        gate_neuron_id=gate.neuron_id if gate is not None else None,
        edge_count=gate.edge_count if gate is not None else 0,
    )
