# =============================================================================
# Module: neuron_prune_by_lru_age.py
# Purpose: LRU-based automatic archival — archive neurons not accessed within
#   a configurable time window.
# Rationale: Memory stores accumulate stale neurons over time. Automatic
#   pruning keeps the active pool focused by archiving neurons that haven't
#   been accessed recently. Pruned neurons are archived (not deleted) and
#   can be restored at any time.
# Responsibility:
#   - neuron_prune: find and archive stale neurons based on access metrics
#   - Prioritize access_count=0 neurons (never accessed)
#   - Support dry-run mode (report without archiving)
#   - Return report with count archived and total edge weight freed
# Organization:
#   1. Imports
#   2. neuron_prune() — main entry point
#   3. _find_prune_candidates() — query for stale neurons
#   4. _compute_freed_weight() — sum edge weights for a set of neuron IDs
# =============================================================================

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List


def neuron_prune(
    conn: sqlite3.Connection,
    days: int = 30,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Archive neurons not accessed within the configured time window.

    CLI: `memory neuron prune [--days N] [--dry-run]`

    Logic flow:
    1. Compute cutoff timestamp: now - (days * 86_400_000) milliseconds
    2. Find candidates: active neurons where last_accessed_at < cutoff
       OR last_accessed_at IS NULL and created_at < cutoff
    3. Order: access_count ASC (never-accessed first), then last_accessed_at ASC
    4. If dry_run: return candidates without archiving
    5. If not dry_run: archive each candidate via neuron_archive()
    6. Compute freed edge weight (sum of edge weights touching archived neurons)
    7. Return report dict

    Args:
        conn: SQLite connection.
        days: Number of days since last access to consider stale (default 30).
        dry_run: If True, report candidates without archiving.

    Returns:
        Dict with keys:
            - pruned_count: int — number of neurons archived (0 if dry_run)
            - candidate_count: int — number of candidates found
            - candidates: list of dicts with id, content preview, access_count,
              last_accessed_at, created_at
            - freed_weight: float — total edge weight freed (0.0 if dry_run)
            - dry_run: bool — whether this was a dry run
            - days: int — the threshold used
    """
    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - (days * 86_400_000)

    candidates = _find_prune_candidates(conn, cutoff_ms)
    candidate_ids = [c["id"] for c in candidates]

    if dry_run:
        return {
            "pruned_count": 0,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "freed_weight": 0.0,
            "dry_run": True,
            "days": days,
        }

    # Compute freed weight before archiving (edges still exist after archive,
    # but we report the weight that's now on archived neurons)
    freed_weight = _compute_freed_weight(conn, candidate_ids)

    # Archive each candidate
    from .neuron_archive_and_restore import neuron_archive
    for nid in candidate_ids:
        neuron_archive(conn, nid)

    return {
        "pruned_count": len(candidates),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "freed_weight": freed_weight,
        "dry_run": False,
        "days": days,
    }


def _find_prune_candidates(
    conn: sqlite3.Connection,
    cutoff_ms: int,
) -> List[Dict[str, Any]]:
    """Find active neurons that are candidates for pruning.

    A neuron is a prune candidate if:
    - status = 'active'
    - AND (last_accessed_at IS NULL OR last_accessed_at < cutoff_ms)
    - AND created_at < cutoff_ms (don't prune brand-new neurons with no access yet)

    Ordering: access_count ASC (never-accessed first), then
    COALESCE(last_accessed_at, 0) ASC (oldest access first).

    Args:
        conn: SQLite connection.
        cutoff_ms: Cutoff timestamp in milliseconds UTC.

    Returns:
        List of candidate dicts.
    """
    rows = conn.execute(
        """SELECT id, content, access_count, last_accessed_at, created_at
           FROM neurons
           WHERE status = 'active'
             AND created_at < ?
             AND (last_accessed_at IS NULL OR last_accessed_at < ?)
           ORDER BY access_count ASC, COALESCE(last_accessed_at, 0) ASC""",
        (cutoff_ms, cutoff_ms),
    ).fetchall()

    candidates = []
    for row in rows:
        content = row[1]
        preview = (content[:80] + "...") if len(content) > 80 else content
        candidates.append({
            "id": row[0],
            "content_preview": preview,
            "access_count": row[2],
            "last_accessed_at": row[3],
            "created_at": row[4],
        })
    return candidates


def _compute_freed_weight(
    conn: sqlite3.Connection,
    neuron_ids: List[int],
) -> float:
    """Sum edge weights for edges touching any of the given neuron IDs.

    Counts each edge once: edges where source_id OR target_id is in the set.

    Args:
        conn: SQLite connection.
        neuron_ids: List of neuron IDs being pruned.

    Returns:
        Total edge weight as float. 0.0 if no edges or empty list.
    """
    if not neuron_ids:
        return 0.0

    placeholders = ",".join("?" * len(neuron_ids))
    row = conn.execute(
        f"""SELECT COALESCE(SUM(weight), 0.0)
            FROM edges
            WHERE source_id IN ({placeholders})
               OR target_id IN ({placeholders})""",
        neuron_ids + neuron_ids,
    ).fetchone()
    return float(row[0])
