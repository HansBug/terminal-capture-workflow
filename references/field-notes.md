# Field Notes

Use this reference for real-world lessons learned while rendering terminal assets under nontrivial constraints.

> The three most recurrent pitfalls (viewport-bounded waits, motion final-hold too short, WebM rejected by GitHub) are surfaced directly in `SKILL.md` under **Common Pitfalls** so first-time scenarios stop tripping on them. The full original notes — including the corner cases below — still live here.

The examples below are intentionally sanitized. Hostnames, usernames, repository names, branch names, and project-specific identifiers have been generalized so the patterns stay reusable.

## When To Split One Flow Into Multiple Videos

If the user asks for "one video per command", do not force a long combined scenario.

In practice, separate scenarios are more reliable when:

- each command has a different success condition
- some commands are `SAT` and others are `UNSAT`
- one command prints a long witness table while another stops at a short summary
- you need separate GIF/MP4/WebM outputs for each command

Sanitized example:

```json
{
  "name": "tool-validate-a-b",
  "steps": [
    {
      "action": "command",
      "text": "python -m tool validate -i tmp/model.xml --left-machine-alias Machine_region2 --left-state H.L --right-machine-alias Machine_region3 --right-state X",
      "clear_before": true,
      "wrap_at_columns": 150,
      "prompt_columns": 17,
      "typed_shot": "01-typed",
      "wait_for_text": "first coexistence: tau__Machine__region3__s20__1 = 67",
      "timeout_ms": 30000
    },
    { "action": "sleep", "ms": 1800 },
    { "action": "screenshot", "name": "02-result" }
  ]
}
```

## Prefer Stable Wait Targets Over Final-Frame Guesses

How `wait_for_text` resolves a pattern differs between the two engines:

- **ttyd** reads the full xterm.js scrollback buffer (default 5000 lines, configurable via `ttyd.scrollback`), so a pattern can match even after it has scrolled out of the visible viewport.
- **VHS** uses `Wait+Screen /pattern/`, which only matches what is currently on screen. A line that has scrolled past the bottom is gone for VHS.

For **VHS scenarios**, the original advice still applies — wait on text that is still visible when the command settles. The most common failure mode is waiting for a string that only appears near the end of a long table and gets pushed out before VHS's pattern check runs.

Better targets for VHS:

- summary lines such as `status: SAT`
- `first coexistence: ...`
- short `reason: ...` lines for `UNSAT`
- headings that appear before long tables start scrolling
- the prompt itself returning — prefer `"wait_for_prompt": true` (matches the shared default prompt regex on both engines) over hand-rolled regexes. Combine with `|| true` so non-zero exits still return to the prompt:

  ```json
  {
    "action": "command",
    "text": "long_command || true",
    "wait_for_text": "summary line",
    "wait_for_prompt": true,
    "timeout_ms": 30000
  }
  ```

  The pair "wait on summary, then wait on prompt" is the recommended idiom — `wait_for_text` proves the relevant output appeared, `wait_for_prompt` proves the command actually returned.

Avoid waiting on (in VHS):

- the final line of a long table
- a row that only becomes visible after the terminal scrolls
- highly formatted trailing output that may be cropped or paged differently between engines

For **ttyd scenarios**, this constraint is relaxed: waiting on any line that appears anywhere in the run — including a string that briefly flashed by during a large dump — is reliable as long as it falls within `ttyd.scrollback`. If a single capture genuinely needs more than the default 5000 lines, raise `ttyd.scrollback` rather than working around it with brittle viewport assumptions.

Sanitized VHS example:

Bad:

```json
{
  "wait_for_text": "\\| 118 \\| s28\\s+\\| emit\\(Sig7\\)"
}
```

Better:

```json
{
  "wait_for_text": "first coexistence: t20 = 66"
}
```

Sanitized ttyd example — previously infeasible because the marker scrolls out, now reliable because the wait reads the full xterm.js scrollback buffer:

```json
{
  "action": "command",
  "text": "for i in $(seq 1 200); do echo line $i; done; echo done",
  "wait_for_text": "line 42",
  "timeout_ms": 15000
}
```

### Canonical reproducer: ttyd scrollback wait

Use this when you suspect the buffer-based path has regressed (e.g. after a ttyd or xterm.js upgrade). The scenario forces an "early marker, then 100 padding lines past the viewport, then a final marker" shape so the wait must reach scrollback to succeed.

```json
{
  "name": "ttyd-scrollback-bug",
  "cwd": "/tmp",
  "shell": ["bash", "--noprofile", "--norc", "-i"],
  "ttyd": {
    "fontSize": 14,
    "viewport": {"width": 900, "height": 380, "deviceScaleFactor": 2}
  },
  "steps": [
    {
      "action": "command",
      "text": "echo SCROLLBACK_EARLY_4f3a7c; for i in $(seq 1 100); do echo padding line $i; done; echo CMD_FINISHED",
      "clear_before": true,
      "wait_for_text": "CMD_FINISHED",
      "timeout_ms": 15000
    },
    {
      "action": "wait_for_text",
      "pattern": "SCROLLBACK_EARLY_4f3a7c",
      "timeout_ms": 5000
    },
    {"action": "screenshot", "name": "verified"}
  ]
}
```

Run it with `python3 scripts/terminal_capture.py render ttyd <path-to-scenario>`. On a healthy install the second `wait_for_text` succeeds quickly and produces `verified.png`. On a regressed install — `window.term` renamed, scrollback option ignored, or the buffer API misused — the renderer now fails fast with an explicit error pointing back to this section, not a generic Playwright timeout.

## Long Command Typing Needs Column-Aware Wrapping

Natural terminal wrapping is not reliable enough for capture automation.

Real failure pattern:

- the visual terminal width is `150` columns
- the prompt consumes part of that width
- a long command reaches the visual edge
- the shell and renderer disagree about the line break
- the typed command appears to overwrite the current line

Use `wrap_at_columns` together with prompt-width hints.

Sanitized example:

```json
{
  "action": "command",
  "text": "python -m tool validate -i tmp/model.xml --left-machine-alias Machine_region2 --left-state H.M --right-machine-alias Machine_region3 --right-state S",
  "clear_before": true,
  "wrap_at_columns": 150,
  "prompt_columns": 17,
  "continuation_prompt_columns": 0,
  "wrap_indent": 2
}
```

This produces shell-equivalent wrapped input such as:

```bash
python -m tool validate -i tmp/model.xml --left-machine-alias Machine_region2 --left-state H.M \
  --right-machine-alias Machine_region3 --right-state S
```

## VHS Escape Rules Matter For Continuation Backslashes

When implementing wrapped command input, make sure the renderer types a single trailing backslash.

A real bug class is:

- the wrapper emits `\\` for display safety
- VHS receives two literal backslashes instead of one continuation marker
- the shell treats `\` as an argument, not a line continuation
- the next line runs as a separate command and fails

Practical rule:

- for VHS typed command text, escape quotes and control characters
- do not double-escape backslashes that are meant to be typed literally

### Empirical probe: VHS Type string semantics

When changing how the renderer escapes characters inside VHS `Type "..."` strings, verify directly against the local `vhs` binary instead of guessing at parser behavior. The procedure below captures what VHS actually types by writing it through a shell heredoc and inspecting the resulting file with `cat -A` — no GIF reading required. This is the probe that confirmed PR #15's decision to leave `escape_vhs_text` alone.

```bash
probe_typed() {
  local label="$1" type_arg="$2"
  rm -f /tmp/captured.txt
  cat > /tmp/vhs-typed-probe.tape <<EOF
Output "/tmp/typed-probe.gif"
Set Shell "bash"
Set Width 800
Set Height 200
Sleep 200ms
Type "cat > /tmp/captured.txt <<'EOF_INNER'"
Enter
Type ${type_arg}
Enter
Type "EOF_INNER"
Enter
Sleep 400ms
EOF
  vhs /tmp/vhs-typed-probe.tape >/dev/null 2>&1
  printf "  %-30s typed: %s\n" "$label" "$(cat -A /tmp/captured.txt | head -1)"
}

probe_typed "literal text"        '"hello"'
probe_typed "\\ in middle"        '"a\b"'
probe_typed "\\ before close \""  '"trail\"'
probe_typed "\\\\ in middle"      '"x\\y"'
probe_typed "\\\\ before close"   '"tail\\"'
```

Findings (vhs from the official Charm apt repo, May 2026, verified on Ubuntu):

- A bare `\` followed by a non-reserved char is typed literally (`"a\b"` types `a\b`).
- A bare `\` immediately before the closing `"` is typed literally (`"trail\"` types `trail\`); it does NOT collide with the close-quote.
- A `\\` sequence is typed as **two** literal backslashes (`"tail\\"` types `tail\\`). VHS does NOT unescape `\\` back to a single `\`.

Implication for `escape_vhs_text`: doubling literal backslashes on the way in would cause the typed terminal to receive two `\` chars where the user wrote one, breaking shell parsing. This is exactly what the "Practical rule" above already warns against, and what issue #3's withdrawn fix attempted. If a future change appears to require backslash doubling, rerun this probe before committing — and if VHS's behavior really did change, update the probe outputs here in the same PR.

## ttyd And VHS Need Different Kinds Of Setup

For screenshots, ttyd can start directly with a custom shell or rcfile.

For VHS, it is often cleaner to:

- hide setup
- activate the virtual environment
- set prompt variables
- run `stty rows ... cols ...`
- clear the screen
- reveal only after the terminal is ready

Sanitized example:

```json
[
  { "action": "hide" },
  {
    "action": "command",
    "text": "source venv/bin/activate && unset PROMPT_COMMAND && export COLUMNS=150 LINES=35 PS1='(venv) repo$ ' && stty rows 35 cols 150 && clear",
    "wait_for_text": "\\(venv\\) repo\\$",
    "timeout_ms": 10000
  },
  { "action": "show" }
]
```

## Separate The Capture Concern From The Shell Concern

If a command is long and fragile, first decide whether the problem is:

- display length only
- shell parsing fragility
- long output scrolling
- timing instability

Use the least invasive fix:

- display-length only: `wrap_at_columns`
- shell-fragile pipeline: helper script
- long output: pager such as `less -R`
- unstable end state: wait on earlier visible summary text, then `sleep` before screenshot

## Practical Timing Heuristics

Useful starting points from real runs:

- `400ms` after a prompt appears when the prompt itself needs to be seen
- `800ms` after a short summary completes
- `1200-1800ms` before a screenshot of a long summary or a state-query result
- `30000ms` timeout for heavier validation commands with solver work

If a command is deterministic but slow, prefer a longer `wait_for_text` timeout over stacking arbitrary sleeps.

## Recommended Review Checklist For Customer-Facing Assets

After rendering:

1. Check the typed screenshot for long-command wrapping correctness.
2. Check the result screenshot for the exact visible state the user requested.
3. Probe the MP4 or WebM duration before choosing review timestamps.
4. If the ending state must be read by a human, keep `endHoldSeconds >= 3`.
5. If one command looks materially different from the others, split it into a dedicated scenario instead of forcing consistency for its own sake.
