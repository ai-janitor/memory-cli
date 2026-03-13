# =============================================================================
# v003_add_manifesto_to_meta.py — Add default manifesto to meta table
# =============================================================================
# Purpose:     For existing databases, insert the default memory manifesto into
#              the meta table as key='manifesto'. New stores get this at init.
# Rationale:   The manifesto guides AI agents on what to store, extract, and
#              prioritize. Every store (LOCAL and GLOBAL) has its own manifesto
#              that can be customized independently.
# Responsibility:
#   - INSERT OR IGNORE manifesto into meta (idempotent)
#   - Does NOT update schema_version — the migration runner handles that
# Organization:
#   Public function: apply(conn) -> None
#   Constant: DEFAULT_MANIFESTO — the default manifesto text
# =============================================================================

from __future__ import annotations

import sqlite3

DEFAULT_MANIFESTO = """\
MEMORY MANIFESTO — How to use this memory store.

This manifesto is a USAGE GUIDE — it tells agents how to store, extract, and
retrieve memory effectively. It is NOT a repository of rules, preferences, or
project-specific data. Those belong as neurons in the graph where they can have
edges, fan out, and participate in activation.

STORING MEMORY:
- Store decisions with impact, not just facts. "We chose X because Y" > "X exists."
- Store people with relationships and edges, not just names.
- Store user corrections as triads: [problem] --caused_by--> [pattern] --solved_by--> [solution].
- Connect what you store. A neuron with no edges is just text.
- Tag with specifics: "works_at" not "related_to."

WHAT NOT TO STORE:
- Boilerplate or status updates.
- Facts derivable from code, git history, or file paths.
- Duplicates of what's already in the graph.

EXTRACTING FROM BLOBS:
- Prioritize decisions and consequences over entity lists.
- Prioritize relationships over isolated facts.
- Extract the user's corrections — highest-signal target.
- Extract purpose: why was this built, not just what.

JUDGING VALUE:
- Impact: did this change what happened next?
- Demand: do agents search for this?
- Centrality: do paths flow through this node?
- NOT frequency. Common ≠ valuable. Demanded = valuable.

PROVENANCE:
- User-authored: confidence 1.0, ground truth. The user's word is law.
- Agent-authored: confidence 1.0, intentional structure.
- Extracted: confidence < 1.0, model inferred. Weight accordingly.

USER PREFERENCES AND RULES:
- User preferences are stored as neurons, NOT in this manifesto.
- Search for them: memory neuron search "user-rule <topic>"
- They have edges, they fan out, they participate in activation.
- Before scaffolding, coding, or naming: search for applicable user rules first.

This manifesto evolves. Update it with: memory meta manifesto set"""


def apply(conn: sqlite3.Connection) -> None:
    """Apply the v2->v3 migration: add default manifesto to meta table.

    This function executes within the caller's transaction. It must NOT
    call BEGIN, COMMIT, or ROLLBACK. If any step fails, it raises an
    exception and the caller rolls back the entire migration batch.

    Args:
        conn: An open sqlite3.Connection inside an active transaction.

    Raises:
        sqlite3.Error: If INSERT fails.
    """
    # =========================================================================
    # STEP 1: Insert default manifesto into meta table (idempotent via OR IGNORE)
    # =========================================================================
    # If manifesto already exists (e.g., set by a newer init), this is a no-op.
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('manifesto', ?)",
        (DEFAULT_MANIFESTO,),
    )
