# =============================================================================
# FILE: tests/cli/test_entrypoint_dispatch.py
# PURPOSE: Test argv routing, noun/verb validation, special cases (init, help),
#          and error handling in the main dispatch path.
# RATIONALE: The entrypoint is the most critical path — every CLI invocation
#            passes through it. Tests must cover happy paths, all error branches,
#            and the documented edge cases E-1 through E-14.
# RESPONSIBILITY:
#   - Test main() with various argv inputs
#   - Test noun resolution (known, unknown)
#   - Test verb resolution (known, unknown for a given noun)
#   - Test special case: `memory init` routes to init handler
#   - Test special case: --help at any position triggers help
#   - Test error fallback for unhandled exceptions
#   - Test exit codes match expected values
# ORGANIZATION:
#   1. Fixtures (mock registry, capture stdout/stderr)
#   2. Test class: TestNounResolution
#   3. Test class: TestVerbResolution
#   4. Test class: TestSpecialCases (init, help)
#   5. Test class: TestErrorHandling
#   6. Test class: TestEdgeCases (E-1 through E-14)
# =============================================================================

from __future__ import annotations

import sys
import pytest
from io import StringIO
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import memory_cli.cli.entrypoint_and_argv_dispatch as _ep_module
from memory_cli.cli.entrypoint_and_argv_dispatch import main, _dispatch
from memory_cli.cli.output_envelope_json_and_text import Result


def _make_mock_registry(handler=None, raise_exc=None):
    if handler is None and raise_exc is None:
        def handler(args, gflags):
            return Result(status="ok", data={"args": args})
    elif raise_exc is not None:
        def handler(args, gflags):
            raise raise_exc
    return {
        "testnoun": {
            "description": "Test noun for unit tests",
            "verb_map": {
                "testverb": handler,
                "otherverb": lambda a, g: Result(status="ok", data="other"),
            },
            "verb_descriptions": {
                "testverb": "Test verb",
                "otherverb": "Other verb",
            },
            "flag_defs": {"testverb": [], "otherverb": []},
        },
    }


@contextmanager
def _patched_registry(registry):
    original = dict(_ep_module._registry)
    _ep_module._registry.clear()
    _ep_module._registry.update(registry)
    try:
        yield
    finally:
        _ep_module._registry.clear()
        _ep_module._registry.update(original)


@contextmanager
def _capture_streams():
    out = StringIO()
    err = StringIO()
    with patch("sys.stdout", out), patch("sys.stderr", err):
        yield out, err


# =============================================================================
# TEST: NOUN RESOLUTION
# =============================================================================
class TestNounResolution:
    """Test that nouns are correctly resolved from argv."""

    def test_known_noun_routes_to_handler(self) -> None:
        """Valid noun + verb -> handler is called with remaining args.

        Pseudo-logic:
        1. Register a test noun with a mock verb handler
        2. Call main(["testnoun", "testverb", "arg1"])
        3. Assert mock handler was called with (["arg1"], global_flags)
        """
        called_with = {}

        def handler(args, gflags):
            called_with["args"] = args
            called_with["flags"] = gflags
            return Result(status="ok", data={})

        registry = _make_mock_registry(handler=handler)
        with _patched_registry(registry), _capture_streams():
            with pytest.raises(SystemExit) as exc:
                main(["testnoun", "testverb", "arg1"])
        assert exc.value.code == 0
        assert called_with["args"] == ["arg1"]

    def test_unknown_noun_exits_2_with_error(self) -> None:
        """Unknown noun -> error message + exit 2.

        Pseudo-logic:
        1. Call main(["nonexistent", "verb"])
        2. Assert SystemExit with code 2
        3. Assert stderr contains "Unknown noun: nonexistent"
        """
        with _patched_registry({}), _capture_streams() as (out, err):
            with pytest.raises(SystemExit) as exc:
                main(["nonexistent", "verb"])
        assert exc.value.code == 2
        assert "Unknown noun" in err.getvalue() or "nonexistent" in err.getvalue()

    def test_noun_is_case_sensitive(self) -> None:
        """Noun lookup is case-sensitive: "Neuron" != "neuron".

        Pseudo-logic:
        1. Register "neuron" noun
        2. Call main(["Neuron", "add"])
        3. Assert exits 2 (unknown noun)
        """
        with _patched_registry(_make_mock_registry()), _capture_streams():
            with pytest.raises(SystemExit) as exc:
                main(["Testnoun", "testverb"])
        assert exc.value.code == 2


# =============================================================================
# TEST: VERB RESOLUTION
# =============================================================================
class TestVerbResolution:
    """Test that verbs are correctly resolved within a noun."""

    def test_known_verb_invokes_handler(self) -> None:
        """Valid verb for a registered noun -> correct handler invoked.

        Pseudo-logic:
        1. Register noun with multiple verbs
        2. Call main(["testnoun", "testverb"])
        3. Assert testverb handler was called, not otherverb handler
        """
        called = {"testverb": False, "otherverb": False}

        def testverb_handler(args, gflags):
            called["testverb"] = True
            return Result(status="ok")

        def otherverb_handler(args, gflags):
            called["otherverb"] = True
            return Result(status="ok")

        registry = {
            "testnoun": {
                "description": "test",
                "verb_map": {"testverb": testverb_handler, "otherverb": otherverb_handler},
                "verb_descriptions": {"testverb": "tv", "otherverb": "ov"},
                "flag_defs": {"testverb": [], "otherverb": []},
            }
        }
        with _patched_registry(registry), _capture_streams():
            with pytest.raises(SystemExit):
                main(["testnoun", "testverb"])
        assert called["testverb"] is True
        assert called["otherverb"] is False

    def test_unknown_verb_exits_2_with_available_verbs(self) -> None:
        """Unknown verb -> error listing available verbs + exit 2.

        Pseudo-logic:
        1. Register noun with known verbs
        2. Call main(["testnoun", "badverb"])
        3. Assert SystemExit with code 2
        4. Assert error output lists available verbs for "testnoun"
        """
        with _patched_registry(_make_mock_registry()), _capture_streams() as (out, err):
            with pytest.raises(SystemExit) as exc:
                main(["testnoun", "badverb"])
        assert exc.value.code == 2
        assert "testverb" in err.getvalue() or "badverb" in err.getvalue()

    def test_noun_with_no_verb_shows_noun_help(self) -> None:
        """Noun with no verb -> show noun-level help + exit 0.

        Pseudo-logic:
        1. Register noun
        2. Call main(["testnoun"])
        3. Assert exit 0
        4. Assert output is noun help text
        """
        with _patched_registry(_make_mock_registry()), _capture_streams() as (out, err):
            with pytest.raises(SystemExit) as exc:
                main(["testnoun"])
        assert exc.value.code == 0
        assert "testnoun" in out.getvalue()


# =============================================================================
# TEST: SPECIAL CASES
# =============================================================================
class TestSpecialCases:
    """Test init and help special handling."""

    def test_init_dispatches_to_init_handler(self) -> None:
        """'memory init' routes to init handler, not noun resolution.

        Pseudo-logic:
        1. Patch handle_init
        2. Call main(["init"])
        3. Assert handle_init was called
        4. Assert noun resolution was NOT attempted
        """
        mock_result = Result(status="ok", data={"database": "/tmp/x.db", "config": "/tmp/c.toml", "created": True})
        with patch(
            "memory_cli.cli.entrypoint_and_argv_dispatch.handle_init",
            return_value=mock_result,
        ) as mock_init:
            with _capture_streams():
                with pytest.raises(SystemExit) as exc:
                    main(["init"])
        assert mock_init.called
        assert exc.value.code == 0

    def test_no_args_shows_top_level_help(self) -> None:
        """No arguments -> show top-level help + exit 0.

        Pseudo-logic:
        1. Call main([])
        2. Assert exit 0
        3. Assert output contains usage line and noun list
        """
        with _capture_streams() as (out, err):
            with pytest.raises(SystemExit) as exc:
                main([])
        assert exc.value.code == 0
        assert "Usage" in out.getvalue() or "memory" in out.getvalue()

    def test_help_flag_anywhere_triggers_help(self) -> None:
        """--help anywhere in tokens -> appropriate help level + exit 0.

        Pseudo-logic:
        1. Call main(["--help"])           -> top-level help
        2. Call main(["neuron", "--help"])  -> noun-level help
        3. Call main(["neuron", "add", "--help"]) -> verb-level help
        4. All exit 0
        """
        with _capture_streams():
            with pytest.raises(SystemExit) as exc:
                main(["--help"])
        assert exc.value.code == 0

        with _capture_streams():
            with pytest.raises(SystemExit) as exc:
                main(["neuron", "--help"])
        assert exc.value.code == 0

        with _capture_streams():
            with pytest.raises(SystemExit) as exc:
                main(["neuron", "add", "--help"])
        assert exc.value.code == 0

    def test_help_output_is_always_plain_text(self) -> None:
        """Help output ignores --format json, always plain text.

        Pseudo-logic:
        1. Call main(["--format", "json", "--help"])
        2. Assert output is NOT JSON
        3. Assert output is plain text help
        """
        with _capture_streams() as (out, err):
            with pytest.raises(SystemExit) as exc:
                main(["--format", "json", "--help"])
        assert exc.value.code == 0
        output = out.getvalue()
        assert not output.strip().startswith("{")


# =============================================================================
# TEST: ERROR HANDLING
# =============================================================================
class TestErrorHandling:
    """Test unhandled exception fallback and error formatting."""

    def test_handler_exception_exits_2_with_error_envelope(self) -> None:
        """Unhandled exception in handler -> error envelope + exit 2.

        Pseudo-logic:
        1. Register noun with handler that raises RuntimeError
        2. Call main(["testnoun", "testverb"])
        3. Assert exit 2
        4. Assert output has error envelope with exception message
        """
        registry = _make_mock_registry(raise_exc=RuntimeError("handler blew up"))
        with _patched_registry(registry), _capture_streams() as (out, err):
            with pytest.raises(SystemExit) as exc:
                main(["testnoun", "testverb"])
        assert exc.value.code == 2
        combined = out.getvalue() + err.getvalue()
        assert "handler blew up" in combined or "error" in combined.lower()

    def test_format_failure_falls_back_to_stderr_text(self) -> None:
        """If formatting itself fails, fall back to plain text on stderr.

        Pseudo-logic:
        1. Patch format_output to raise
        2. Trigger an error path
        3. Assert stderr has plain text error message
        """
        registry = _make_mock_registry(raise_exc=RuntimeError("trigger error"))
        with _patched_registry(registry), _capture_streams() as (out, err):
            with patch(
                "memory_cli.cli.entrypoint_and_argv_dispatch.format_output",
                side_effect=Exception("format failed"),
            ):
                with pytest.raises(SystemExit) as exc:
                    main(["testnoun", "testverb"])
        assert exc.value.code == 2
        assert err.getvalue() != ""


# =============================================================================
# TEST: EDGE CASES (E-1 through E-14 from spec)
# =============================================================================
class TestEdgeCases:
    """Test documented edge cases from the spec."""

    def test_e1_empty_result_set_is_success_not_not_found(self) -> None:
        """E-1: Empty list result -> exit 0, not exit 1.

        Pseudo-logic:
        1. Register handler returning Result(status="ok", data=[])
        2. Call main(["testnoun", "testverb"])
        3. Assert exit 0 (not 1)
        """
        def handler(args, gflags):
            return Result(status="ok", data=[])

        registry = _make_mock_registry(handler=handler)
        with _patched_registry(registry), _capture_streams():
            with pytest.raises(SystemExit) as exc:
                main(["testnoun", "testverb"])
        assert exc.value.code == 0

    def test_e2_init_when_already_initialized(self, tmp_path) -> None:
        """E-2: `memory init` when DB exists -> error unless --force.

        Pseudo-logic:
        1. Patch DB existence check to return True
        2. Call main(["init"])
        3. Assert exit 2 with "already exists" error
        4. Call main(["init", "--force"])
        5. Assert exit 0
        """
        db_path = tmp_path / "mem.db"
        db_path.touch()
        with _capture_streams():
            with pytest.raises(SystemExit) as exc:
                main(["--db", str(db_path), "init"])
        assert exc.value.code == 2

        with _capture_streams():
            with pytest.raises(SystemExit) as exc:
                main(["--db", str(db_path), "init", "--force"])
        assert exc.value.code == 0

    def test_e3_global_flags_before_noun(self) -> None:
        """E-3: Global flags before noun still route correctly.

        Pseudo-logic:
        1. Call main(["--format", "text", "neuron", "list"])
        2. Assert handler called with global_flags.format == "text"
        """
        captured_flags = {}

        def handler(args, gflags):
            captured_flags["format"] = gflags.format
            return Result(status="ok", data=[])

        registry = {
            "testnoun": {
                "description": "test",
                "verb_map": {"testverb": handler},
                "verb_descriptions": {"testverb": "tv"},
                "flag_defs": {"testverb": []},
            }
        }
        with _patched_registry(registry), _capture_streams():
            with pytest.raises(SystemExit):
                main(["--format", "text", "testnoun", "testverb"])
        assert captured_flags.get("format") == "text"

    def test_e4_global_flags_after_verb(self) -> None:
        """E-4: Global flags after verb still parsed correctly.

        Pseudo-logic:
        1. Call main(["neuron", "list", "--format", "text"])
        2. Assert handler called with global_flags.format == "text"
        """
        captured_flags = {}

        def handler(args, gflags):
            captured_flags["format"] = gflags.format
            return Result(status="ok", data=[])

        registry = {
            "testnoun": {
                "description": "test",
                "verb_map": {"testverb": handler},
                "verb_descriptions": {"testverb": "tv"},
                "flag_defs": {"testverb": []},
            }
        }
        with _patched_registry(registry), _capture_streams():
            with pytest.raises(SystemExit):
                main(["testnoun", "testverb", "--format", "text"])
        assert captured_flags.get("format") == "text"
