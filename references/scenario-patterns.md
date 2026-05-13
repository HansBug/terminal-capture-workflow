# Scenario Patterns

Use this reference when building or editing a scenario JSON.

## Shared Structure

```json
{
  "name": "example-name",
  "cwd": "/abs/path/to/workdir",
  "shell": ["bash", "--noprofile", "--norc", "-i"],
  "requires": ["python3"],
  "ttyd": {
    "fontSize": 20,
    "typingDelayMs": 20,
    "cursorBlink": true,
    "viewport": {
      "width": 1400,
      "height": 560,
      "deviceScaleFactor": 2
    },
    "theme": {
      "background": "#300a24"
    }
  },
  "vhs": {
    "fontSize": 22,
    "width": 1280,
    "height": 760,
    "padding": 24,
    "windowBar": "Colorful",
    "borderRadius": 10,
    "theme": "Ubuntu",
    "typingSpeed": "35ms",
    "framerate": 30,
    "outputs": ["mp4", "gif"],
    "endHoldSeconds": 3
  },
  "screenshots": {
    "autocrop": true,
    "padding": 18
  },
  "steps": []
}
```

For motion outputs, `endHoldSeconds` controls how long the final frame stays on screen after the last action completes. If omitted, GIF/MP4/WebM outputs default to a 2-second final hold. Set it to `0` to disable the extra hold.

## Step Types

- `command`
  - Type a full command, optionally clear first, optionally capture the typed state, then wait for output.
  - Supports optional long-command wrapping fields:
    - `wrap_at_columns`
    - `wrap_indent`
    - `prompt_columns`
    - `continuation_prompt_columns`
- `type`
  - Type text without pressing enter yet.
- `paste`
  - Inject text quickly. Use this for multiline content, prepared answers, or large snippets.
- `press`
  - Press a key or key chord such as `Enter`, `PageDown`, `ctrl+b`, `ctrl+shift+*`, `alt+enter`, or `ctrl+[`.
- `input`
  - Compose a sequence of `text`, `paste`, `press`, and `sleep` events for richer interactions.
- `wait_for_text`
  - Wait until the rendered terminal text contains the expected pattern (regex). On ttyd this covers the entire scrollback buffer; on VHS it covers the current viewport.
- `wait_until_stable` (field on `command` and `wait_for_text`, not a standalone action)
  - After the existing wait fires, additionally hold off until the rendered terminal buffer has been **quiet for `ms` milliseconds**. Use this for streaming-token output (codex, claude, ollama) and spinner-heavy commands (`npm install`, `pip install`) where the pattern can match while the screen is still changing. Shape: `"wait_until_stable": {"ms": 800}` (any additional keys are accepted-but-ignored for forward compatibility). Engine semantics:
    - **ttyd**: real polling — samples the xterm.js buffer every 150 ms; any change resets the stable-window timer. Bounded by the step's `timeout_ms`. If the buffer never settles before the timeout, the renderer emits a stderr warning and proceeds.
    - **VHS**: degraded — the tape emits a literal `Sleep <ms>ms` immediately after the existing `Wait+Screen`. Strictly worse than polling (it cannot tell whether the buffer is actually quiet), but better than a hand-picked `Sleep` at the top of the step because the timer at least starts after the wait matches.
- `wait_for_prompt`
  - Wait until a shell prompt has returned. `"prompt": true` uses the shared default regex `[\$#%▶❯>]\s*$` (covers bash / zsh / sh `$`, root `#`, csh `%`, starship / fish `❯` / `▶`, and VHS's default Ubuntu-theme `>`). Multiline semantics are passed as a flag by the renderers (Python `re.MULTILINE`, JS `"m"`, Go regexp matches end-of-string at viewport end). `"prompt": "<regex>"` uses your own pattern. Can be combined with `wait_for_text` on a `command` step (`"wait_for_text": "summary", "wait_for_prompt": true`) for the "wait on summary AND wait on prompt return" idiom recommended in `field-notes.md`. **Known limitation:** because PS2 continuation, heredoc body, and Markdown-style `> quotes` also start with `> `, the default regex matches them too — scenarios that drive multi-line bash (`for … do …`, unclosed quotes, heredocs) should pass an explicit regex without `>` in the class, e.g. `"wait_for_prompt": "[\\$#%▶❯]\\s*$"`.
- `screenshot`
  - Capture a still at the current stage.
- `sleep`
  - Explicit wait when there is no better observable condition.
- `hide` and `show`
  - VHS-only visibility control for teaser captures.
- `raw_vhs`
  - Inject explicit VHS tape lines when you need engine-specific control.

## Generalized Input Model

Prefer the shared input model over brittle one-off shell tricks.

### Supported event kinds inside `input`

```json
{
  "action": "input",
  "events": [
    { "kind": "text", "text": "hello world" },
    { "kind": "press", "key": "Enter" },
    { "kind": "paste", "text": "line 1\nline 2" },
    { "kind": "sleep", "ms": 300 }
  ]
}
```

### Key normalization

- Modifier names are case-insensitive: `ctrl`, `Ctrl`, `CONTROL` all normalize.
- Common aliases are normalized: `esc`, `return`, `pgdn`, `left`, `right`, `space`.
- Printable-key chords such as `ctrl+*`, `ctrl+shift+*`, `ctrl+%`, `ctrl+[`, and `alt+x` work across both engines.
- VHS also accepts many single-modifier special-key chords such as `shift+tab`, `ctrl+left`, and `alt+enter`.
- Some multi-modifier special-key chords are rejected by the VHS parser itself. When the user needs those, prefer the `ttyd + Playwright` engine.

### Multiline paste

`paste` is the right default for multiline content:

```json
{
  "action": "paste",
  "text": "first line\nsecond line\nthird line"
}
```

For VHS, this is rendered as fast exact typing. It does not depend on `xclip`, `xsel`, or any desktop clipboard tool.

## Interactive Confirmation Pattern

Use when a command asks for `y/N`, a password, or another short confirmation.

```json
[
  {
    "action": "command",
    "text": "python3 scripts/confirm_demo.py",
    "clear_before": true,
    "typed_shot": "01-command-typed",
    "wait_for_text": "Apply migration now\\? \\[y/N\\]",
    "timeout_ms": 10000,
    "result_shot": "02-prompt-visible"
  },
  { "action": "sleep", "ms": 600 },
  { "action": "type", "text": "y" },
  { "action": "screenshot", "name": "03-confirmation-typed" },
  { "action": "press", "key": "Enter" },
  {
    "action": "wait_for_text",
    "pattern": "Done\\. New schema version: 2026\\.04",
    "timeout_ms": 10000
  },
  { "action": "screenshot", "name": "04-finished" }
]
```

Add a brief `sleep` before the reply when the prompt itself must be legible in a GIF or homepage demo. Still screenshots usually do not need this, but motion assets often do.

## Multi-Step Wizard Pattern

Use when the flow alternates between prompts and replies.

```json
[
  {
    "action": "command",
    "text": "python3 scripts/wizard_demo.py",
    "clear_before": true,
    "wait_for_text": "Project name:",
    "timeout_ms": 10000,
    "result_shot": "01-project-prompt"
  },
  { "action": "type", "text": "docs-homepage-demo" },
  { "action": "press", "key": "Enter" },
  { "action": "wait_for_text", "pattern": "Package manager", "timeout_ms": 10000 },
  { "action": "screenshot", "name": "02-package-manager-prompt" }
]
```

## Arbitrary Interaction Pattern

Use this for `tmux`, `vim`/`vi`, shell wizards, pagers, or anything that needs more than one reply.

```json
[
  {
    "action": "command",
    "text": "tmux -f /dev/null new-session -s demo",
    "clear_before": true,
    "wait_for_text": "demo",
    "timeout_ms": 10000
  },
  {
    "action": "input",
    "events": [
      { "kind": "text", "text": "vi -Nu NONE -n notes.txt" },
      { "kind": "press", "key": "Enter" }
    ]
  },
  { "action": "wait_for_text", "pattern": "notes\\.txt", "timeout_ms": 10000 },
  {
    "action": "input",
    "events": [
      { "kind": "press", "key": "ctrl+b" },
      { "kind": "press", "key": "%" },
      { "kind": "sleep", "ms": 250 },
      { "kind": "press", "key": "ctrl+b" },
      { "kind": "press", "key": "left" }
    ]
  }
]
```

## Long Output Pattern

Do not try to fit a long terminal transcript into one screenshot. Wrap the command in a helper script if the pipeline is awkward, then page through `less -R`.

```json
[
  {
    "action": "command",
    "text": "bash scripts/run_long_output_pager.sh",
    "clear_before": true,
    "wait_for_text": "Section 1: rollout checks",
    "timeout_ms": 10000,
    "result_shot": "01-page-1"
  },
  { "action": "press", "key": "PageDown" },
  { "action": "wait_for_text", "pattern": "Section 2: rollout checks", "timeout_ms": 10000 },
  { "action": "screenshot", "name": "02-page-2" }
]
```

## Long Command Pattern

Use this when one shell command is longer than the intended terminal width and you want the typed state to remain readable.

```json
[
  {
    "action": "command",
    "text": "python -m pyfcstm sysdesim validate -i tmp/model1_fixed_v2.xml --left-machine-alias StateMachine__Control_region2 --left-state H.L --right-machine-alias StateMachine__Control_region3 --right-state X",
    "clear_before": true,
    "wrap_at_columns": 150,
    "prompt_columns": 17,
    "continuation_prompt_columns": 0,
    "wrap_indent": 2,
    "typed_shot": "01-command-typed",
    "wait_for_text": "status: SAT",
    "timeout_ms": 30000
  }
]
```

Behavior notes:

- The renderer rewrites the single-line shell command into backslash-continued lines before typing it.
- Breaks prefer whitespace outside quoted regions.
- `prompt_columns` should match the visible width of the first prompt line.
- `continuation_prompt_columns` is useful when continuation lines also have a visible prompt or gutter.
- Use this for display stability only. If the command is semantically fragile or visually too large even after wrapping, prefer a helper shell script instead.

## Engine-Specific Wait Pattern

Use when ttyd and VHS show different prompts or status text.

```json
{
  "action": "wait_for_text",
  "pattern_by_engine": {
    "ttyd": "bash-5\\.2\\$",
    "vhs": ">"
  },
  "timeout_ms": 10000
}
```

## Teaser Pattern

Use `hide` and `show` to skip setup while still waiting for a meaningful visible state before the reveal.

```json
[
  { "action": "hide" },
  {
    "action": "command",
    "text": "python3 scripts/confirm_demo.py",
    "clear_before": true,
    "wait_for_text": "Apply migration now\\? \\[y/N\\]",
    "timeout_ms": 10000
  },
  { "action": "show" },
  { "action": "screenshot", "name": "01-prompt-ready" }
]
```

## Raw VHS Escape Hatch

Use `raw_vhs` only when the shared model is not enough and you know you need explicit tape commands.

```json
[
  {
    "action": "raw_vhs",
    "lines": [
      "Hide",
      "Sleep 500ms",
      "Show"
    ]
  }
]
```

## Practical Rules

- Keep the scenario in the user workspace, not in the skill directory.
- When the user specifies a size, reflect it in both the ttyd viewport and the VHS canvas.
- Prefer waiting on visible text over fixed sleeps.
- Use `input` when the user needs multiple replies, combo presses, or TUI navigation.
- If the output command is complex or shell-fragile, move it into a wrapper script in the user workspace.
- If the asset is customer-facing, add explicit screenshot steps at the exact moments the user will care about during review.
- For GIF or video review, probe the rendered media first and choose extraction timestamps that are inside the actual clip duration.
- For motion assets, hold critical beats such as confirmations or summaries for `400-800ms` when they need to be readable in the animation itself.
- Motion outputs also hold on the final state by default for 2 seconds. Increase `vhs.endHoldSeconds` when the ending state must be studied, or set it to `0` when you explicitly want an immediate cut.
- If you are solving a problem that already looks like a real customer delivery, read `field-notes.md` before overfitting the scenario. It captures common failure modes and the fixes that worked in real runs.
