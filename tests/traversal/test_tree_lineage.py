# =============================================================================
# Module: test_tree_lineage.py
# Purpose: Acceptance tests for recursive tree/lineage traversal — the multi-hop
#   analog of goto (single-hop). Walks edges recursively from a root neuron and
#   returns a nested tree (down = descendants, up = ancestors), depth-bounded and
#   cycle-safe, optionally filtered by edge type.
# Rationale: The CLI was one-hop only (goto/edge list). This is the FEATURE under
#   maintain-operate-orchestration (backlog memory-cli #64). Contract-first: these
#   tests are RED until traversal/tree_recursive_lineage.py exists.
# Responsibility:
#   - down: nest children (edges where node is the source) recursively
#   - up: nest parents (edges where node is the target) recursively
#   - depth: bound recursion (depth=1 = root + immediate level only)
#   - edge type filter: only follow edges whose reason matches
#   - cycle-safe: a back-edge must not infinite-loop (visited set)
#   - return shape: {id, content, depth, children: [ ...same shape... ]}
# =============================================================================

from __future__ import annotations

import time
import pytest

from memory_cli.db.connection_setup_wal_fk_busy import open_connection
from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
from memory_cli.db.migration_runner_single_transaction import run_pending_migrations

# The unit under construction (RED until implemented):
from memory_cli.traversal.tree_recursive_lineage import tree_lineage

# Full schema (target v8). NOT v001-only: edge_list caches column-existence
# (provenance/canonical_reason) keyed by id(conn), and ids get reused after GC —
# a v001-only conn here poisons that shared cache for a later same-id conn and
# fails an unrelated test (test_edge_provenance). Full migrate = no schema
# mismatch. The id(conn) cache itself is a latent bug — filed separately.

sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec package required for migration (vec0 virtual table)",
)


@pytest.fixture
def migrated_conn():
    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    run_pending_migrations(conn, 0, 8)  # full schema, not v001-only (see header note)
    yield conn
    conn.close()


def _neuron(conn, content, project="test-project"):
    now = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) "
        "VALUES (?, ?, ?, ?, 'active')",
        (content, now, now, project),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _edge(conn, source_id, target_id, reason="child_of", weight=1.0):
    now = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO edges (source_id, target_id, weight, reason, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (source_id, target_id, weight, reason, now),
    )


@pytest.fixture
def chain_graph(migrated_conn):
    """root(r) --child_of--> a --child_of--> b ;  root --child_of--> c
    Edge convention: source = parent, target = child (matches `neuron add --parent`).
    """
    conn = migrated_conn
    r = _neuron(conn, "root")
    a = _neuron(conn, "child-a")
    b = _neuron(conn, "grandchild-b")
    c = _neuron(conn, "child-c")
    _edge(conn, r, a, "child_of")
    _edge(conn, a, b, "child_of")
    _edge(conn, r, c, "child_of")
    return conn, {"r": r, "a": a, "b": b, "c": c}


# --- down (descendants) ---

def test_tree_down_nests_descendants(chain_graph):
    conn, ids = chain_graph
    tree = tree_lineage(conn, ids["r"], direction="down", depth=10, edge_type="child_of")
    assert tree["id"] == ids["r"]
    assert tree["depth"] == 0
    child_ids = sorted(ch["id"] for ch in tree["children"])
    assert child_ids == sorted([ids["a"], ids["c"]])
    a_node = next(ch for ch in tree["children"] if ch["id"] == ids["a"])
    assert [g["id"] for g in a_node["children"]] == [ids["b"]]
    assert a_node["depth"] == 1
    assert a_node["children"][0]["depth"] == 2


def test_tree_depth_bound(chain_graph):
    conn, ids = chain_graph
    tree = tree_lineage(conn, ids["r"], direction="down", depth=1, edge_type="child_of")
    # depth=1 → root + immediate children, but grandchild NOT expanded
    a_node = next(ch for ch in tree["children"] if ch["id"] == ids["a"])
    assert a_node["children"] == []


def test_tree_edge_type_filter(chain_graph):
    conn, ids = chain_graph
    # add a non-child_of edge from root; it must NOT be followed when filtering
    other = _neuron(conn, "related-not-child")
    _edge(conn, ids["r"], other, "relates_to")
    tree = tree_lineage(conn, ids["r"], direction="down", depth=10, edge_type="child_of")
    assert other not in [ch["id"] for ch in tree["children"]]


# --- up (ancestors) ---

def test_tree_up_nests_ancestors(chain_graph):
    conn, ids = chain_graph
    tree = tree_lineage(conn, ids["b"], direction="up", depth=10, edge_type="child_of")
    assert tree["id"] == ids["b"]
    # b's parent is a; a's parent is root
    a_node = next(p for p in tree["children"] if p["id"] == ids["a"])
    assert [p["id"] for p in a_node["children"]] == [ids["r"]]


# --- cycle safety ---

def test_tree_cycle_safe(migrated_conn):
    conn = migrated_conn
    x = _neuron(conn, "x")
    y = _neuron(conn, "y")
    _edge(conn, x, y, "child_of")
    _edge(conn, y, x, "child_of")  # back-edge → cycle
    # must terminate (visited set), not infinite-loop / RecursionError
    tree = tree_lineage(conn, x, direction="down", depth=50, edge_type="child_of")
    assert tree["id"] == x
