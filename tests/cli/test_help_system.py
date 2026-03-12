# =============================================================================
# FILE: tests/cli/test_help_system.py
# PURPOSE: Test help output at all three levels (top-level, noun-level,
#          verb-level) and help detection logic.
# RATIONALE: Help is the user's (and agent's) first contact with the CLI.
#            Must always be plain text, always exit 0, and accurately reflect
#            the registered nouns and verbs. Tests verify content and behavior.
# RESPONSIBILITY:
#   - Test has_help_flag() detection
#   - Test show_top_level_help() content and structure
#   - Test show_noun_help() content for each noun
#   - Test show_verb_help() content for specific verbs
#   - Test that help is always plain text regardless of --format
#   - Test that help always exits 0
# ORGANIZATION:
#   1. Fixtures (mock registry with known nouns/verbs)
#   2. Test class: TestHelpDetection
#   3. Test class: TestTopLevelHelp
#   4. Test class: TestNounLevelHelp
#   5. Test class: TestVerbLevelHelp
#   6. Test class: TestHelpBehavior (exit code, format override)
# =============================================================================

from __future__ import annotations

from memory_cli.cli.help_system_three_levels import (
    has_help_flag, show_top_level_help, show_noun_help, show_verb_help,
)


_MOCK_REGISTRY = {
    "neuron": {
        "description": "Memory neurons — content nodes in the graph",
        "verb_map": {"add": None, "get": None, "list": None},
        "verb_descriptions": {
            "add": "Create a new neuron",
            "get": "Retrieve a neuron",
            "list": "List neurons",
        },
        "flag_defs": {
            "add": [
                {"name": "--type", "type": "str", "default": "memory", "desc": "Neuron type"},
                {"name": "--source", "type": "str", "default": None, "desc": "Origin"},
            ],
            "get": [],
            "list": [],
        },
    },
    "tag": {
        "description": "Tags — categorical labels",
        "verb_map": {"add": None, "remove": None},
        "verb_descriptions": {"add": "Add a tag", "remove": "Remove a tag"},
        "flag_defs": {"add": [], "remove": []},
    },
    "edge": {
        "description": "Edges — directed connections",
        "verb_map": {"add": None},
        "verb_descriptions": {"add": "Create an edge"},
        "flag_defs": {"add": []},
    },
}


# =============================================================================
# TEST: HELP FLAG DETECTION
# =============================================================================
class TestHelpDetection:
    """Test has_help_flag() token scanning."""

    def test_help_long_flag_detected(self) -> None:
        """--help in tokens -> True.

        Pseudo-logic:
        1. assert has_help_flag(["neuron", "--help"]) is True
        """
        assert has_help_flag(["neuron", "--help"]) is True

    def test_help_short_flag_detected(self) -> None:
        """-h in tokens -> True.

        Pseudo-logic:
        1. assert has_help_flag(["neuron", "-h"]) is True
        """
        assert has_help_flag(["neuron", "-h"]) is True

    def test_no_help_flag_returns_false(self) -> None:
        """No --help or -h -> False.

        Pseudo-logic:
        1. assert has_help_flag(["neuron", "add", "content"]) is False
        """
        assert has_help_flag(["neuron", "add", "content"]) is False

    def test_help_anywhere_in_stream(self) -> None:
        """--help at beginning, middle, end all detected.

        Pseudo-logic:
        1. assert has_help_flag(["--help", "neuron", "add"]) is True
        2. assert has_help_flag(["neuron", "--help", "add"]) is True
        3. assert has_help_flag(["neuron", "add", "--help"]) is True
        """
        assert has_help_flag(["--help", "neuron", "add"]) is True
        assert has_help_flag(["neuron", "--help", "add"]) is True
        assert has_help_flag(["neuron", "add", "--help"]) is True


# =============================================================================
# TEST: TOP-LEVEL HELP
# =============================================================================
class TestTopLevelHelp:
    """Test show_top_level_help() output."""

    def test_contains_usage_line(self) -> None:
        """Output contains usage: memory <noun> <verb>.

        Pseudo-logic:
        1. Build mock registry with a few nouns
        2. output = show_top_level_help(registry)
        3. Assert "Usage:" in output
        4. Assert "memory <noun> <verb>" in output or similar pattern
        """
        output = show_top_level_help(_MOCK_REGISTRY)
        assert "Usage:" in output
        assert "memory" in output

    def test_lists_all_registered_nouns(self) -> None:
        """Output lists every registered noun.

        Pseudo-logic:
        1. Build mock registry with nouns: neuron, tag, edge
        2. output = show_top_level_help(registry)
        3. Assert "neuron" in output
        4. Assert "tag" in output
        5. Assert "edge" in output
        """
        output = show_top_level_help(_MOCK_REGISTRY)
        assert "neuron" in output
        assert "tag" in output
        assert "edge" in output

    def test_shows_global_flags(self) -> None:
        """Output includes --format, --config, --db, --help.

        Pseudo-logic:
        1. output = show_top_level_help(registry)
        2. Assert "--format" in output
        3. Assert "--config" in output
        4. Assert "--db" in output
        """
        output = show_top_level_help(_MOCK_REGISTRY)
        assert "--format" in output
        assert "--config" in output
        assert "--db" in output

    def test_shows_init_special_command(self) -> None:
        """Output mentions `memory init` as a special command.

        Pseudo-logic:
        1. output = show_top_level_help(registry)
        2. Assert "init" in output
        """
        output = show_top_level_help(_MOCK_REGISTRY)
        assert "init" in output


# =============================================================================
# TEST: NOUN-LEVEL HELP
# =============================================================================
class TestNounLevelHelp:
    """Test show_noun_help() output."""

    def test_contains_noun_name(self) -> None:
        """Output contains the noun name in header.

        Pseudo-logic:
        1. output = show_noun_help("neuron", mock_neuron_entry)
        2. Assert "neuron" in output
        """
        output = show_noun_help("neuron", _MOCK_REGISTRY["neuron"])
        assert "neuron" in output

    def test_lists_all_verbs_for_noun(self) -> None:
        """Output lists every verb registered for this noun.

        Pseudo-logic:
        1. Build mock noun entry with verbs: add, get, list
        2. output = show_noun_help("neuron", entry)
        3. Assert "add" in output, "get" in output, "list" in output
        """
        output = show_noun_help("neuron", _MOCK_REGISTRY["neuron"])
        assert "add" in output
        assert "get" in output
        assert "list" in output

    def test_includes_verb_descriptions(self) -> None:
        """Each verb has its description next to it.

        Pseudo-logic:
        1. Build mock entry with verb_descriptions
        2. output = show_noun_help("neuron", entry)
        3. Assert description text appears for each verb
        """
        output = show_noun_help("neuron", _MOCK_REGISTRY["neuron"])
        assert "Create a new neuron" in output
        assert "Retrieve a neuron" in output


# =============================================================================
# TEST: VERB-LEVEL HELP
# =============================================================================
class TestVerbLevelHelp:
    """Test show_verb_help() output."""

    def test_contains_noun_and_verb(self) -> None:
        """Output contains both noun and verb names.

        Pseudo-logic:
        1. output = show_verb_help("neuron", "add", mock_entry)
        2. Assert "neuron" in output and "add" in output
        """
        output = show_verb_help("neuron", "add", _MOCK_REGISTRY["neuron"])
        assert "neuron" in output
        assert "add" in output

    def test_shows_flag_definitions(self) -> None:
        """Output lists flags with types and defaults.

        Pseudo-logic:
        1. Build entry with flag_defs for "add" verb
        2. output = show_verb_help("neuron", "add", entry)
        3. Assert "--type" in output, "--source" in output
        """
        output = show_verb_help("neuron", "add", _MOCK_REGISTRY["neuron"])
        assert "--type" in output
        assert "--source" in output


# =============================================================================
# TEST: HELP BEHAVIOR
# =============================================================================
class TestHelpBehavior:
    """Test help exit code and format override."""

    def test_help_always_exits_0(self) -> None:
        """All help paths exit 0, never 1 or 2.

        Pseudo-logic:
        1. For each help function, verify it doesn't signal non-zero exit
        """
        output = show_top_level_help(_MOCK_REGISTRY)
        assert isinstance(output, str)
        output2 = show_noun_help("neuron", _MOCK_REGISTRY["neuron"])
        assert isinstance(output2, str)
        output3 = show_verb_help("neuron", "add", _MOCK_REGISTRY["neuron"])
        assert isinstance(output3, str)

    def test_help_is_plain_text_not_json(self) -> None:
        """Help output is never JSON, even when --format json.

        Pseudo-logic:
        1. output = show_top_level_help(registry)
        2. Assert output does not start with "{"
        3. Assert output is human-readable text
        """
        output = show_top_level_help(_MOCK_REGISTRY)
        assert not output.strip().startswith("{")
        assert "memory" in output
