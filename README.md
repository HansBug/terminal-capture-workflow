# Terminal Capture Workflow

[简体中文](./README_zh.md)

![tmux + vi showcase](./assets/tmux-vi-showcase.gif)

`terminal-capture-workflow` is an agent skill for producing terminal screenshots, staged PNG stills, GIFs, MP4/WebM demos, and visual QA frames without OS-level desktop input injection. It works with both OpenAI Codex CLI (`$terminal-capture-workflow`) and Anthropic Claude Code (`/terminal-capture-workflow`, or auto-triggered from the `description` in `SKILL.md`).

## What It Covers

- `ttyd + Playwright` screenshots for guides, reports, docs, and issue comments
- `VHS` rendering for `gif`, `mp4`, `webm`, and staged stills
- Default final-frame hold for motion outputs, plus user-controlled end-hold duration
- A generalized input model for arbitrary text, multiline paste, key presses, modifier chords, and multi-step interactive flows
- Real TUI and shell interactions such as `tmux`, `vi`/`vim`, `less`, prompts, and wizard-style CLIs
- Long-output capture with pagers instead of forcing everything into one frame
- Visual QA by probing rendered media and extracting representative frames
- User-controlled window sizes for both ttyd and VHS outputs
- Column-aware long-command wrapping for `command` steps so shell input stays readable in narrow terminal captures

## Input Model

Scenarios can compose interactions instead of hard-coding only `y/N` prompts:

- `type`: type text without pressing enter yet
- `paste`: inject text quickly, including multiline content
- `press`: press a key or combo such as `ctrl+b`, `ctrl+shift+*`, `ctrl+[`, `alt+enter`, `pagedown`
- `input`: build richer sequences from `text`, `paste`, `press`, and `sleep` events
- `raw_vhs`: explicit VHS escape hatch when you need engine-specific tape lines

For `command` steps, scenarios can also request column-aware wrapping with:

- `wrap_at_columns`: target terminal width in characters
- `wrap_indent`: indentation for wrapped continuation lines, defaults to `2`
- `prompt_columns`: visible prompt width on the first line
- `continuation_prompt_columns`: visible prompt width on continuation lines

When these fields are set, the renderers split long shell commands into backslash-continued lines before typing them. This avoids the common capture failure where a long command visually overwrites the current line because the simulated terminal width and the shell's line editor disagree.

Modifier names are normalized case-insensitively, so `ctrl+b`, `Ctrl+B`, and `CONTROL+b` all work. Printable-key chords such as `ctrl+*`, `ctrl+shift+*`, `ctrl+%`, and `ctrl+[` are supported across both engines. When you need special-key chords that VHS itself rejects, prefer the `ttyd + Playwright` path.

## Install The Skill

### Codex CLI

```bash
git clone https://github.com/HansBug/terminal-capture-workflow "${CODEX_HOME:-$HOME/.codex}/skills/terminal-capture-workflow"
```

Then invoke it explicitly as `$terminal-capture-workflow`.

### Claude Code

```bash
git clone https://github.com/HansBug/terminal-capture-workflow "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/terminal-capture-workflow"
```

Then invoke it explicitly as `/terminal-capture-workflow`, or let Claude Code auto-trigger it from the description in `SKILL.md`.

### Shared Clone (Both)

```bash
git clone https://github.com/HansBug/terminal-capture-workflow ~/src/terminal-capture-workflow
ln -s ~/src/terminal-capture-workflow "${CODEX_HOME:-$HOME/.codex}/skills/terminal-capture-workflow"
ln -s ~/src/terminal-capture-workflow "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/terminal-capture-workflow"
```

## Install Dependencies

Debian or Ubuntu base packages:

```bash
sudo apt update
sudo apt install -y ttyd ffmpeg less python3-pil nodejs npm
```

Install VHS:

```bash
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://repo.charm.sh/apt/gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/charm.gpg
echo "deb [signed-by=/etc/apt/keyrings/charm.gpg] https://repo.charm.sh/apt/ * *" | sudo tee /etc/apt/sources.list.d/charm.list >/dev/null
sudo apt update
sudo apt install -y vhs
```

Install the Playwright package in the skill directory:

```bash
npm install
```

If no system Chrome or Chromium browser is available:

```bash
npx playwright install chromium
```

## Basic Usage

Before building a nontrivial scenario, read [`references/field-notes.md`](./references/field-notes.md). It captures the failure modes that show up in real capture work: long command wrapping, flaky waits, split-per-command deliverables, and engine-specific setup tradeoffs.

Check the environment first:

```bash
python scripts/terminal_capture.py check
```

Bootstrap a brand-new scenario in your project (one-shot scaffold):

```bash
python scripts/terminal_capture.py init my-demo --engine vhs --with-setup
# → scenarios/my-demo.json, scripts/render_my-demo.sh, scripts/setup_my-demo.sh
bash scripts/render_my-demo.sh
```

See [`references/project-layout.md`](./references/project-layout.md) for the rationale, output-path conventions, and CI integration patterns.

Render an existing scenario:

```bash
python scripts/terminal_capture.py render all /path/to/scenario.json
```

Probe a rendered media file before choosing review timestamps:

```bash
python scripts/terminal_capture.py probe-media /path/to/demo.mp4
```

Extract review frames from a video or GIF:

```bash
python scripts/terminal_capture.py extract-frames /path/to/demo.mp4 --times 0.8,2.4,4.8
```

## Repository Structure

- [`SKILL.md`](./SKILL.md): skill body that both Codex and Claude Code load
- [`AGENTS.md`](./AGENTS.md) / [`CLAUDE.md`](./CLAUDE.md): project-level maintenance rules (`CLAUDE.md` is a symlink to `AGENTS.md`)
- [`scripts/terminal_capture.py`](./scripts/terminal_capture.py): environment check, render orchestration, and media inspection helpers
- [`scripts/render_ttyd_scenario.js`](./scripts/render_ttyd_scenario.js): ttyd + Playwright renderer
- [`references/environment-and-install.md`](./references/environment-and-install.md): dependency and installation guidance
- [`references/scenario-patterns.md`](./references/scenario-patterns.md): scenario schema and interaction patterns
- [`references/field-notes.md`](./references/field-notes.md): real-world capture lessons, pitfalls, and sanitized examples
- [`assets/tmux-vi-showcase.gif`](./assets/tmux-vi-showcase.gif): real showcase asset rendered by the workflow

## Notes

- Put scenario JSON files in the target workspace, not in the skill directory.
- Prefer visible-text waits over fixed sleeps whenever possible.
- Wrap fragile shell pipelines in helper scripts before embedding them in a scenario.
- Route long output through `less -R` or another pager instead of forcing a huge transcript into one screenshot.
- For long single-line shell commands, prefer `command` with `wrap_at_columns` instead of hoping the terminal emulator and shell prompt wrap the same way on their own.
- Motion outputs hold the final state for 2 seconds by default. Override that with `vhs.endHoldSeconds`, or set it to `0` when you explicitly want an immediate cut.
