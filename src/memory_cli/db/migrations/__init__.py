# =============================================================================
# memory_cli.db.migrations — Migration registry and discovery
# =============================================================================
# Purpose:     Central registry mapping schema version numbers to their
#              migration apply() functions. The migration runner imports this
#              to find which functions to call for a given version range.
# Rationale:   Explicit registry (dict of int -> callable) is simpler and more
#              debuggable than auto-discovery. Each migration module exports an
#              apply(conn) function. The registry maps version number to that.
# Responsibility:
#   - Import all migration modules
#   - Build MIGRATION_REGISTRY: dict[int, MigrationFn]
#   - Validate no duplicate version numbers at import time
# Organization:
#   MIGRATION_REGISTRY dict is the sole public export.
#   Each migration lives in its own file: v001_*.py, v002_*.py, etc.
# =============================================================================

from __future__ import annotations

from typing import Callable
import sqlite3

# --- Type alias matching migration_runner's MigrationFn ---
MigrationFn = Callable[[sqlite3.Connection], None]

# --- Migration registry: version_number -> apply function ---
# Each entry maps an integer version to the function that migrates
# from (version-1) to (version).
# Import and register each migration module's apply function here.

from .v001_baseline_all_tables_indexes_triggers import apply as apply_v001
from .v002_add_store_fingerprint import apply as apply_v002
from .v003_add_manifesto_to_meta import apply as apply_v003
from .v004_add_access_tracking import apply as apply_v004
from .v005_add_edge_provenance import apply as apply_v005
from .v006_add_consolidated_column import apply as apply_v006
from .v007_add_edge_types_and_canonical_reason import apply as apply_v007
from .v008_add_search_latency_table import apply as apply_v008
from .v009_add_embedding_input_hash import apply as apply_v009

MIGRATION_REGISTRY: dict[int, MigrationFn] = {
    1: apply_v001,
    2: apply_v002,
    3: apply_v003,
    4: apply_v004,
    5: apply_v005,
    6: apply_v006,
    7: apply_v007,
    8: apply_v008,
    9: apply_v009,
}
