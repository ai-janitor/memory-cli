# =============================================================================
# Package: tests.traversal
# Purpose: Test suite for graph traversal commands — timeline and goto.
#   Validates chronological navigation (timeline) and edge-following navigation
#   (goto) independently from search.
# Rationale: Traversal commands are the primary structural navigation tools for
#   agents. They must produce deterministic, correctly ordered, paginated output
#   with proper exit codes. These tests verify all edge cases: direction,
#   tie-breaking, self-loops, empty results, reference not found, and pagination.
# Organization:
#   test_timeline_walk.py — Timeline forward/backward/pagination/tie-breaking tests
#   test_goto_edges.py — Goto outgoing/incoming/both/self-loop/pagination tests
# =============================================================================
