# =============================================================================
# FILE: tests/cli/test_scoped_handle_format_and_parse.py
# PURPOSE: Unit tests for scoped neuron handle formatting and parsing.
# RATIONALE: Scoped handles are the CLI boundary contract — format_handle,
#            parse_handle, and detect_scope must be thoroughly tested since
#            every noun handler depends on them.
# RESPONSIBILITY:
#   - Test format_handle produces correct "SCOPE-id" strings
#   - Test parse_handle accepts LOCAL, GLOBAL, L, G, and bare integers
#   - Test detect_scope correctly classifies ~/.memory/ vs other paths
#   - Test bulk wrappers (scope_neuron_dict, scope_edge_dict, etc.)
# =============================================================================

from __future__ import annotations

import os
import pytest

from memory_cli.cli.scoped_handle_format_and_parse import (
    detect_scope,
    format_handle,
    parse_handle,
    scope_neuron_dict,
    scope_edge_dict,
    scope_neuron_id_value,
    scope_ref_map,
    scope_list,
)


# =============================================================================
# detect_scope tests
# =============================================================================

class TestDetectScope:
    """Scope detection from DB path."""

    def test_global_scope_from_home_memory(self):
        """~/.memory/memory.db -> GLOBAL."""
        home = os.path.expanduser("~")
        assert detect_scope(f"{home}/.memory/memory.db") == "GLOBAL"

    def test_global_scope_tilde_form(self):
        """~/.memory/memory.db (unexpanded) -> GLOBAL."""
        assert detect_scope("~/.memory/memory.db") == "GLOBAL"

    def test_global_scope_subdirectory(self):
        """~/.memory/sub/nested.db -> GLOBAL."""
        assert detect_scope("~/.memory/sub/nested.db") == "GLOBAL"

    def test_local_scope_project_path(self):
        """/home/user/project/.memory/memory.db -> LOCAL."""
        assert detect_scope("/home/user/project/.memory/memory.db") == "LOCAL"

    def test_local_scope_tmp(self):
        """/tmp/test.db -> LOCAL."""
        assert detect_scope("/tmp/test.db") == "LOCAL"

    def test_local_scope_custom_path(self):
        """/opt/data/neurons.db -> LOCAL."""
        assert detect_scope("/opt/data/neurons.db") == "LOCAL"

    def test_local_scope_memory_in_name(self):
        """/home/user/.memory-project/db.sqlite -> LOCAL (not under ~/.memory/)."""
        assert detect_scope("/home/user/.memory-project/db.sqlite") == "LOCAL"


# =============================================================================
# format_handle tests
# =============================================================================

class TestFormatHandle:
    """Format integer ID + scope into scoped handle string."""

    def test_local_format(self):
        assert format_handle(42, "LOCAL") == "LOCAL-42"

    def test_global_format(self):
        assert format_handle(1, "GLOBAL") == "GLOBAL-1"

    def test_zero_id(self):
        assert format_handle(0, "LOCAL") == "LOCAL-0"

    def test_large_id(self):
        assert format_handle(999999, "GLOBAL") == "GLOBAL-999999"


# =============================================================================
# parse_handle tests
# =============================================================================

class TestParseHandle:
    """Parse scoped handle strings back to (scope, int_id)."""

    def test_local_long(self):
        assert parse_handle("LOCAL-42") == ("LOCAL", 42)

    def test_global_long(self):
        assert parse_handle("GLOBAL-7") == ("GLOBAL", 7)

    def test_local_short(self):
        assert parse_handle("L-42") == ("LOCAL", 42)

    def test_global_short(self):
        assert parse_handle("G-7") == ("GLOBAL", 7)

    def test_bare_integer(self):
        assert parse_handle("42") == (None, 42)

    def test_case_insensitive(self):
        assert parse_handle("local-5") == ("LOCAL", 5)
        assert parse_handle("Global-10") == ("GLOBAL", 10)
        assert parse_handle("g-3") == ("GLOBAL", 3)
        assert parse_handle("l-1") == ("LOCAL", 1)

    def test_whitespace_stripped(self):
        assert parse_handle("  LOCAL-42  ") == ("LOCAL", 42)
        assert parse_handle(" 42 ") == (None, 42)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_handle("INVALID-42")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_handle("")

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            parse_handle("LOCAL--1")

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError):
            parse_handle("LOCAL-abc")

    def test_missing_id_raises(self):
        with pytest.raises(ValueError):
            parse_handle("LOCAL-")


# =============================================================================
# Bulk wrapper tests
# =============================================================================

class TestScopeNeuronDict:
    """scope_neuron_dict wraps 'id' field."""

    def test_wraps_int_id(self):
        d = {"id": 42, "content": "hello"}
        result = scope_neuron_dict(d, "LOCAL")
        assert result["id"] == "LOCAL-42"
        assert result["content"] == "hello"

    def test_no_id_passthrough(self):
        d = {"content": "hello"}
        result = scope_neuron_dict(d, "LOCAL")
        assert result == d

    def test_non_int_id_passthrough(self):
        """If id is already a string (shouldn't happen), don't double-wrap."""
        d = {"id": "LOCAL-42", "content": "hello"}
        result = scope_neuron_dict(d, "LOCAL")
        assert result["id"] == "LOCAL-42"

    def test_original_not_mutated(self):
        d = {"id": 42, "content": "hello"}
        scope_neuron_dict(d, "LOCAL")
        assert d["id"] == 42


class TestScopeEdgeDict:
    """scope_edge_dict wraps source_id and target_id."""

    def test_wraps_both_ids(self):
        d = {"source_id": 1, "target_id": 2, "reason": "related"}
        result = scope_edge_dict(d, "GLOBAL")
        assert result["source_id"] == "GLOBAL-1"
        assert result["target_id"] == "GLOBAL-2"
        assert result["reason"] == "related"

    def test_original_not_mutated(self):
        d = {"source_id": 1, "target_id": 2}
        scope_edge_dict(d, "LOCAL")
        assert d["source_id"] == 1


class TestScopeNeuronIdValue:
    """scope_neuron_id_value wraps 'neuron_id' field."""

    def test_wraps_neuron_id(self):
        d = {"neuron_id": 5, "key": "foo", "value": "bar"}
        result = scope_neuron_id_value(d, "LOCAL")
        assert result["neuron_id"] == "LOCAL-5"

    def test_no_neuron_id_passthrough(self):
        d = {"key": "foo"}
        result = scope_neuron_id_value(d, "LOCAL")
        assert result == d


class TestScopeRefMap:
    """scope_ref_map wraps ref label -> neuron_id values."""

    def test_wraps_int_values(self):
        rm = {"foo": 1, "bar": 2}
        result = scope_ref_map(rm, "LOCAL")
        assert result == {"foo": "LOCAL-1", "bar": "LOCAL-2"}

    def test_non_int_passthrough(self):
        rm = {"foo": "already-scoped"}
        result = scope_ref_map(rm, "LOCAL")
        assert result == {"foo": "already-scoped"}


class TestScopeList:
    """scope_list applies scope to a list of dicts."""

    def test_neuron_list(self):
        items = [{"id": 1, "content": "a"}, {"id": 2, "content": "b"}]
        result = scope_list(items, "LOCAL", "neuron")
        assert result[0]["id"] == "LOCAL-1"
        assert result[1]["id"] == "LOCAL-2"

    def test_edge_list(self):
        items = [{"source_id": 1, "target_id": 2}]
        result = scope_list(items, "GLOBAL", "edge")
        assert result[0]["source_id"] == "GLOBAL-1"
        assert result[0]["target_id"] == "GLOBAL-2"

    def test_empty_list(self):
        assert scope_list([], "LOCAL", "neuron") == []

    def test_unknown_kind_passthrough(self):
        items = [{"x": 1}]
        result = scope_list(items, "LOCAL", "unknown")
        assert result == items
