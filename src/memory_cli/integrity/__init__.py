# =============================================================================
# integrity/__init__.py — Public API for metadata & integrity subsystem
# =============================================================================
# Purpose:     Entry point for the integrity module. Exposes the key functions
#              that the CLI layer and startup sequence call into.
# Rationale:   Centralizes imports so callers do `from memory_cli.integrity
#              import run_startup_drift_check` rather than reaching into
#              submodules directly.
# Responsibility:
#   - Re-export public functions from submodules
#   - Keep the public surface minimal — only what CLI and startup need
# Organization:
#   Flat re-exports grouped by concern: startup check, drift handlers,
#   first-write seeding, meta stats, meta check.
# =============================================================================

# --- Public API exports ---

# Startup drift check — called on every CLI invocation
from memory_cli.integrity.startup_drift_check_model_and_dims import (
    run_startup_drift_check,
    DriftCheckResult,
)

# Drift handlers — called by startup check when drift detected
from memory_cli.integrity.model_drift_stale_vector_marking import (
    handle_model_drift,
    is_vector_dependent_operation,
)
from memory_cli.integrity.dimension_drift_hard_block import handle_dimension_drift

# First-vector-write seeding — called by vector storage on first insert
from memory_cli.integrity.first_vector_write_seed_metadata import seed_metadata_on_first_vector

# CLI commands — called by meta noun handler
from memory_cli.integrity.meta_stats_db_summary import gather_meta_stats
from memory_cli.integrity.meta_check_orphans_and_anomalies import run_meta_check, CheckItem, MetaCheckResult

__all__ = [
    "run_startup_drift_check",
    "DriftCheckResult",
    "handle_model_drift",
    "is_vector_dependent_operation",
    "handle_dimension_drift",
    "seed_metadata_on_first_vector",
    "gather_meta_stats",
    "run_meta_check",
    "CheckItem",
    "MetaCheckResult",
]
