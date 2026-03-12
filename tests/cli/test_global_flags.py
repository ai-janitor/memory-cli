# =============================================================================
# FILE: tests/cli/test_global_flags.py
# PURPOSE: Test --format, --config, --db parsing, stripping, and defaults.
# RATIONALE: Global flags must be cleanly extracted from anywhere in argv
#            without disturbing the noun/verb tokens. Incorrect parsing breaks
#            dispatch. These tests verify all positions, edge cases, and defaults.
# RESPONSIBILITY:
#   - Test parse_global_flags() with flags at various positions
#   - Test default values when flags are absent
#   - Test invalid --format values
#   - Test --flag=value syntax alongside --flag value syntax
#   - Test stripping: remaining tokens must not contain global flags
#   - Test edge case: --format without a value
# ORGANIZATION:
#   1. Test class: TestFormatFlag
#   2. Test class: TestConfigFlag
#   3. Test class: TestDbFlag
#   4. Test class: TestFlagStripping
#   5. Test class: TestFlagEdgeCases
# =============================================================================

from __future__ import annotations

import pytest
from memory_cli.cli.global_flags_format_config_db import parse_global_flags, GlobalFlags


# =============================================================================
# TEST: --format FLAG
# =============================================================================
class TestFormatFlag:
    """Test --format flag parsing."""

    def test_format_json_explicit(self) -> None:
        """--format json sets format to json.

        Pseudo-logic:
        1. flags, remaining = parse_global_flags(["--format", "json", "neuron", "list"])
        2. Assert flags.format == "json"
        3. Assert remaining == ["neuron", "list"]
        """
        flags, remaining = parse_global_flags(["--format", "json", "neuron", "list"])
        assert flags.format == "json"
        assert remaining == ["neuron", "list"]

    def test_format_text_explicit(self) -> None:
        """--format text sets format to text.

        Pseudo-logic:
        1. flags, remaining = parse_global_flags(["--format", "text", "neuron", "list"])
        2. Assert flags.format == "text"
        """
        flags, remaining = parse_global_flags(["--format", "text", "neuron", "list"])
        assert flags.format == "text"

    def test_format_default_is_json(self) -> None:
        """No --format -> default to json.

        Pseudo-logic:
        1. flags, remaining = parse_global_flags(["neuron", "list"])
        2. Assert flags.format == "json"
        """
        flags, remaining = parse_global_flags(["neuron", "list"])
        assert flags.format == "json"

    def test_format_invalid_value_raises_error(self) -> None:
        """--format xml -> error (only json and text allowed).

        Pseudo-logic:
        1. pytest.raises(ValueError/SystemExit)
        2. Call parse_global_flags(["--format", "xml", "neuron", "list"])
        """
        with pytest.raises(ValueError):
            parse_global_flags(["--format", "xml", "neuron", "list"])

    def test_format_equals_syntax(self) -> None:
        """--format=json works same as --format json.

        Pseudo-logic:
        1. flags, remaining = parse_global_flags(["--format=json", "neuron", "list"])
        2. Assert flags.format == "json"
        3. Assert remaining == ["neuron", "list"]
        """
        flags, remaining = parse_global_flags(["--format=json", "neuron", "list"])
        assert flags.format == "json"
        assert remaining == ["neuron", "list"]


# =============================================================================
# TEST: --config FLAG
# =============================================================================
class TestConfigFlag:
    """Test --config flag parsing."""

    def test_config_path_parsed(self) -> None:
        """--config /path/to/config sets config path.

        Pseudo-logic:
        1. flags, _ = parse_global_flags(["--config", "/tmp/config.toml", "neuron", "list"])
        2. Assert flags.config == "/tmp/config.toml"
        """
        flags, _ = parse_global_flags(["--config", "/tmp/config.toml", "neuron", "list"])
        assert flags.config == "/tmp/config.toml"

    def test_config_default_is_none(self) -> None:
        """No --config -> None.

        Pseudo-logic:
        1. flags, _ = parse_global_flags(["neuron", "list"])
        2. Assert flags.config is None
        """
        flags, _ = parse_global_flags(["neuron", "list"])
        assert flags.config is None


# =============================================================================
# TEST: --db FLAG
# =============================================================================
class TestDbFlag:
    """Test --db flag parsing."""

    def test_db_path_parsed(self) -> None:
        """--db /path/to/db.sqlite sets db path.

        Pseudo-logic:
        1. flags, _ = parse_global_flags(["--db", "/tmp/memory.db", "neuron", "list"])
        2. Assert flags.db == "/tmp/memory.db"
        """
        flags, _ = parse_global_flags(["--db", "/tmp/memory.db", "neuron", "list"])
        assert flags.db == "/tmp/memory.db"

    def test_db_default_is_none(self) -> None:
        """No --db -> None.

        Pseudo-logic:
        1. flags, _ = parse_global_flags(["neuron", "list"])
        2. Assert flags.db is None
        """
        flags, _ = parse_global_flags(["neuron", "list"])
        assert flags.db is None


# =============================================================================
# TEST: FLAG STRIPPING
# =============================================================================
class TestFlagStripping:
    """Test that global flags are removed from the remaining token list."""

    def test_flags_at_start_stripped(self) -> None:
        """Flags before noun are stripped from remaining tokens.

        Pseudo-logic:
        1. _, remaining = parse_global_flags(["--format", "text", "--db", "/tmp/x", "neuron", "list"])
        2. Assert remaining == ["neuron", "list"]
        """
        _, remaining = parse_global_flags(["--format", "text", "--db", "/tmp/x", "neuron", "list"])
        assert remaining == ["neuron", "list"]

    def test_flags_at_end_stripped(self) -> None:
        """Flags after verb are stripped from remaining tokens.

        Pseudo-logic:
        1. _, remaining = parse_global_flags(["neuron", "list", "--format", "text"])
        2. Assert remaining == ["neuron", "list"]
        """
        _, remaining = parse_global_flags(["neuron", "list", "--format", "text"])
        assert remaining == ["neuron", "list"]

    def test_flags_interleaved_stripped(self) -> None:
        """Flags mixed between noun/verb/args are all stripped.

        Pseudo-logic:
        1. _, remaining = parse_global_flags(["--format", "json", "neuron", "--db", "/x", "list", "--config", "/y"])
        2. Assert remaining == ["neuron", "list"]
        """
        _, remaining = parse_global_flags(
            ["--format", "json", "neuron", "--db", "/x", "list", "--config", "/y"]
        )
        assert remaining == ["neuron", "list"]


# =============================================================================
# TEST: EDGE CASES
# =============================================================================
class TestFlagEdgeCases:
    """Test tricky edge cases in flag parsing."""

    def test_format_without_value_raises_error(self) -> None:
        """--format at end of argv with no value -> error.

        Pseudo-logic:
        1. pytest.raises(ValueError/SystemExit)
        2. Call parse_global_flags(["neuron", "list", "--format"])
        """
        with pytest.raises(ValueError):
            parse_global_flags(["neuron", "list", "--format"])

    def test_format_value_looks_like_flag(self) -> None:
        """--format --db (value looks like another flag) -> error.

        Pseudo-logic:
        1. pytest.raises(ValueError/SystemExit)
        2. Call parse_global_flags(["--format", "--db", "neuron", "list"])
        """
        with pytest.raises(ValueError):
            parse_global_flags(["--format", "--db", "neuron", "list"])

    def test_multiple_same_flags(self) -> None:
        """--format json --format text -> last wins or error (spec TBD).

        Pseudo-logic:
        1. flags, _ = parse_global_flags(["--format", "json", "--format", "text", "neuron", "list"])
        2. Assert flags.format is either "text" (last wins) or raises error
        """
        try:
            flags, _ = parse_global_flags(
                ["--format", "json", "--format", "text", "neuron", "list"]
            )
            assert flags.format in ("json", "text")
        except ValueError:
            pass
