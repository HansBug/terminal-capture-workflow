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
    ],
)
def test_resolve_wait_prompt_pattern_accepts_bool_string_and_none(value, expected):
    assert resolve_wait_prompt_pattern(value) == expected


@pytest.mark.parametrize("bad", [42, 3.14, ["a", "b"], {"a": 1}])
def test_resolve_wait_prompt_pattern_rejects_other_types(bad):
    with pytest.raises(ValueError, match="wait_for_prompt"):
        resolve_wait_prompt_pattern(bad)


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n", "   \t  \n"])
def test_resolve_wait_prompt_pattern_rejects_blank_strings(blank):
    """Blank-only strings are almost certainly typos (deleted-too-much,
    accidental trailing space) and never a useful regex. Reject loudly
    rather than silently no-op — keeps the strict-type policy from
    cracking on whitespace."""
    with pytest.raises(ValueError, match="NON-EMPTY"):
        resolve_wait_prompt_pattern(blank)


# --- regex correctness ---

@pytest.mark.parametrize(
    "prompt_line",
    [
        "user@host:~$ ",
        "user@host:~# ",
        "demo% ",
        "❯ ",
        "▶ ",
        "> ",  # VHS's default Ubuntu theme renders bash PS1 as `> `
        "(venv) project$ ",
        "user@host:~$",  # no trailing space
        "demo$",
    ],
)
def test_default_regex_matches_common_prompts(prompt_line):
    # Pass re.MULTILINE explicitly — see the comment on
    # DEFAULT_PROMPT_REGEX for why the multiline flag lives at the
    # callsite, not in the pattern (JavaScript doesn't accept `(?m)`).
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


@pytest.mark.parametrize(
    "ps2_or_heredoc_line",
    [
        "> ",  # bare PS2 prompt (multi-line bash command continuation)
        "for i in 1 2 3; do\n> ",  # PS2 mid-flow
        "cat <<EOF\n> ",  # heredoc body line
        "> quoted",  # markdown quote starter — no `\s*$` anchor here
    ],
)
def test_default_regex_known_false_positive_on_ps2_and_heredoc(ps2_or_heredoc_line):
    """Documented limitation: when a capture leaves bash in PS2
    (multi-line command continuation, heredoc body), the rendered `> `
    matches the default prompt regex too — the wait fires *during* the
    continuation, not after the outer command returns. Scenarios that
    legitimately drive multi-line bash flow must pass an explicit
    `wait_for_prompt: "<regex>"` (omitting `>` from the character
    class) to avoid this. Pin the failure mode so a future "fix" that
    breaks this expectation surfaces the trade-off explicitly.
    """
    # Lines that contain `> ` will match — the regex CAN'T distinguish
    # PS1 from PS2 from rendered text alone.
    if re.search(r"[\$#%▶❯>]\s*$", ps2_or_heredoc_line, re.MULTILINE):
        assert re.search(DEFAULT_PROMPT_REGEX, ps2_or_heredoc_line, re.MULTILINE), (
            "The PS2 known-limitation case is expected to match; if it "
            "stopped matching, the default regex changed (probably for "
            "the better) — update this test and the docstring."
        )


def _decode_js_double_quoted_literal(literal: str) -> str:
    """Decode the common JS double-quoted string escape sequences we
    might see in renderer constants: ``\\\\`` → ``\\``, ``\\"`` → ``"``,
    ``\\n`` / ``\\t`` / ``\\r``. Other ``\\X`` falls back to the second
    character (matches JS semantics for unrecognized escapes). Walks
    the string char-by-char rather than using Python's
    ``unicode_escape`` codec, because that codec treats the input as
    latin-1 and mangles multi-byte UTF-8 like ``▶`` and ``❯``.
    """
    mapping = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "r": "\r"}
    out: list[str] = []
    index = 0
    while index < len(literal):
        char = literal[index]
        if char == "\\" and index + 1 < len(literal):
            nxt = literal[index + 1]
            out.append(mapping.get(nxt, nxt))
            index += 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def test_default_prompt_regex_matches_between_python_and_js():
    """Mechanized cross-renderer symmetry: the runtime regex string for
    DEFAULT_PROMPT_REGEX must be byte-identical in
    ``scripts/terminal_capture.py`` and ``scripts/render_ttyd_scenario.js``.

    Python uses a raw string (``r"(?m)..."``) and JS uses a normal
    string with backslash escapes (``"(?m)[\\\\$...]\\\\s*$"``); the
    source-level literals look different but at runtime they must encode
    the same regex. Parsing both files and comparing the decoded
    strings catches silent drift before it becomes a misrender.
    """
    js_path = Path(__file__).resolve().parents[1] / "scripts" / "render_ttyd_scenario.js"
    js_text = js_path.read_text(encoding="utf-8")
    match = re.search(
        r'const DEFAULT_PROMPT_REGEX = "((?:[^"\\]|\\.)*)";', js_text
    )
    assert match is not None, (
        "Could not locate `const DEFAULT_PROMPT_REGEX = \"...\";` in "
        "scripts/render_ttyd_scenario.js — did the declaration form change?"
    )
    js_runtime = _decode_js_double_quoted_literal(match.group(1))
    assert js_runtime == DEFAULT_PROMPT_REGEX, (
        f"Cross-language drift: Python DEFAULT_PROMPT_REGEX={DEFAULT_PROMPT_REGEX!r}, "
        f"JS runtime form={js_runtime!r}. "
        "Update both files at once."
    )


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
