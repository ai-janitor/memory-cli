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

This manifesto guides agents on when and how to store memory. It is a usage
guide, not a rule book. User preferences and project rules belong as neurons
in the graph — not here.

WHEN TO STORE:
When significant effort was spent discovering a path, method, solution, or
insight — store it as a neuron so the next agent doesn't have to rediscover it.
If it was hard to figure out, it's worth remembering. If it's obvious, don't
bother.

HOW TO STORE:
- Store as a neuron with edges to related concepts. Isolated neurons are noise.
- Use problem-pattern-solution triads for bugs: [bug] --caused_by--> [pattern] --solved_by--> [solution].
- Be specific with edge reasons: "works_at" not "related_to."
- Tag with user-rule when storing user preferences so agents can find them.

PROVENANCE:
- User-authored: confidence 1.0. The user's word is the highest authority.
- Agent-authored: confidence 1.0, intentional structure.
- Extracted: confidence < 1.0, model inferred.

BEFORE ACTING:
- Before scaffolding, coding, or naming: search for applicable user rules first.
  memory neuron search "user-rule <topic>"

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
