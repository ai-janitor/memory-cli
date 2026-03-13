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
MEMORY MANIFESTO — What to remember, what to extract, what matters.

STORAGE PRIORITIES (what to store):
1. Decisions with downstream impact — "we chose X because Y" bends the path. Facts don't.
2. People with relationships — name alone is useless. Name + role + org + how they connect = valuable.
3. Feedback and corrections — the user told you to change behavior. Prevents repeating mistakes.
4. Novel concepts — if the graph has nothing like this, flag it. New dimensions > more density.
5. Search misses — if you searched and found nothing, that's a gap. Note what was missing.

STORAGE ANTI-PATTERNS (what NOT to store):
1. Boilerplate — "started working on feature X" is noise.
2. Facts derivable from code — file paths, function signatures, git history. Read the source.
3. Common without demand — stored often, searched never = clutter.
4. Isolated nodes — a neuron with no edges is just text. If you can't connect it, question storing it.

EXTRACTION PRIORITIES (what to extract from blobs):
1. Decisions and their consequences — what was chosen, what was rejected, why.
2. Relationships between entities — not just "Payam exists" but "Payam works_at Leidos."
3. Tensions and tradeoffs — where two good ideas conflicted and one won.
4. The user's corrections — "no, do it THIS way" is the highest-signal extraction target.
5. Purpose behind actions — why was this built, not just what was built.

EDGE PRIORITIES (relationships > nodes):
- A neuron with 5 edges is more valuable than 5 neurons with 0 edges.
- Authored edges (agent wrote them) > extracted edges (model guessed them).
- Edge reason should be specific: "works_at" not "related_to."
- Fan-out nodes (decisions that caused other things) are load-bearing. Protect them.

VALUE SIGNALS (how to judge what matters):
- Impact: did this change what happened next?
- Demand: do agents keep searching for this?
- Centrality: do paths flow through this node?
- Novelty: is this a new dimension the graph didn't have?
- NOT frequency. Common ≠ valuable. Demanded = valuable.

PROVENANCE (track the source):
- Authored (agent wrote structure): confidence 1.0, intentional edges.
- Extracted (model guessed): confidence < 1.0, inferred edges.
- The graph must know the difference. Activation should respect it.

This manifesto evolves. Update it as you learn what matters for this store."""


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
