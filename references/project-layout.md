# Project Layout for Terminal Capture Scenarios

Use this reference when a downstream repo needs to **own its capture artifacts** — commit scenarios, regenerate GIFs / MP4s on demand, hand the recipe to teammates or CI. The `python scripts/terminal_capture.py init <name>` subcommand scaffolds the layout below in one shot; this doc explains why each piece is shaped the way it is.

## The three-piece layout

```
<your-repo>/
├── scenarios/
│   └── <name>.json              # scenario authored by you, committed to repo
└── scripts/
    ├── render_<name>.sh         # `init` scaffolds this; thin wrapper around terminal_capture.py
    └── setup_<name>.sh          # optional, with `init --with-setup`; repo-specific prep
```

This is the same shape that pyfcstm, pyplantuml, animedex, and other downstream consumers each rediscovered by hand — formalize it once and stop reinventing it.

### Why `scenarios/` is not `scripts/`

`scenarios/*.json` are **declarative data**, not code. Keeping them separate from `scripts/` lets reviewers tell at a glance whether a PR is editing capture intent (data) or how renders are invoked (code). It also matches makefile-style conventions in nearby ecosystems (data in `data/`, code in `scripts/`).

### Why `setup_<name>.sh` is separate from `render_<name>.sh`

`render_<name>.sh` is **portable** — it only needs `terminal_capture.py`, the scenario JSON, and the engines installed. Anyone who clones the repo can run it.

`setup_<name>.sh` is **repo-specific** — it might `pip install -e .`, source a venv, prefetch HTTP fixtures, export API keys from a secret manager, or start a mock server. Most repos do not need it; some need quite a lot.

Mixing the two means every render of a polished, stable scenario keeps re-running brittle setup. Splitting them means the render step is reproducible long after the setup happens to evolve.

When a setup script exists, the typical run is:

```bash
bash scripts/setup_<name>.sh   # warm caches, install deps, ...
bash scripts/render_<name>.sh  # produce the capture
```

If you want a one-shot, write a tiny `make capture` target or a top-level orchestrator script — keep `render_*.sh` itself focused on the rendering step.

## What `init` generates

The wrapper script (`scripts/render_<name>.sh`) is intentionally **portable across both supported agent CLIs**:

```bash
#!/usr/bin/env bash
set -euo pipefail

SKILL_ROOT="${SKILL_ROOT:-$HOME/.claude/skills/terminal-capture-workflow}"
if [ ! -d "$SKILL_ROOT" ]; then
  SKILL_ROOT="$HOME/.codex/skills/terminal-capture-workflow"
fi

cd "$(dirname "$0")/.."
python3 "$SKILL_ROOT/scripts/terminal_capture.py" render <engine> scenarios/<name>.json "$@"
```

Three rules baked in:

1. **`SKILL_ROOT` env override comes first.** Useful when working from a branch clone instead of the installed skill copy (set `SKILL_ROOT=$PWD bash scripts/render_<name>.sh` to test local changes), or on a fresh machine where neither install path exists yet.
2. **Claude install path first, Codex fallback.** Just an arbitrary preference order; both work.
3. **`cd "$(dirname "$0")/.."` before invoking Python.** The render script can be invoked from any cwd; chdir to the project root keeps `scenarios/<name>.json` relative-resolvable.

The trailing `"$@"` forwards extra CLI flags (`--output-root`, `--cwd`, etc.) so the same script works for ad-hoc overrides:

```bash
bash scripts/render_<name>.sh --output-root docs/captures/
```

## Where to write outputs

By default the renderer writes to `<scenario_cwd>/.terminal-capture-output/`. That directory should be in `.gitignore`. This is the right choice for **scratch / iteration** mode: you regenerate locally, commit the scenario JSON + render script, and let collaborators re-render fresh on their machines.

For **team-shared deliverables** (homepage GIFs, README hero clips, paper figures), commit the *output* too — pin a stable copy in `docs/captures/<name>/` or `assets/captures/<name>/` and pass it to render:

```bash
bash scripts/render_<name>.sh --output-root docs/captures/
git add docs/captures/<name>/
```

This is how PRs can review the rendered artifact without rebuilding it locally.

## Wiring into README / CI

A common pattern, once the three-piece layout is in place:

### README badge

```markdown
![Capture](docs/captures/hero/hero.gif)

> Regenerate with `bash scripts/render_hero.sh` (requires terminal-capture-workflow installed; see [skill docs](https://github.com/HansBug/terminal-capture-workflow)).
```

### CI smoke

```yaml
# .github/workflows/render-smoke.yml
- name: Smoke-test capture renders
  run: |
    pipx run --spec git+https://github.com/HansBug/terminal-capture-workflow ...
    bash scripts/render_hero.sh
    test -f .terminal-capture-output/vhs/hero/hero.mp4
```

(The exact install incantation depends on what the skill ships as; see the upstream skill README. The pattern is: install / locate skill, run `bash scripts/render_*.sh`, assert artifacts exist.)

## When NOT to use this layout

- One-off captures with no expectation of re-render → write a scenario JSON in `/tmp`, run it, post the artifact, move on. `init` would over-scaffold.
- Scenarios that depend on heavy live state (databases, paid APIs) and cannot be replayed → consider committing only the rendered artifacts and treating the scenario JSON as documentation rather than a reproducible recipe.

## Reference: `init` flags

```bash
python "$SKILL_ROOT/scripts/terminal_capture.py" init <name> \
    [--engine ttyd|vhs|all]   # default: all
    [--with-setup]             # also scaffold setup_<name>.sh
```

Behavior:

- Refuses to overwrite any existing file with the target name (`FileExistsError`); no partial writes.
- Names must match `^[A-Za-z0-9][A-Za-z0-9_-]*$`.
- `<scenarios>` and `<scripts>` directories are auto-created if missing.
