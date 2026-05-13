---
name: terminal-capture-workflow
description: Create staged terminal screenshots, PNG stills, GIFs, MP4/WebM demos, and visual QA artifacts without using OS-level desktop input injection. Use when the agent needs terminal capture assets for guides, operation manuals, reports, slide decks, changelogs, or homepage demos, especially for interactive prompts, multi-step CLI flows, long paged output, ttyd/Playwright rendering, VHS rendering, frame extraction, or visual inspection of generated terminal media.
---

# Terminal Capture Workflow

## Overview

Produce terminal assets through two non-intrusive engines:

- `ttyd + Playwright` for documentation-oriented screenshots
- `VHS` for `gif`, `mp4`, `webm`, and staged stills, with a default final hold on motion outputs so viewers can read the ending state
- A shared interaction model for arbitrary text input, multiline paste, key presses, modifier chords, and multi-step terminal/TUI flows

Always start by resolving the installed skill root, then run environment detection, choose the engine, author a scenario, render, visually inspect, and iterate.

## Skill Root

Before running any command from this skill, resolve the installed skill directory. Try these paths in order:

- `~/.codex/skills/terminal-capture-workflow` (Codex)
- `~/.claude/skills/terminal-capture-workflow` (Claude Code)

Either may be a real directory or a symlink to a local clone of the repo. If neither exists, locate the repo copy that contains this `SKILL.md`. Do not assume the user workspace also contains `scripts/terminal_capture.py`; many workspaces only contain scenario files and helper demo scripts.

## Scenario Quick Reference

Tunable fields, grouped by scope. Anything not listed here is in `references/scenario-patterns.md`.

| Scope | Field | Default | When to adjust |
|---|---|---|---|
| top | `cwd` | scenario directory | Cross-directory resource references |
| top | `shell` | `["bash", "--noprofile", "--norc", "-i"]` | Need a different shell |
| top | `requires` | `[]` | Add VHS `Require` lines |
| ttyd | `viewport.width` | 1400 | Wider terminal for long lines / panels |
| ttyd | `viewport.height` | 560 | Taller terminal for paged output |
| ttyd | `viewport.deviceScaleFactor` | 2 | PNG too blurry or too large |
| ttyd | `fontSize` | 20 | Readability |
| ttyd | `typingDelayMs` | 20 | Faster / slower typing animation |
| ttyd | `cursorBlink` | true | Disable for cleaner stills |
| ttyd | `theme` | xterm default | Custom color theme |
| ttyd | `rendererType` | `"dom"` | Switch to `canvas` / `webgl` only if DOM rendering misbehaves |
| ttyd | `scrollback` | 5000 (raised from xterm.js's built-in 1000) | Raise for very long output runs; `wait_for_text` matches the entire scrollback buffer |
| vhs | `width` | 1280 | Match ttyd viewport |
| vhs | `height` | 760 | Match ttyd viewport |
| vhs | `fontSize` | 22 | Readability |
| vhs | `padding` | 24 | Outer canvas padding |
| vhs | `windowBar` | `"Colorful"` | Window chrome style |
| vhs | `borderRadius` | 10 | Rounded corners |
| vhs | `theme` | `"Ubuntu"` | Different VHS theme |
| vhs | `typingSpeed` | `"35ms"` | Faster / slower typing animation |
| vhs | `framerate` | 30 | Smoother or smaller motion |
| vhs | `playbackSpeed` | unset | Final playback speed multiplier |
| vhs | `outputs` | `["mp4"]` | Need gif / webm or multiple formats |
| vhs | `endHoldSeconds` | 2 (motion outputs only; PNG-only flows hold 0) | Motion final frame needs more reading time |
| vhs | `endHoldMs` | unset | Same as `endHoldSeconds` in ms |
| vhs | `screenshotSettleMs` | 120 | Delay after a `Screenshot` step |
| vhs | `waitTimeout` | unset | Override default 10s wait timeout |
| screenshots | `autocrop` | true | Set false to keep original margins |
| screenshots | `padding` | 18 | Margin around autocrop bounds |
| step `command` | `wrap_at_columns` | unset | Long command overruns terminal width |
| step `command` | `prompt_columns` | 0 | `wrap_at_columns` enabled and PS1 is wide |
| step `command` | `continuation_prompt_columns` | 0 | Wrapped continuation lines also have a prompt |
| step `command` | `wrap_indent` | 2 | Continuation-line indent |
| step `command` | `clear_before` | false | `Ctrl+L` before typing |
| step `command` | `timeout_ms` | 10000 | Slow command (solver / network) |
| step `command` | `result_delay_ms` | 900 | Only when no `wait_for_text` and no `wait_for_prompt` |
| step `command` | `typed_shot` / `result_shot` | unset | Auto-capture at typed / result moments |
| step `command` / action `wait_for_prompt` | `wait_for_prompt` / `prompt` | unset | `true` waits on the default prompt regex (`[\$#%▶❯>]\s*$`); a string is used verbatim as a regex |
| step | `pattern_by_engine` / `wait_for_text_by_engine` | unset | Different prompts per engine |

## Engine Decision Tree

```
What do you want to produce?
├── One or a few static PNGs                   → prefer ttyd
│   ├── Multi-modifier special-key chords      → must use ttyd
│   └── ttyd environment blocked               → fall back to VHS `Screenshot`
├── GIF / MP4 / WebM motion                    → must use VHS
│   ├── Also need static PNGs                  → engine: `all`
│   └── Target a GitHub PR or issue            → outputs `["gif", "mp4"]` only (see Common Pitfalls)
└── Recording an agent CLI (codex / claude)    → VHS, with a wider viewport and longer endHoldSeconds (see paragraph below)
```

When the target is an agent CLI such as `codex` or `claude`, the UI includes tool-call panels and streaming spinners. In that case raise both `vhs.width` (or `ttyd.viewport.width`) to at least `1400` so panels do not break, and `vhs.endHoldSeconds` to `4` or more so viewers can read the final answer. A dedicated `references/recording-agent-cli.md` plus starter scenarios are tracked separately.

## Workflow

1. Resolve `SKILL_ROOT`, then run `python "$SKILL_ROOT/scripts/terminal_capture.py" check`.
2. Read the capability summary before planning the render.
3. If the request is anything more complex than a toy one-command demo, read `references/field-notes.md` before designing the scenario. Treat this as the default for customer-facing captures, split-per-command deliverables, long commands, long solver-like output, or any task that already feels slightly fragile.
4. If the requested output is blocked, stop and tell the user which dependencies are missing. Reuse the install commands printed by the check command instead of improvising package names.
5. Choose the engine:
   - Prefer `ttyd` for screenshots used in docs, guides, reports, or issue comments.
   - Prefer `vhs` for `gif`, `mp4`, `webm`, and teaser-style captures.
   - Prefer `all` when the user wants both stills and motion assets from the same flow.
   - If `ttyd` is blocked but `vhs` is ready, use VHS `Screenshot` steps as a fallback for still images.
6. If this is a brand-new scenario inside a fresh project (no existing `scenarios/` directory yet), scaffold the three-piece layout with `python "$SKILL_ROOT/scripts/terminal_capture.py" init <name> [--engine ttyd|vhs|all] [--with-setup]`. The command creates `scenarios/<name>.json` (a minimal runnable template), `scripts/render_<name>.sh` (a SKILL_ROOT-resolving wrapper that runs the right engine), and optionally `scripts/setup_<name>.sh` for repo-specific prep. See `references/project-layout.md` for the why and the recommended commit-to-repo workflow.
7. Create or update a scenario JSON in the user workspace. Set the requested window size in:
   - `ttyd.viewport.width`
   - `ttyd.viewport.height`
   - `vhs.width`
   - `vhs.height`
   - `vhs.endHoldSeconds` when the user wants a specific frozen ending length for GIF or video. If it is omitted, motion outputs default to a short final hold.
8. For large output, do not force everything into one frame. Route the command through `less -R` or another pager and capture specific pages with `PageDown`.
9. For fragile commands, wrap them in a helper shell script inside the user workspace instead of keeping a long pipeline inline in the scenario.
10. Use `input` steps when the user needs more than a single command or reply. Compose `text`, `paste`, `press`, and `sleep` events instead of faking the flow with a giant inline shell command.
11. When one single shell command is visually too long for the requested terminal width, prefer `command` with `wrap_at_columns` plus prompt-width hints instead of relying on the terminal emulator's natural wrap. This keeps typed long commands readable and avoids overwrite artifacts.
12. Prefer `ttyd + Playwright` when the user needs exotic key chords that VHS may reject, especially multi-modifier special-key combinations. Use VHS when the user primarily needs motion output.
13. For `tmux`, `vim`/`vi`, `less`, `fzf`, and other TUI flows, plan around visible state changes and explicit waits, not fixed timing guesses.
14. Render with `python "$SKILL_ROOT/scripts/terminal_capture.py" render <engine> <scenario-path> [--output-root <dir>]`.
15. If the user asked for visual verification, or the asset is customer-facing, inspect the final stills directly. For video or GIF, first run `python "$SKILL_ROOT/scripts/terminal_capture.py" probe-media <media>` to get the duration and suggested timestamps, then extract representative frames with `python "$SKILL_ROOT/scripts/terminal_capture.py" extract-frames <media> --times <comma-separated-seconds>`.
16. If the visual review fails, adjust the scenario and rerender. Do not stop at “the command succeeded” when the artifact itself is the deliverable.
17. If a prompt or confirmation beat is too brief in motion output, add a short `sleep` step before the reply so the state is legible in GIF or video, then rerender.

## Common Pitfalls

Three failure modes recur across real downstream usage. They are also documented in `references/field-notes.md`; they appear here because new scenarios still hit them on the first attempt.

### 1. VHS `wait_for_text` is viewport-bounded

VHS `Wait+Screen /pattern/` only matches text currently visible on screen. When command output exceeds one screen, the target line scrolls out of view and VHS's wait will time out — even though the pattern clearly appeared. ttyd no longer has this constraint (it reads the full xterm.js scrollback buffer; see `ttyd.scrollback` in the quick reference for the default), but **VHS does**.

Fix (VHS): wait for the prompt to return, not for an intermediate line. Append `|| true` so non-zero exits still return to the prompt. Prefer `wait_for_prompt: true` over hand-rolled regexes — it uses the shared default prompt regex (`[\$#%▶❯>]\s*$`), works on both engines, and combines with `wait_for_text` so the "wait on summary AND wait on prompt return" idiom is one extra field rather than a custom regex.

```json
{
  "action": "command",
  "text": "long_command_with_many_lines || true",
  "wait_for_text": "summary line",
  "wait_for_prompt": true,
  "timeout_ms": 30000
}
```

For solver-like commands, also raise `timeout_ms`. Avoid waiting on rows that only appear deep inside a long table.

### 2. Motion output ends too fast for viewers to read

`vhs.endHoldSeconds` defaults to 2. For looping demo GIFs this is usually fine; for hero clips, tutorial videos, or PR review media, viewers cannot read the final state in time and the asset has to be re-rendered.

Fix: raise `endHoldSeconds` to match the asset's purpose.

```json
{ "vhs": { "endHoldSeconds": 4 } }
```

Empirical values: tutorial / hero / PR review → 3–5s; pure loop GIF → 2s (default); summary-screen demo → 4–6s.

### 3. GitHub's media upload endpoint rejects WebM

GitHub's media upload endpoint (the path that backs PR / issue drag-and-drop attachments, as well as the `gh-image` CLI extension) rejects WebM with HTTP 422 `content_type is not included in the list`. Anything posted directly into a PR or issue body must be GIF / PNG / MP4.

Fix: for PR delivery render only `["gif", "mp4"]` — GIF auto-loops in markdown, MP4 gives a native `<video>` control with pause and scrub.

```json
{ "vhs": { "outputs": ["gif", "mp4"] } }
```

WebM remains useful as a high-quality local archive; just do not paste it into a GitHub thread.

## Scenario Rules

- Keep `cwd` aligned with the target project or scratch directory.
- Keep the scenario in the user workspace, but keep the renderer commands anchored to `SKILL_ROOT`.
- Use `pattern_by_engine` or `wait_for_text_by_engine` when shell prompts differ between ttyd and VHS.
- Use `type`, `paste`, `press`, and `input` steps for real interactions instead of embedding everything in one shell command.
- For long `command` steps, use `wrap_at_columns`, and when needed also set `prompt_columns`, `continuation_prompt_columns`, and `wrap_indent` so wrapped shell input reflects the real terminal width instead of visually overwriting one line.
- Key names are normalized case-insensitively. Chords like `ctrl+b`, `ctrl+shift+*`, `ctrl+[`, `alt+enter`, and `shift+tab` can be represented directly in scenarios.
- Use `typed_shot`, `result_shot`, and explicit `screenshot` steps when the user cares about exact stages.
- Use `hide` and `show` to suppress setup in teaser videos.
- VHS `paste` is rendered as fast exact typing and does not depend on the system clipboard.
- Motion outputs automatically hold on the final frame for 2 seconds unless the scenario sets `vhs.endHoldSeconds` or `vhs.endHoldMs`.
- Use `screenshots.autocrop` for tighter documentation images. Disable it only when the user explicitly wants full-frame output.

## Visual Review

Inspect the generated media against the user’s actual concern, not just general aesthetics. Focus on:

- Whether the correct stage was captured
- Whether prompts or confirmations are visible before input
- Whether syntax highlighting and ANSI colors survived
- Whether the requested page of long output is the one shown
- Whether the chosen window size feels intentional
- Whether unwanted setup is hidden in teaser media
- Whether there is excessive whitespace that harms readability
- Whether frame-extraction timestamps are inside the actual media duration
- Whether the final state lingers long enough for a human viewer to read it

## References

- Read `references/field-notes.md` first whenever the task looks real, slightly brittle, or user-facing.
- Read `references/environment-and-install.md` when dependencies are missing or the user asks what to install.
- Read `references/scenario-patterns.md` when building or editing a scenario for interactive flows, long output, teaser captures, or engine-specific wait rules.
- Read `references/project-layout.md` when the scenario needs to be committed to a downstream repo and regenerated on demand by teammates or CI.
