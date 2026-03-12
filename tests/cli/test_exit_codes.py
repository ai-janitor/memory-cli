# =============================================================================
# FILE: tests/cli/test_exit_codes.py
# PURPOSE: Test exit code constants and helper behavior.
# RATIONALE: Exit codes are a contract with calling processes. Tests ensure
#            the constants are correct and the helpers map statuses accurately.
# RESPONSIBILITY:
#   - Test constant values (0, 1, 2)
#   - Test status_to_exit_code() mapping for all known statuses
#   - Test status_to_exit_code() fallback for unknown statuses
#   - Test exit_with() raises SystemExit with correct code
# ORGANIZATION:
#   1. Test class: TestExitCodeConstants
#   2. Test class: TestStatusToExitCode
#   3. Test class: TestExitWith
# =============================================================================

from __future__ import annotations

import pytest
from memory_cli.cli.exit_codes_0_1_2 import (
    EXIT_SUCCESS, EXIT_NOT_FOUND, EXIT_ERROR,
    status_to_exit_code, exit_with,
)


# =============================================================================
# TEST: CONSTANTS
# =============================================================================
class TestExitCodeConstants:
    """Verify exit code constant values match the spec."""

    def test_exit_success_is_0(self) -> None:
        """EXIT_SUCCESS == 0."""
        assert EXIT_SUCCESS == 0

    def test_exit_not_found_is_1(self) -> None:
        """EXIT_NOT_FOUND == 1."""
        assert EXIT_NOT_FOUND == 1

    def test_exit_error_is_2(self) -> None:
        """EXIT_ERROR == 2."""
        assert EXIT_ERROR == 2


# =============================================================================
# TEST: STATUS -> EXIT CODE MAPPING
# =============================================================================
class TestStatusToExitCode:
    """Test the status string to exit code conversion."""

    def test_ok_maps_to_0(self) -> None:
        """status "ok" -> 0.

        Pseudo-logic:
        1. Call status_to_exit_code("ok")
        2. Assert returns 0
        """
        assert status_to_exit_code("ok") == 0

    def test_not_found_maps_to_1(self) -> None:
        """status "not_found" -> 1.

        Pseudo-logic:
        1. Call status_to_exit_code("not_found")
        2. Assert returns 1
        """
        assert status_to_exit_code("not_found") == 1

    def test_error_maps_to_2(self) -> None:
        """status "error" -> 2.

        Pseudo-logic:
        1. Call status_to_exit_code("error")
        2. Assert returns 2
        """
        assert status_to_exit_code("error") == 2

    def test_unknown_status_defaults_to_2(self) -> None:
        """Unknown status string -> 2 (error).

        Pseudo-logic:
        1. Call status_to_exit_code("banana")
        2. Assert returns 2 (unknown = error)
        """
        assert status_to_exit_code("banana") == 2


# =============================================================================
# TEST: EXIT_WITH HELPER
# =============================================================================
class TestExitWith:
    """Test that exit_with raises SystemExit with correct code."""

    def test_exit_with_ok_raises_systemexit_0(self) -> None:
        """exit_with("ok") -> SystemExit(0).

        Pseudo-logic:
        1. pytest.raises(SystemExit) as exc
        2. Call exit_with("ok")
        3. Assert exc.value.code == 0
        """
        with pytest.raises(SystemExit) as exc:
            exit_with("ok")
        assert exc.value.code == 0

    def test_exit_with_not_found_raises_systemexit_1(self) -> None:
        """exit_with("not_found") -> SystemExit(1).

        Pseudo-logic:
        1. pytest.raises(SystemExit) as exc
        2. Call exit_with("not_found")
        3. Assert exc.value.code == 1
        """
        with pytest.raises(SystemExit) as exc:
            exit_with("not_found")
        assert exc.value.code == 1

    def test_exit_with_error_raises_systemexit_2(self) -> None:
        """exit_with("error") -> SystemExit(2).

        Pseudo-logic:
        1. pytest.raises(SystemExit) as exc
        2. Call exit_with("error")
        3. Assert exc.value.code == 2
        """
        with pytest.raises(SystemExit) as exc:
            exit_with("error")
        assert exc.value.code == 2
