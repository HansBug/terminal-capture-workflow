"""Tests for the ``wait_for_prompt`` step field and the shared default
prompt regex.

Tracks issue #6's wait_for_prompt half. (The lint half depends on the
``validate-scenario`` subcommand introduced in #9 and is intentionally
out of scope here.)

The field can be set on a ``command`` step or as a standalone
``wait_for_prompt`` action; in both forms a ``true`` value selects the
shared :data:`DEFAULT_PROMPT_REGEX` and a string value is used verbatim
as the regex pattern. When a ``command`` step sets both
``wait_for_text`` and ``wait_for_prompt``, the rendered VHS tape must
wait on the text first (specific summary line) and the prompt second
(command actually returned) — matching the ``field-notes.md``-recommended
"wait on summary, then wait on prompt" pattern.
"""

from pathlib import Path

import re

import pytest

from terminal_capture import (
    DEFAULT_PROMPT_REGEX,
    build_vhs_tape,
    resolve_wait_prompt_pattern,
)


# --- resolve_wait_prompt_pattern ---

@pytest.mark.parametrize(
    "value, expected",
    [
        (True, DEFAULT_PROMPT_REGEX),
        ("custom>$", "custom>$"),
        ("❯", "❯"),
        (False, None),
        (None, None),
        ("", None),  # empty string treated as no-op
    ],
)
def test_resolve_wait_prompt_pattern_accepts_bool_string_and_none(value, expected):
    assert resolve_wait_prompt_pattern(value) == expected


@pytest.mark.parametrize("bad", [42, 3.14, ["a", "b"], {"a": 1}])
def test_resolve_wait_prompt_pattern_rejects_other_types(bad):
    with pytest.raises(ValueError, match="wait_for_prompt"):
        resolve_wait_prompt_pattern(bad)


# --- regex correctness ---

@pytest.mark.parametrize(
    "prompt_line",
    [
        "user@host:~$ ",
        "user@host:~# ",
        "demo% ",
        "❯ ",
        "▶ ",
        "> ",
        "(venv) project$ ",
        "user@host:~$",  # no trailing space
        "demo$",
    ],
)
def test_default_regex_matches_common_prompts(prompt_line):
    assert re.search(DEFAULT_PROMPT_REGEX, prompt_line, re.MULTILINE), (
        f"default prompt regex must match {prompt_line!r}"
    )


@pytest.mark.parametrize(
    "non_prompt_line",
    [
        "echo hello",
        "loading data...",
        "Hello, World!",
        "12345",
        "compiling foo.c",
    ],
)
def test_default_regex_does_not_match_plain_output(non_prompt_line):
    assert not re.search(DEFAULT_PROMPT_REGEX, non_prompt_line, re.MULTILINE)


# --- VHS tape integration ---

def _build_tape(scenario, tmp_path):
    scenario.setdefault("name", "test")
    scenario.setdefault("cwd", str(tmp_path))
    return build_vhs_tape(scenario, out_dir=tmp_path).splitlines()


def test_vhs_tape_command_with_wait_for_prompt_true(tmp_path):
    """A command step with `wait_for_prompt: true` produces a Wait+Screen
    line that uses the default prompt regex."""
    scenario = {
        "vhs": {},
        "steps": [
            {
                "action": "command",
                "text": "echo hi",
                "wait_for_prompt": True,
            }
        ],
    }
    tape = _build_tape(scenario, tmp_path)
    wait_lines = [line for line in tape if line.startswith("Wait+Screen")]
    assert wait_lines, f"Expected a Wait+Screen line; got:\n{chr(10).join(tape)}"
    # The default regex contains '$' (anchored prompt char).
    assert "$" in wait_lines[0]


def test_vhs_tape_command_with_both_text_and_prompt_waits_in_order(tmp_path):
    """When both `wait_for_text` and `wait_for_prompt` are set, text is
    waited on first (so we know the summary appeared) and prompt is
    waited on second (so we know the command actually returned)."""
    scenario = {
        "vhs": {},
        "steps": [
            {
                "action": "command",
                "text": "long_cmd",
                "wait_for_text": "DONE",
                "wait_for_prompt": True,
            }
        ],
    }
    tape = _build_tape(scenario, tmp_path)
    waits = [(i, line) for i, line in enumerate(tape) if line.startswith("Wait+Screen")]
    assert len(waits) == 2, f"Expected exactly 2 waits, got {len(waits)} in:\n{chr(10).join(tape)}"
    assert "DONE" in waits[0][1], "first wait should be the wait_for_text"
    assert "$" in waits[1][1] and "DONE" not in waits[1][1], (
        "second wait should be the prompt regex, not the text"
    )


def test_vhs_tape_standalone_wait_for_prompt_with_string(tmp_path):
    scenario = {
        "vhs": {},
        "steps": [{"action": "wait_for_prompt", "prompt": "❯"}],
    }
    tape = _build_tape(scenario, tmp_path)
    wait_lines = [line for line in tape if line.startswith("Wait+Screen")]
    assert wait_lines
    assert "❯" in wait_lines[0]


def test_vhs_tape_standalone_wait_for_prompt_with_true_uses_default(tmp_path):
    scenario = {
        "vhs": {},
        "steps": [{"action": "wait_for_prompt", "prompt": True}],
    }
    tape = _build_tape(scenario, tmp_path)
    wait_lines = [line for line in tape if line.startswith("Wait+Screen")]
    assert wait_lines
    assert "$" in wait_lines[0]


def test_vhs_tape_command_without_wait_for_prompt_unchanged(tmp_path):
    """Regression: a scenario that uses only wait_for_text and never
    mentions wait_for_prompt must produce exactly one Wait+Screen line —
    the new field is strictly additive."""
    scenario = {
        "vhs": {},
        "steps": [
            {
                "action": "command",
                "text": "echo hi",
                "wait_for_text": "hi",
            }
        ],
    }
    tape = _build_tape(scenario, tmp_path)
    wait_lines = [line for line in tape if line.startswith("Wait+Screen")]
    assert len(wait_lines) == 1
    assert "hi" in wait_lines[0]


def test_vhs_tape_standalone_wait_for_prompt_action_requires_prompt(tmp_path):
    """`{"action":"wait_for_prompt"}` with no `prompt` field is a
    malformed step — surface that loudly, don't silently no-op."""
    scenario = {
        "vhs": {},
        "steps": [{"action": "wait_for_prompt"}],
    }
    with pytest.raises(ValueError, match="prompt"):
        _build_tape(scenario, tmp_path)
