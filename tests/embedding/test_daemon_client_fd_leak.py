# =============================================================================
# Module: test_daemon_client_fd_leak.py
# Purpose: Regression test for the client fd-leak hygiene fix (task-74c20c2e,
#   e7afb5d) — embedding_daemon_client owns the socket with a finally-close on
#   ALL paths (incl. the second-connect failure after autostart, which previously
#   leaked the first socket's fd). Every socket created during a failed daemon
#   embed MUST be closed before falling back inproc. Tester-owned.
# =============================================================================

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from memory_cli.embedding import embedding_daemon_client as dc


def test_all_sockets_closed_on_daemon_connect_failure():
    created = []

    def fake_socket(*_a, **_k):
        m = MagicMock()
        m.connect.side_effect = OSError("connection refused")  # force the error path
        created.append(m)
        return m

    cfg = MagicMock()  # config only read for timeouts/paths; embed falls back
    with patch("socket.socket", side_effect=fake_socket), \
         patch.object(dc, "_try_autostart", lambda config: None), \
         patch.object(dc, "_inproc_embed", return_value=[[0.0] * 768]) as inproc:
        result = dc.embed(["probe text"], "query", cfg)

    # Fell back inproc (daemon unreachable) …
    assert result == [[0.0] * 768]
    assert inproc.called, "did not fall back to inproc on daemon connect failure"
    # … and EVERY socket opened along the way was closed (no fd leak).
    assert created, "expected at least one socket connect attempt"
    for s in created:
        assert s.close.called, (
            "a client socket was not closed on the daemon connect-failure path "
            "(fd leak — the finally-close hygiene fix regressed)"
        )
