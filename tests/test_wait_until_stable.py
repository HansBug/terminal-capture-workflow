"""Tests for the ``wait_until_stable`` step field.

Tracks issue #7. The field tells the renderer to wait for an additional
quiet window after the existing ``wait_for_text`` / ``wait_for_prompt``
fires, so streaming-token output (codex, claude, ollama) and spinner-
heavy commands (`npm install`, `pip install`) settle before the
screenshot is taken — instead of relying on hand-picked ``Sleep`` values.

Engine semantics:

- **ttyd**: real buffer polling. After the existing wait fires, sample
  the xterm.js buffer every 150 ms; reset the stable-window timer on
  any change. Tested via end-to-end (this file focuses on the Python
  tape-building half).
- **VHS**: degraded path — no API to poll the rendered tape. Emit a
  literal ``Sleep <ms>ms`` after the existing ``Wait+Screen`` so the
  stable timer at least starts only after the pattern appears. Strictly
  worse than ttyd, documented in scenario-patterns.md and SKILL.md.
"""

from pathlib import Path

import pytest

from terminal_capture import (
    build_vhs_tape,
    resolve_wait_until_stable_ms,
)


# --- resolve_wait_until_stable_ms ---

def test_resolve_returns_ms_value_for_valid_dict():
    assert resolve_wait_until_stable_ms({"ms": 800}) == 800
    assert resolve_wait_until_stable_ms({"ms": 0}) == 0
    assert resolve_wait_until_stable_ms({"ms": 1500, "pattern": "ignored"}) == 1500


def test_resolve_returns_none_for_unset():
    assert resolve_wait_until_stable_ms(None) is None


@pytest.mark.parametrize(
    "bad",
    [
        42,
        "800",
        ["ms", 800],
        {"seconds": 0.8},  # missing required `ms` key
        {"ms": "fast"},  # ms must be int-compatible
        {"ms": -100},  # negative makes no sense — parse_positive_int clamps to 0,
                       # but a negative explicit value is more likely a typo than
                       # an intentional zero; reject loudly.
    ],
)
def test_resolve_rejects_invalid_shapes(bad):
    with pytest.raises(ValueError):
        resolve_wait_until_stable_ms(bad)


# --- VHS tape integration ---

def _build_tape(scenario, tmp_path):
    scenario.setdefault("name", "test")
    scenario.setdefault("cwd", str(tmp_path))
    return build_vhs_tape(scenario, out_dir=tmp_path).splitlines()


def test_vhs_tape_command_with_wait_until_stable_emits_sleep_after_wait(tmp_path):
    """A `command` step with `wait_until_stable.ms` must emit a
    ``Sleep <ms>ms`` line immediately after the existing wait — that's
    VHS's degraded "stability" implementation."""
    scenario = {
        "vhs": {},
        "steps": [
            {
                "action": "command",
                "text": "echo Done.",
                "wait_for_text": "Done\\.",
                "wait_until_stable": {"ms": 800},
            }
        ],
    }
    tape = _build_tape(scenario, tmp_path)
    wait_idx = next(
        i for i, line in enumerate(tape) if line.startswith("Wait+Screen")
    )
    # First non-empty line after the wait must be the stability sleep.
    follow_idx = next(
        i for i in range(wait_idx + 1, len(tape)) if tape[i].strip()
    )
    assert tape[follow_idx] == "Sleep 800ms", (
        f"Expected `Sleep 800ms` immediately after the wait, got "
        f"{tape[follow_idx]!r}; full tape:\n{chr(10).join(tape)}"
    )


def test_vhs_tape_standalone_wait_for_text_with_wait_until_stable(tmp_path):
    """The same stability sleep applies when `wait_for_text` is used as
    a standalone action, not just inside a `command` step."""
    scenario = {
        "vhs": {},
        "steps": [
            {
                "action": "wait_for_text",
                "pattern": "Done\\.",
                "wait_until_stable": {"ms": 500},
            },
            {"action": "screenshot", "name": "after"},
        ],
    }
    tape = _build_tape(scenario, tmp_path)
    wait_idx = next(
        i for i, line in enumerate(tape) if line.startswith("Wait+Screen")
    )
    follow = tape[wait_idx + 1]
    assert follow == "Sleep 500ms", f"Expected `Sleep 500ms`, got {follow!r}"


def test_vhs_tape_command_stable_sleep_lands_after_both_waits(tmp_path):
    """When the command sets `wait_for_text` + `wait_for_prompt` +
    `wait_until_stable`, the stability sleep must come **after both**
    waits — the pattern-and-prompt anchors fire first, then we let the
    buffer settle."""
    scenario = {
        "vhs": {},
        "steps": [
            {
                "action": "command",
                "text": "codex exec query",
                "wait_for_text": "answer",
                "wait_for_prompt": True,
                "wait_until_stable": {"ms": 1200},
            }
        ],
    }
    tape = _build_tape(scenario, tmp_path)
    waits = [i for i, line in enumerate(tape) if line.startswith("Wait+Screen")]
    sleep_idx = next(
        i
        for i, line in enumerate(tape)
        if line.strip() == "Sleep 1200ms"
    )
    assert len(waits) == 2, f"expected 2 waits (text + prompt), got {len(waits)}"
    assert sleep_idx > waits[-1], (
        "Stability `Sleep 1200ms` must come after the prompt wait, not "
        "between the two wait lines."
    )


def test_vhs_tape_without_wait_until_stable_unchanged(tmp_path):
    """Regression: scenarios that do not set wait_until_stable must
    produce no extra Sleep — keeps the field strictly additive."""
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
    # The only `Sleep` lines in this minimal tape are the boilerplate
    # screenshot-settle / clear-before / end-hold sleeps. None of them
    # is `Sleep <user>ms` for our stable window.
    user_stable_sleeps = [
        line
        for line in tape
        if line == "Sleep 800ms" or line == "Sleep 1200ms" or line == "Sleep 500ms"
    ]
    assert not user_stable_sleeps, (
        f"Did not expect any user stability sleep, but got: {user_stable_sleeps}"
    )


def test_vhs_tape_zero_ms_stable_window_still_renders(tmp_path):
    """`{"ms": 0}` is a valid (if pointless) request — it should emit
    `Sleep 0ms` (or the equivalent `Sleep 0s` that ``format_duration``
    produces for integer-second values), not raise or silently drop
    the field. This catches a common typo (someone setting 0 by
    accident) that we would otherwise silently no-op on."""
    scenario = {
        "vhs": {},
        "steps": [
            {
                "action": "wait_for_text",
                "pattern": "Done\\.",
                "wait_until_stable": {"ms": 0},
            }
        ],
    }
    tape = _build_tape(scenario, tmp_path)
    # `format_duration(0)` collapses to "0s", but the line must still
    # appear in the position immediately after the Wait+Screen.
    wait_idx = next(
        i for i, line in enumerate(tape) if line.startswith("Wait+Screen")
    )
    follow = tape[wait_idx + 1]
    assert follow in ("Sleep 0ms", "Sleep 0s"), (
        f"Expected explicit zero-duration sleep right after the wait, got "
        f"{follow!r}; full tape:\n" + "\n".join(tape)
    )
