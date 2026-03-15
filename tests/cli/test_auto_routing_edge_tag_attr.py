# =============================================================================
# FILE: tests/cli/test_auto_routing_edge_tag_attr.py
# PURPOSE: Verify that edge, tag, and attr handlers respect GLOBAL-/LOCAL-/
#          fingerprint: scope prefixes and route to the correct DB store.
# RATIONALE: Task #22 — backlog #39 showed that `memory edge list --neuron
#            GLOBAL-157` from a project with a local .memory/ fails because
#            edge/tag/attr handlers ignored the scope from parse_handle() and
#            always queried the first (local) connection.
# RESPONSIBILITY:
#   - Test each of the 9 handlers (edge add/list/remove, tag add/list/remove,
#     attr add/list/remove) routes to GLOBAL conn when GLOBAL-N is given
#   - Test each handler uses first (local) conn when no scope prefix is given
#   - Test each handler returns not_found when requested scope is unavailable
# ORGANIZATION:
#   1. Shared fixtures
#   2. TestEdgeAutoRouting — edge add, list, remove
#   3. TestTagAutoRouting — tag add, list, remove
#   4. TestAttrAutoRouting — attr add, list, remove
# =============================================================================

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# SHARED FIXTURES
# =============================================================================

@pytest.fixture
def local_conn():
    return MagicMock(name="local_conn")


@pytest.fixture
def global_conn():
    return MagicMock(name="global_conn")


@pytest.fixture
def two_connections(local_conn, global_conn):
    """Layered connections: LOCAL first, GLOBAL second."""
    return [(local_conn, "LOCAL"), (global_conn, "GLOBAL")]


@pytest.fixture
def global_flags():
    return SimpleNamespace(config=None, db=None, global_only=False)


def _mock_neuron(nid=42, tags=None, attrs=None):
    """Return a minimal neuron dict."""
    return {
        "id": nid,
        "content": "test neuron",
        "tags": tags or ["t1"],
        "attrs": attrs or {"k": "v"},
        "created_at": "2026-01-01T00:00:00",
        "source": None,
    }


# =============================================================================
# TestEdgeAutoRouting
# =============================================================================

# Handlers use inline `from X import Y` — patch the __init__ namespace so the
# name is replaced at the point where the handler resolves it.
_LAYERED = "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections"
_EDGE_ADD = "memory_cli.edge.edge_add"
_EDGE_LIST = "memory_cli.edge.edge_list"
_EDGE_REMOVE = "memory_cli.edge.edge_remove"
_NEURON_GET = "memory_cli.neuron.neuron_get"
_NEURON_UPDATE = "memory_cli.neuron.neuron_update"


class TestEdgeAddAutoRouting:
    """edge add routes by source/target handle scope."""

    def _call(self, args, global_flags, connections):
        from memory_cli.cli.noun_handlers.edge_noun_handler import handle_add
        with patch(_LAYERED, return_value=connections):
            return handle_add(args, global_flags)

    def test_global_source_routes_to_global_conn(self, global_conn, global_flags, two_connections):
        """GLOBAL-1 as source -> writes to global_conn, not local."""
        fake_edge = {"source_id": 1, "target_id": 2, "reason": "related_to", "weight": 1.0}
        with patch(_EDGE_ADD, return_value=fake_edge):
            result = self._call(["GLOBAL-1", "GLOBAL-2"], global_flags, two_connections)
        assert result.status == "ok"
        global_conn.commit.assert_called_once()

    def test_no_scope_uses_first_conn(self, local_conn, global_conn, global_flags, two_connections):
        """Bare IDs (no scope) -> writes to first (local) conn."""
        fake_edge = {"source_id": 1, "target_id": 2, "reason": "related_to", "weight": 1.0}
        with patch(_EDGE_ADD, return_value=fake_edge):
            result = self._call(["1", "2"], global_flags, two_connections)
        assert result.status == "ok"
        local_conn.commit.assert_called_once()
        global_conn.commit.assert_not_called()

    def test_missing_scope_returns_not_found(self, global_flags, two_connections):
        """GLOBAL-1 when only LOCAL store exists -> not_found."""
        local_only = [(two_connections[0][0], "LOCAL")]
        result = self._call(["GLOBAL-1", "GLOBAL-2"], global_flags, local_only)
        assert result.status == "not_found"
        assert "GLOBAL" in result.error


class TestEdgeListAutoRouting:
    """edge list --neuron routes by handle scope."""

    def _call(self, args, global_flags, connections):
        from memory_cli.cli.noun_handlers.edge_noun_handler import handle_list
        with patch(_LAYERED, return_value=connections):
            return handle_list(args, global_flags)

    def test_global_neuron_routes_to_global_conn(self, global_conn, global_flags, two_connections):
        """GLOBAL-157 -> edge_list called on global_conn only."""
        with patch(_EDGE_LIST, return_value=[]) as mock_el:
            result = self._call(["--neuron", "GLOBAL-157"], global_flags, two_connections)
        assert result.status == "ok"
        # edge_list was called exactly once, on the global connection
        assert mock_el.call_count == 1
        assert mock_el.call_args[0][0] is global_conn

    def test_no_scope_queries_all_connections(self, local_conn, global_conn, global_flags, two_connections):
        """Bare --neuron 157 -> edge_list called on both connections."""
        with patch(_EDGE_LIST, return_value=[]) as mock_el:
            result = self._call(["--neuron", "157"], global_flags, two_connections)
        assert result.status == "ok"
        assert mock_el.call_count == 2

    def test_missing_scope_returns_not_found(self, global_flags, two_connections):
        """GLOBAL-157 when only LOCAL store exists -> not_found."""
        local_only = [(two_connections[0][0], "LOCAL")]
        result = self._call(["--neuron", "GLOBAL-157"], global_flags, local_only)
        assert result.status == "not_found"
        assert "GLOBAL" in result.error

    def test_local_neuron_routes_to_local_conn(self, local_conn, global_conn, global_flags, two_connections):
        """LOCAL-42 -> edge_list called on local_conn only."""
        with patch(_EDGE_LIST, return_value=[]) as mock_el:
            result = self._call(["--neuron", "LOCAL-42"], global_flags, two_connections)
        assert result.status == "ok"
        assert mock_el.call_count == 1
        assert mock_el.call_args[0][0] is local_conn


class TestEdgeRemoveAutoRouting:
    """edge remove routes by source/target handle scope."""

    def _call(self, args, global_flags, connections):
        from memory_cli.cli.noun_handlers.edge_noun_handler import handle_remove
        with patch(_LAYERED, return_value=connections):
            return handle_remove(args, global_flags)

    def test_global_source_routes_to_global_conn(self, global_conn, global_flags, two_connections):
        """GLOBAL-1 as source -> removes from global_conn."""
        fake_result = {"source_id": 1, "target_id": 2, "removed": True}
        with patch(_EDGE_REMOVE, return_value=fake_result):
            result = self._call(["GLOBAL-1", "GLOBAL-2"], global_flags, two_connections)
        assert result.status == "ok"
        global_conn.commit.assert_called_once()

    def test_no_scope_uses_first_conn(self, local_conn, global_conn, global_flags, two_connections):
        """Bare IDs -> removes from first (local) conn."""
        fake_result = {"source_id": 1, "target_id": 2, "removed": True}
        with patch(_EDGE_REMOVE, return_value=fake_result):
            result = self._call(["1", "2"], global_flags, two_connections)
        assert result.status == "ok"
        local_conn.commit.assert_called_once()
        global_conn.commit.assert_not_called()

    def test_missing_scope_returns_not_found(self, global_flags, two_connections):
        """GLOBAL-1 when only LOCAL store exists -> not_found."""
        local_only = [(two_connections[0][0], "LOCAL")]
        result = self._call(["GLOBAL-1", "GLOBAL-2"], global_flags, local_only)
        assert result.status == "not_found"


# =============================================================================
# TestTagAutoRouting
# =============================================================================

class TestTagAddAutoRouting:
    """tag add routes by neuron handle scope."""

    def _call(self, args, global_flags, connections):
        from memory_cli.cli.noun_handlers.tag_noun_handler import handle_add
        with patch(_LAYERED, return_value=connections):
            return handle_add(args, global_flags)

    def test_global_neuron_routes_to_global_conn(self, global_conn, global_flags, two_connections):
        """GLOBAL-42 tag add -> reads/writes to global_conn."""
        neuron = _mock_neuron(42)
        with patch(_NEURON_GET, return_value=neuron), \
             patch(_NEURON_UPDATE) as mock_upd:
            result = self._call(["GLOBAL-42", "mytag"], global_flags, two_connections)
        assert result.status == "ok"
        assert result.data["neuron_id"] == "GLOBAL-42"
        mock_upd.assert_called_once()
        assert mock_upd.call_args[0][0] is global_conn

    def test_no_scope_uses_first_conn(self, local_conn, global_conn, global_flags, two_connections):
        """Bare ID -> reads/writes to first (local) conn."""
        neuron = _mock_neuron(42)
        with patch(_NEURON_GET, return_value=neuron), \
             patch(_NEURON_UPDATE) as mock_upd:
            result = self._call(["42", "mytag"], global_flags, two_connections)
        assert result.status == "ok"
        assert mock_upd.call_args[0][0] is local_conn

    def test_neuron_not_found_in_target_store(self, global_conn, global_flags, two_connections):
        """GLOBAL-42 but neuron doesn't exist -> not_found."""
        with patch(_NEURON_GET, return_value=None):
            result = self._call(["GLOBAL-42", "mytag"], global_flags, two_connections)
        assert result.status == "not_found"

    def test_missing_scope_returns_not_found(self, global_flags, two_connections):
        """GLOBAL-42 when only LOCAL store -> not_found."""
        local_only = [(two_connections[0][0], "LOCAL")]
        result = self._call(["GLOBAL-42", "mytag"], global_flags, local_only)
        assert result.status == "not_found"
        assert "GLOBAL" in result.error


class TestTagListAutoRouting:
    """tag list --neuron routes by handle scope."""

    def _call(self, args, global_flags, connections):
        from memory_cli.cli.noun_handlers.tag_noun_handler import handle_list
        with patch(_LAYERED, return_value=connections):
            return handle_list(args, global_flags)

    def test_global_neuron_routes_to_global_conn(self, local_conn, global_conn, global_flags, two_connections):
        """GLOBAL-42 --neuron -> looks up in global_conn only."""
        global_neuron = _mock_neuron(42, tags=["global_tag"])

        def fake_get(conn, nid):
            return global_neuron if conn is global_conn else None

        with patch(_NEURON_GET, side_effect=fake_get):
            result = self._call(["--neuron", "GLOBAL-42"], global_flags, two_connections)
        assert result.status == "ok"
        assert result.data == ["global_tag"]

    def test_no_scope_searches_all_stores(self, local_conn, global_conn, global_flags, two_connections):
        """Bare --neuron 42 -> searches all stores."""
        local_neuron = _mock_neuron(42, tags=["local_tag"])

        def fake_get(conn, nid):
            return local_neuron if conn is local_conn else None

        with patch(_NEURON_GET, side_effect=fake_get):
            result = self._call(["--neuron", "42"], global_flags, two_connections)
        assert result.status == "ok"
        assert result.data == ["local_tag"]

    def test_missing_scope_returns_not_found(self, global_flags, two_connections):
        """GLOBAL-42 when only LOCAL store -> not_found."""
        local_only = [(two_connections[0][0], "LOCAL")]
        result = self._call(["--neuron", "GLOBAL-42"], global_flags, local_only)
        assert result.status == "not_found"


class TestTagRemoveAutoRouting:
    """tag remove routes by neuron handle scope."""

    def _call(self, args, global_flags, connections):
        from memory_cli.cli.noun_handlers.tag_noun_handler import handle_remove
        with patch(_LAYERED, return_value=connections):
            return handle_remove(args, global_flags)

    def test_global_neuron_routes_to_global_conn(self, global_conn, global_flags, two_connections):
        """GLOBAL-42 tag remove -> writes to global_conn."""
        neuron = _mock_neuron(42)
        with patch(_NEURON_GET, return_value=neuron), \
             patch(_NEURON_UPDATE) as mock_upd:
            result = self._call(["GLOBAL-42", "mytag"], global_flags, two_connections)
        assert result.status == "ok"
        assert result.data["neuron_id"] == "GLOBAL-42"
        assert mock_upd.call_args[0][0] is global_conn

    def test_no_scope_uses_first_conn(self, local_conn, global_flags, two_connections):
        """Bare ID -> writes to first (local) conn."""
        neuron = _mock_neuron(42)
        with patch(_NEURON_GET, return_value=neuron), \
             patch(_NEURON_UPDATE) as mock_upd:
            result = self._call(["42", "mytag"], global_flags, two_connections)
        assert result.status == "ok"
        assert mock_upd.call_args[0][0] is local_conn

    def test_missing_scope_returns_not_found(self, global_flags, two_connections):
        """GLOBAL-42 when only LOCAL store -> not_found."""
        local_only = [(two_connections[0][0], "LOCAL")]
        result = self._call(["GLOBAL-42", "mytag"], global_flags, local_only)
        assert result.status == "not_found"


# =============================================================================
# TestAttrAutoRouting
# =============================================================================

class TestAttrAddAutoRouting:
    """attr add routes by neuron handle scope."""

    def _call(self, args, global_flags, connections):
        from memory_cli.cli.noun_handlers.attr_noun_handler import handle_add
        with patch(_LAYERED, return_value=connections):
            return handle_add(args, global_flags)

    def test_global_neuron_routes_to_global_conn(self, global_conn, global_flags, two_connections):
        """GLOBAL-42 attr add -> writes to global_conn."""
        neuron = _mock_neuron(42)
        with patch(_NEURON_GET, return_value=neuron), \
             patch(_NEURON_UPDATE) as mock_upd:
            result = self._call(["GLOBAL-42", "mykey", "myval"], global_flags, two_connections)
        assert result.status == "ok"
        assert result.data["neuron_id"] == "GLOBAL-42"
        assert mock_upd.call_args[0][0] is global_conn

    def test_no_scope_uses_first_conn(self, local_conn, global_flags, two_connections):
        """Bare ID -> writes to first (local) conn."""
        neuron = _mock_neuron(42)
        with patch(_NEURON_GET, return_value=neuron), \
             patch(_NEURON_UPDATE) as mock_upd:
            result = self._call(["42", "mykey", "myval"], global_flags, two_connections)
        assert result.status == "ok"
        assert mock_upd.call_args[0][0] is local_conn

    def test_missing_scope_returns_not_found(self, global_flags, two_connections):
        """GLOBAL-42 when only LOCAL store -> not_found."""
        local_only = [(two_connections[0][0], "LOCAL")]
        result = self._call(["GLOBAL-42", "mykey", "myval"], global_flags, local_only)
        assert result.status == "not_found"
        assert "GLOBAL" in result.error


class TestAttrListAutoRouting:
    """attr list routes by neuron handle scope."""

    def _call(self, args, global_flags, connections):
        from memory_cli.cli.noun_handlers.attr_noun_handler import handle_list
        with patch(_LAYERED, return_value=connections):
            return handle_list(args, global_flags)

    def test_global_neuron_routes_to_global_conn(self, local_conn, global_conn, global_flags, two_connections):
        """GLOBAL-42 attr list -> reads from global_conn only."""
        global_neuron = _mock_neuron(42, attrs={"env": "prod"})

        def fake_get(conn, nid):
            return global_neuron if conn is global_conn else None

        with patch(_NEURON_GET, side_effect=fake_get):
            result = self._call(["GLOBAL-42"], global_flags, two_connections)
        assert result.status == "ok"
        assert result.data == {"env": "prod"}

    def test_no_scope_searches_all_stores(self, local_conn, global_conn, global_flags, two_connections):
        """Bare ID -> searches all stores, returns first match."""
        local_neuron = _mock_neuron(42, attrs={"env": "local"})

        def fake_get(conn, nid):
            return local_neuron if conn is local_conn else None

        with patch(_NEURON_GET, side_effect=fake_get):
            result = self._call(["42"], global_flags, two_connections)
        assert result.status == "ok"
        assert result.data == {"env": "local"}

    def test_missing_scope_returns_not_found(self, global_flags, two_connections):
        """GLOBAL-42 when only LOCAL store -> not_found."""
        local_only = [(two_connections[0][0], "LOCAL")]
        result = self._call(["GLOBAL-42"], global_flags, local_only)
        assert result.status == "not_found"


class TestAttrRemoveAutoRouting:
    """attr remove routes by neuron handle scope."""

    def _call(self, args, global_flags, connections):
        from memory_cli.cli.noun_handlers.attr_noun_handler import handle_remove
        with patch(_LAYERED, return_value=connections):
            return handle_remove(args, global_flags)

    def test_global_neuron_routes_to_global_conn(self, global_conn, global_flags, two_connections):
        """GLOBAL-42 attr remove -> writes to global_conn."""
        neuron = _mock_neuron(42)
        with patch(_NEURON_GET, return_value=neuron), \
             patch(_NEURON_UPDATE) as mock_upd:
            result = self._call(["GLOBAL-42", "mykey"], global_flags, two_connections)
        assert result.status == "ok"
        assert result.data["neuron_id"] == "GLOBAL-42"
        assert mock_upd.call_args[0][0] is global_conn

    def test_no_scope_uses_first_conn(self, local_conn, global_flags, two_connections):
        """Bare ID -> writes to first (local) conn."""
        neuron = _mock_neuron(42)
        with patch(_NEURON_GET, return_value=neuron), \
             patch(_NEURON_UPDATE) as mock_upd:
            result = self._call(["42", "mykey"], global_flags, two_connections)
        assert result.status == "ok"
        assert mock_upd.call_args[0][0] is local_conn

    def test_missing_scope_returns_not_found(self, global_flags, two_connections):
        """GLOBAL-42 when only LOCAL store -> not_found."""
        local_only = [(two_connections[0][0], "LOCAL")]
        result = self._call(["GLOBAL-42", "mykey"], global_flags, local_only)
        assert result.status == "not_found"
