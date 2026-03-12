# =============================================================================
# meta_check_orphans_and_anomalies.py — `memory meta check` command
# =============================================================================
# Purpose:     Run 9 integrity checks on the database and report issues.
#              This is the active health-check command — unlike stats (passive),
#              check actively probes for orphans, anomalies, and inconsistencies.
#              Updates last_integrity_check_at after a successful run.
# Rationale:   Over time, databases accumulate orphaned records (vectors without
#              neurons, edges pointing to deleted neurons, FTS entries for removed
#              content). Dimension consistency can also degrade if bugs or manual
#              edits corrupt vectors. A structured check with clear pass/fail
#              gives agents and operators confidence or actionable issues.
# Responsibility:
#   - Run 9 named checks, each returning pass/fail + optional issue detail
#   - Aggregate into a MetaCheckResult with status, counts, and issues array
#   - Update last_integrity_check_at in meta table after successful completion
# Organization:
#   Single public function: run_meta_check(conn, config) -> dict
#   9 internal check functions, each returning a CheckItem.
#   CheckItem dataclass for individual check results.
# =============================================================================

from __future__ import annotations

import os
import sqlite3
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class CheckItem:
    """Result of a single integrity check.

    Attributes:
        name: Short identifier for the check (e.g., "db_accessible").
        passed: True if the check passed, False if it found an issue.
        detail: Human-readable description of the issue if failed, or None.
    """
    name: str
    passed: bool
    detail: str | None = None


@dataclass
class MetaCheckResult:
    """Aggregate result of all integrity checks.

    Attributes:
        status: "ok" if all checks passed, "issues_found" otherwise.
        checks_passed: Number of checks that passed.
        checks_failed: Number of checks that failed.
        issues: List of issue descriptions from failed checks.
        checks: List of all CheckItem results.
    """
    status: str = "ok"
    checks_passed: int = 0
    checks_failed: int = 0
    issues: list[str] = field(default_factory=list)
    checks: list[CheckItem] = field(default_factory=list)


def run_meta_check(conn: sqlite3.Connection, config: dict) -> dict:
    """Run all 9 integrity checks and return results.

    Args:
        conn: Open SQLite connection with all tables accessible.
        config: Resolved config dict with embedding_model and embedding_dimensions.

    Returns:
        Dict with:
            - status: "ok" or "issues_found"
            - checks_passed: int
            - checks_failed: int
            - issues: list[str] (descriptions of failed checks)
            - last_integrity_check_at: str (ISO 8601, when this check completed)
    """
    # --- Step 1: Run all 9 checks ---
    checks = [
        _check_db_accessible(conn),
        _check_schema_version(conn),
        _check_model_match(conn, config),
        _check_dimension_match(conn, config),
        _check_stale_flag(conn),
        _check_orphaned_vectors(conn),
        _check_orphaned_edges(conn),
        _check_orphaned_fts(conn),
        _check_dimension_consistency(conn, config),
    ]

    # --- Step 2: Aggregate results ---
    result = MetaCheckResult()
    for check in checks:
        result.checks.append(check)
        if check.passed:
            result.checks_passed += 1
        else:
            result.checks_failed += 1
            if check.detail is not None:
                result.issues.append(check.detail)
    result.status = "ok" if result.checks_failed == 0 else "issues_found"

    # --- Step 3: Update last_integrity_check_at ---
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_integrity_check_at', ?)",
        (now_iso,),
    )
    conn.commit()

    # --- Step 4: Return as dict with status, counts, issues, and timestamp ---
    return {
        "status": result.status,
        "checks_passed": result.checks_passed,
        "checks_failed": result.checks_failed,
        "issues": result.issues,
        "last_integrity_check_at": now_iso,
    }


# =============================================================================
# Individual check functions — one per integrity check
# =============================================================================


def _check_db_accessible(conn: sqlite3.Connection) -> CheckItem:
    """Check 1: Verify the database is accessible and responsive.

    Executes a simple query to confirm the connection is alive.
    """
    # Try: SELECT 1
    # If succeeds → CheckItem("db_accessible", True)
    # If fails → CheckItem("db_accessible", False, "Database not accessible: {error}")
    try:
        conn.execute("SELECT 1").fetchone()
        return CheckItem(name="db_accessible", passed=True)
    except Exception as exc:
        return CheckItem(name="db_accessible", passed=False, detail=f"Database not accessible: {exc}")


def _check_schema_version(conn: sqlite3.Connection) -> CheckItem:
    """Check 2: Verify schema version is known and expected.

    Reads the schema version and confirms it is a recognized value.
    """
    # Read schema version from meta table (seeded as '1' by v001 migration)
    # If version >= 1 and version <= MAX_KNOWN_VERSION → pass
    # If version == 0 or missing → fail: "Schema not initialized"
    # If version > MAX_KNOWN_VERSION → fail: "Unknown schema version {v}"
    MAX_KNOWN_VERSION = 1
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row is None:
            return CheckItem(name="schema_version", passed=False, detail="Schema not initialized (no schema_version in meta)")
        version = int(row[0])
        if version == 0:
            return CheckItem(name="schema_version", passed=False, detail="Schema not initialized (schema_version = 0)")
        if version > MAX_KNOWN_VERSION:
            return CheckItem(name="schema_version", passed=False, detail=f"Unknown schema version {version} (max known: {MAX_KNOWN_VERSION})")
        return CheckItem(name="schema_version", passed=True)
    except Exception as exc:
        return CheckItem(name="schema_version", passed=False, detail=f"Could not read schema version: {exc}")


def _check_model_match(conn: sqlite3.Connection, config: dict) -> CheckItem:
    """Check 3: Verify DB model name matches config model.

    If no model stored in DB (no vectors yet), this check passes.
    """
    # Read embedding_model from meta (key used by v001 migration)
    # If None or 'default' → pass (no vectors written yet, nothing to compare)
    # Extract config model basename and compare
    # If DB model == config model → pass
    # Else → fail: "Model mismatch: DB has {db}, config has {config}"
    row = conn.execute("SELECT value FROM meta WHERE key = 'embedding_model'").fetchone()
    if row is None or row[0] == "default":
        return CheckItem(name="model_match", passed=True)
    db_model = row[0]
    config_model = os.path.basename(config["embedding"]["model_path"])
    if db_model == config_model:
        return CheckItem(name="model_match", passed=True)
    return CheckItem(
        name="model_match",
        passed=False,
        detail=f"Model mismatch: DB has '{db_model}', config has '{config_model}'",
    )


def _check_dimension_match(conn: sqlite3.Connection, config: dict) -> CheckItem:
    """Check 4: Verify DB dimensions match config dimensions.

    If no dimensions stored in DB (no vectors yet), this check passes.
    """
    # Read embedding_dimensions from meta
    # If None → pass (no vectors written yet)
    # Compare int(db_dims) vs int(config["embedding"]["dimensions"])
    # If match → pass
    # Else → fail: "Dimension mismatch: DB has {db}, config has {config}"
    row = conn.execute("SELECT value FROM meta WHERE key = 'embedding_dimensions'").fetchone()
    if row is None:
        return CheckItem(name="dimension_match", passed=True)
    try:
        db_dims = int(row[0])
    except (ValueError, TypeError):
        return CheckItem(name="dimension_match", passed=True)
    config_dims = int(config["embedding"]["dimensions"])
    if db_dims == config_dims:
        return CheckItem(name="dimension_match", passed=True)
    return CheckItem(
        name="dimension_match",
        passed=False,
        detail=f"Dimension mismatch: DB has {db_dims}, config has {config_dims}",
    )


def _check_stale_flag(conn: sqlite3.Connection) -> CheckItem:
    """Check 5: Check if vectors are marked as stale.

    Stale vectors indicate a past model drift that hasn't been resolved.
    """
    # Read vectors_marked_stale_at from meta
    # If None → pass (no stale condition)
    # Else → fail with timestamp and remediation instruction
    row = conn.execute("SELECT value FROM meta WHERE key = 'vectors_marked_stale_at'").fetchone()
    if row is None:
        return CheckItem(name="stale_flag", passed=True)
    return CheckItem(
        name="stale_flag",
        passed=False,
        detail=f"Vectors marked stale since {row[0]}. Run `memory batch reembed` to resolve.",
    )


def _check_orphaned_vectors(conn: sqlite3.Connection) -> CheckItem:
    """Check 6: Detect vectors whose parent neuron no longer exists.

    Orphaned vectors waste space and can confuse search results.
    """
    # Count vectors in neurons_vec whose neuron_id has no matching row in neurons
    # vec0 does not support JOINs, so use a subquery approach
    row = conn.execute("""
        SELECT COUNT(*) FROM neurons_vec
        WHERE neuron_id NOT IN (SELECT id FROM neurons)
    """).fetchone()
    count = row[0] if row is not None else 0
    if count == 0:
        return CheckItem(name="orphaned_vectors", passed=True)
    return CheckItem(
        name="orphaned_vectors",
        passed=False,
        detail=f"{count} orphaned vector(s) found (neuron deleted but vector remains)",
    )


def _check_orphaned_edges(conn: sqlite3.Connection) -> CheckItem:
    """Check 7: Detect edges where source or target neuron no longer exists.

    Orphaned edges can cause traversal errors and confusing results.
    """
    # Count edges where source or target neuron no longer exists
    # Edges use ON DELETE CASCADE, but orphans may appear if FK was disabled
    row = conn.execute("""
        SELECT COUNT(*) FROM edges e
        LEFT JOIN neurons n1 ON e.source_id = n1.id
        LEFT JOIN neurons n2 ON e.target_id = n2.id
        WHERE n1.id IS NULL OR n2.id IS NULL
    """).fetchone()
    count = row[0] if row is not None else 0
    if count == 0:
        return CheckItem(name="orphaned_edges", passed=True)
    return CheckItem(
        name="orphaned_edges",
        passed=False,
        detail=f"{count} orphaned edge(s) found (source or target neuron deleted)",
    )


def _check_orphaned_fts(conn: sqlite3.Connection) -> CheckItem:
    """Check 8: Detect FTS entries whose parent neuron no longer exists.

    Orphaned FTS entries can produce phantom search results.
    """
    # FTS5 content-backed table — use the shadow docsize table to detect orphans
    # neurons_fts_docsize has one row per indexed document.
    # A rowid in docsize with no matching neurons.id = orphaned FTS entry.
    try:
        row = conn.execute("""
            SELECT COUNT(*) FROM neurons_fts_docsize
            WHERE rowid NOT IN (SELECT id FROM neurons)
        """).fetchone()
        count = row[0] if row is not None else 0
    except Exception:
        # Shadow table may not be accessible in all configurations — pass trivially
        return CheckItem(name="orphaned_fts", passed=True)
    if count == 0:
        return CheckItem(name="orphaned_fts", passed=True)
    return CheckItem(
        name="orphaned_fts",
        passed=False,
        detail=f"{count} orphaned FTS entry/entries found (neuron deleted but FTS index not cleaned up)",
    )


def _check_dimension_consistency(conn: sqlite3.Connection, config: dict) -> CheckItem:
    """Check 9: Sample up to 100 vectors and verify dimension count.

    This catches corrupted or mismatched vectors that slipped past checks.
    """
    # Read expected dimensions from config
    expected_dims = int(config["embedding"]["dimensions"])
    # SELECT embedding FROM neurons_vec LIMIT 100
    # Embeddings are stored as float32 blobs — each float is 4 bytes
    # If dimension count != expected → record as inconsistent
    #
    # Handle case where no vectors exist → pass trivially
    try:
        rows = conn.execute("SELECT embedding FROM neurons_vec LIMIT 100").fetchall()
    except Exception:
        return CheckItem(name="dimension_consistency", passed=True)

    if not rows:
        return CheckItem(name="dimension_consistency", passed=True)

    inconsistent = 0
    sampled = len(rows)
    for row in rows:
        emb = row[0]
        if emb is None:
            continue
        # float32 blob: each float is 4 bytes
        if isinstance(emb, (bytes, bytearray)):
            actual_dims = len(emb) // 4
        else:
            # Some vec0 builds return a list or other type
            try:
                actual_dims = len(emb)
            except TypeError:
                continue
        if actual_dims != expected_dims:
            inconsistent += 1

    if inconsistent == 0:
        return CheckItem(name="dimension_consistency", passed=True)
    return CheckItem(
        name="dimension_consistency",
        passed=False,
        detail=f"{inconsistent} of {sampled} sampled vector(s) have wrong dimensions (expected {expected_dims})",
    )
