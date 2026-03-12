# =============================================================================
# test_dimension_drift.py — Tests for dimension drift hard block
# =============================================================================
# Purpose:     Verify that handle_dimension_drift emits a clear error to
#              stderr and exits with code 2. Dimension drift is the most
#              severe integrity violation — no operations should proceed.
# Rationale:   The vec0 virtual table has a fixed column width set at creation.
#              If config dimensions don't match, every vector operation will
#              either silently corrupt data or hard-fail at the SQLite layer.
#              Our handler must catch this BEFORE any DB writes happen.
# Responsibility:
#   - Test that sys.exit(2) is always called
#   - Test error message content includes both dimension values
#   - Test error message includes remediation steps
#   - Test that function never returns (always exits)
#   - Test with string and int dimension inputs
# Organization:
#   One test class for exit behavior, one for error message formatting.
#   Uses pytest.raises(SystemExit) to catch the exit.
# =============================================================================

from __future__ import annotations

import pytest
from memory_cli.integrity.dimension_drift_hard_block import (
    handle_dimension_drift,
    _format_dimension_error,
)


class TestHardBlock:
    """Tests for the sys.exit(2) behavior."""

    def test_exits_with_code_2(self) -> None:
        """handle_dimension_drift should always exit with code 2.

        # --- Act / Assert ---
        # with pytest.raises(SystemExit) as exc_info:
        #     handle_dimension_drift(768, 384)
        # exc_info.value.code == 2
        """
        with pytest.raises(SystemExit) as exc_info:
            handle_dimension_drift(768, 384)
        assert exc_info.value.code == 2

    def test_exits_with_string_inputs(self) -> None:
        """Dimensions may come from meta table as strings — should still exit.

        # --- Act / Assert ---
        # with pytest.raises(SystemExit) as exc_info:
        #     handle_dimension_drift("768", "384")
        # exc_info.value.code == 2
        """
        with pytest.raises(SystemExit) as exc_info:
            handle_dimension_drift("768", "384")
        assert exc_info.value.code == 2

    def test_exits_with_mixed_types(self) -> None:
        """One string, one int — should handle gracefully and still exit.

        # --- Act / Assert ---
        # with pytest.raises(SystemExit) as exc_info:
        #     handle_dimension_drift("768", 384)
        # exc_info.value.code == 2
        """
        with pytest.raises(SystemExit) as exc_info:
            handle_dimension_drift("768", 384)
        assert exc_info.value.code == 2

    def test_never_returns(self) -> None:
        """After calling handle_dimension_drift, no subsequent code runs.

        # --- Arrange ---
        # Set a flag = False before the call

        # --- Act ---
        # try:
        #     handle_dimension_drift(768, 384)
        #     flag = True  # This line should never execute
        # except SystemExit:
        #     pass

        # --- Assert ---
        # flag == False
        """
        flag = False
        try:
            handle_dimension_drift(768, 384)
            flag = True  # This line should never execute
        except SystemExit:
            pass
        assert flag is False


class TestErrorMessage:
    """Tests for the error message content."""

    def test_error_written_to_stderr(self, capsys) -> None:
        """Error message should go to stderr, not stdout.

        # --- Arrange ---
        # Capture stderr

        # --- Act ---
        # try:
        #     handle_dimension_drift(768, 384)
        # except SystemExit:
        #     pass

        # --- Assert ---
        # stderr has content
        # stdout is empty
        """
        try:
            handle_dimension_drift(768, 384)
        except SystemExit:
            pass
        captured = capsys.readouterr()
        assert len(captured.err) > 0
        assert captured.out == ""

    def test_error_includes_both_dimensions(self, capsys) -> None:
        """Error message should show DB dims and config dims.

        # --- Arrange ---
        # Capture stderr

        # --- Act ---
        # try:
        #     handle_dimension_drift(768, 384)
        # except SystemExit:
        #     pass

        # --- Assert ---
        # stderr contains "768"
        # stderr contains "384"
        """
        try:
            handle_dimension_drift(768, 384)
        except SystemExit:
            pass
        captured = capsys.readouterr()
        assert "768" in captured.err
        assert "384" in captured.err

    def test_error_includes_remediation(self, capsys) -> None:
        """Error message should explain how to fix the problem.

        # --- Arrange ---
        # Capture stderr

        # --- Act ---
        # try:
        #     handle_dimension_drift(768, 384)
        # except SystemExit:
        #     pass

        # --- Assert ---
        # stderr contains remediation guidance (change config or re-embed)
        """
        try:
            handle_dimension_drift(768, 384)
        except SystemExit:
            pass
        captured = capsys.readouterr()
        assert "reembed" in captured.err or "re-embed" in captured.err

    def test_error_mentions_blocked(self, capsys) -> None:
        """Error should clearly state that operations are blocked.

        # --- Arrange ---
        # Capture stderr

        # --- Act ---
        # try:
        #     handle_dimension_drift(768, 384)
        # except SystemExit:
        #     pass

        # --- Assert ---
        # stderr contains "blocked" or "cannot"
        """
        try:
            handle_dimension_drift(768, 384)
        except SystemExit:
            pass
        captured = capsys.readouterr()
        assert "blocked" in captured.err.lower() or "cannot" in captured.err.lower()


class TestFormatDimensionError:
    """Tests for the _format_dimension_error helper."""

    def test_format_includes_db_dims(self) -> None:
        """Formatted error should include the database dimension count.

        # --- Act ---
        # msg = _format_dimension_error(768, 384)

        # --- Assert ---
        # "768" in msg
        """
        msg = _format_dimension_error(768, 384)
        assert "768" in msg

    def test_format_includes_config_dims(self) -> None:
        """Formatted error should include the config dimension count.

        # --- Act ---
        # msg = _format_dimension_error(768, 384)

        # --- Assert ---
        # "384" in msg
        """
        msg = _format_dimension_error(768, 384)
        assert "384" in msg

    def test_format_returns_string(self) -> None:
        """Helper should return a string, not write directly.

        # --- Act ---
        # msg = _format_dimension_error(768, 384)

        # --- Assert ---
        # isinstance(msg, str)
        # len(msg) > 0
        """
        msg = _format_dimension_error(768, 384)
        assert isinstance(msg, str)
        assert len(msg) > 0
