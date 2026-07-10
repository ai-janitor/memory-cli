# =============================================================================
# Module: test_hygiene_nested_deadline.py
# Purpose: Regression coverage for the R3 hygiene nested-deadline guard
#   (task-74c20c2e). _SearchDeadline shares one process-wide SIGALRM / single
#   ITIMER_REAL, so a NESTED enter (a search inside a search) would clobber the
#   outer deadline — it must refuse with RuntimeError, and the depth guard must
#   reset so a later top-level deadline still works. Tester-owned.
# =============================================================================

from __future__ import annotations

import pytest

from memory_cli.search.light_search_pipeline_orchestrator import _SearchDeadline


def test_nested_deadline_refused_with_runtimeerror():
    with _SearchDeadline(5):
        with pytest.raises(RuntimeError, match="nested"):
            with _SearchDeadline(5):
                pass  # inner enter must raise before arming a second ITIMER


def test_depth_guard_resets_after_outer_exit():
    # A refused nested enter must NOT leak depth — a fresh top-level deadline
    # after the outer one exits must arm cleanly (no false "nested" error).
    with _SearchDeadline(5):
        with pytest.raises(RuntimeError):
            with _SearchDeadline(5):
                pass
    # outer exited → depth back to 0 → this must NOT raise
    with _SearchDeadline(5):
        pass
