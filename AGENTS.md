# AGENTS.md

This repository publishes an agent skill that works with both OpenAI Codex and Anthropic Claude Code.
Treat it as both:

- the installable skill payload for Codex (`~/.codex/skills/terminal-capture-workflow`) and Claude Code (`~/.claude/skills/terminal-capture-workflow`)
- the public GitHub source of truth for that payload

## Purpose

`terminal-capture-workflow` produces terminal screenshots, staged PNG stills, GIFs, and MP4/WebM demos through two non-intrusive engines (`ttyd + Playwright` and `VHS`). No OS-level desktop input injection is used or added as a fallback.

## Structure

- `SKILL.md` is the skill body that both CLIs load.
- `CLAUDE.md` is a symlink to this file. Editing `AGENTS.md` covers both agents.
- `scripts/terminal_capture.py` and `scripts/render_ttyd_scenario.js` resolve `SKILL_ROOT` from `__file__`, so the install location does not change behavior.
- `references/` holds on-demand docs the skill reads during real work.
- `assets/` holds demo media referenced from the README.
- `agents/openai.yaml` is Codex-specific UI metadata; Claude Code ignores it.

## Editing Rules

1. Keep the two-engine story honest. Any scenario feature should state its behavior under both `ttyd` and `vhs`, or explicitly mark itself engine-specific.
2. When the invocation surface or default behavior changes, review `SKILL.md`, `README.md`, `README_zh.md`, `references/scenario-patterns.md`, and `agents/openai.yaml` together.
3. Scenario JSON files belong in user workspaces. Do not commit ad-hoc scenarios into this repo; reference examples belong in `references/`.
4. After script changes, run `python scripts/terminal_capture.py check` to confirm the environment probe still works.

## Validation Expectations

Before pushing a functional change, at minimum do all of these:

- `python3 -m py_compile scripts/terminal_capture.py`
- `python3 scripts/terminal_capture.py check`
- `python3 scripts/terminal_capture.py --help`
- `python3 -m pytest tests/` (see *Unit Tests* below)

For behavior changes, also do real end-to-end checks:

- one `codex exec` render using `$terminal-capture-workflow`
- one `claude -p` render using `/terminal-capture-workflow` (or description-triggered)
- at least one `ttyd` still and one `vhs` motion output

## Unit Tests

- Tests live in `tests/`. `tests/conftest.py` adds `scripts/` to `sys.path` so `from terminal_capture import ...` works without packaging the renderer. No `pyproject.toml` / `setup.py` — the repo stays single-script-friendly.
- Runner is `pytest`. The test files only use plain `def test_*` + `assert`, so any reasonably recent pytest works; the dev environment is pinned at the top of `tests/conftest.py`. Run from the repo root: `python3 -m pytest tests/`. CI-friendly flags like `-q` or `-v` are fine.
- New test files go in `tests/test_*.py`. Share helpers and path injection via `conftest.py`.
- Test-driven workflow for any change to `scripts/terminal_capture.py` or `scripts/render_ttyd_scenario.js`:
  1. Write the failing test first. Run pytest. Watch it fail **for the right reason** (feature missing, not a typo).
  2. Write the minimal fix. Run pytest. Watch it pass.
  3. For renderer behavior changes, also run **at least one VHS end-to-end render** of a scenario that exercises the changed code path. Pytest alone cannot prove the generated tape parses on the real `vhs` binary.
- **When pytest and e2e disagree, e2e is the ground truth about the rendering toolchain (VHS, ttyd).** Re-examine the test invariant first — verify with a second minimal probe (see `references/field-notes.md` for the canonical VHS Type-string probe) before deciding which half of the contradiction was wrong. Do not paper over an e2e failure by widening the test. Note that e2e itself can be wrong too (a VHS regression, a ttyd version change, a platform difference); the discipline is "re-test the assumption", not "e2e is always right". Issue #3 / PR #15 is the canonical worked example: pytest greenlit an "escape `\` to `\\`" fix that the real VHS binary rejected, and the resolution was to revise the test invariant and withdraw the fix.
- Cross-renderer symmetry: when patching `wrap_shell_command_text` or other shared logic in `scripts/terminal_capture.py`, mirror the change in `scripts/render_ttyd_scenario.js`. We do not currently run JS unit tests, so manual symmetry check plus `node --check scripts/render_ttyd_scenario.js` is the bar. If a JS-only bug emerges, add a JS test harness rather than dropping the symmetry — default to Node's stdlib `node:test` + `node --test` to avoid pulling in a bundler/runner dependency; only escalate to `vitest` / `jest` if a real DOM or Playwright integration is needed.

## What Not To Do

- Do not introduce OS-level keyboard or mouse injection as a fallback.
- Do not silently change default engine selection.
- Do not move renderer anchoring away from `SKILL_ROOT`; absolute paths baked into scenarios make the skill non-portable between installs.
- Do not force the skill into a single engine when a flow legitimately needs both stills and motion.
