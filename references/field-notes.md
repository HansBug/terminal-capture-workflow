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

The most common failure mode in long outputs is waiting for a string that only appears near the end of a long table.

Better targets:

- summary lines such as `status: SAT`
- `first coexistence: ...`
- short `reason: ...` lines for `UNSAT`
- headings that appear before long tables start scrolling

Avoid waiting on:

- the final line of a long table
- a row that only becomes visible after the terminal scrolls
- highly formatted trailing output that may be cropped or paged differently between engines

Sanitized example:

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
