# =============================================================================
# FILE: src/memory_cli/cli/noun_handlers/__init__.py
# PURPOSE: Package init for noun handlers. Imports all noun handler modules
#          so they self-register with the dispatch registry at import time.
# RATIONALE: Import-time registration means adding a new noun is just adding
#            a new module file — no central switch statement to update. This
#            __init__.py is the trigger that loads them all.
# RESPONSIBILITY:
#   - Import every noun handler module (triggers their register_noun() calls)
#   - Importing this package triggers self-registration into the dispatch registry
#     (get_registry() lives in entrypoint_and_argv_dispatch, not here)
# ORGANIZATION:
#   - One import per noun handler module, alphabetically
# =============================================================================

# --- Import noun handlers to trigger self-registration ---
# Each module calls register_noun() at module level when imported.
from memory_cli.cli.noun_handlers import attr_noun_handler as _attr
from memory_cli.cli.noun_handlers import batch_noun_handler as _batch
from memory_cli.cli.noun_handlers import edge_noun_handler as _edge
from memory_cli.cli.noun_handlers import meta_noun_handler as _meta
from memory_cli.cli.noun_handlers import neuron_noun_handler as _neuron
from memory_cli.cli.noun_handlers import tag_noun_handler as _tag
