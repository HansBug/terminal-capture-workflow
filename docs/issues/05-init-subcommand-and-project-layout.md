# [P1][Track B] 新增 `init` 子命令 + `references/project-layout.md`

## 背景

跨项目调研里，每个下游使用者都各自发明了"scenario + setup + render 三件套"的工程化布局：

- **pyfcstm-2**：`scenarios/01_notpatched_static_check.json` / `scenarios/02_notpatched_validate.json` 等 4 个 scenario 共置；持久输出到 `~/Nutstore/work/pyfcstm_cli_demos/`，README 注明"任何人都能在本机一键重放所有 4 段录制"。
- **pyplantuml-bundled**：用户原话"改成 `docs/cli-demo.{setup.sh,hello.puml}` 提交进仓库，配 `scripts/render_cli_demo.sh` 一键再生"。
- **animedex**：`docs/source/_static/gifs/{hero,quickstart,anilist,jikan,trace,nekos}.tape`，但**没有 render 脚本**；用户在多次 commit 里手动 `cd ... && vhs xxx.tape`。

这套布局应该被官方约定，并且通过子命令自动生成。否则每个项目都会"再造轮子但少一根"——animedex 缺 render 脚本、pyplantuml 早期把 setup 留在 `/tmp`、pyfcstm-2 把输出路径写死到 Nutstore。

## 改动方案

### 1. 新增子命令

```bash
python scripts/terminal_capture.py init <scenario-name> \
    [--engine ttyd|vhs|all] \
    [--with-setup] \
    [--output-dir <path>]
```

行为：在当前 cwd 生成（不覆盖已存在文件，遇到则报错）：

```
<cwd>/
├── scenarios/<scenario-name>.json
├── scripts/render_<scenario-name>.sh
└── scripts/setup_<scenario-name>.sh    # 仅 --with-setup
```

`scenarios/<scenario-name>.json` 是最小可跑模板：

```json
{
  "name": "<scenario-name>",
  "cwd": ".",
  "shell": ["bash", "--noprofile", "--norc", "-i"],
  "vhs": {
    "fontSize": 22,
    "width": 1280,
    "height": 760,
    "outputs": ["gif", "mp4"],
    "endHoldSeconds": 3
  },
  "ttyd": {
    "fontSize": 20,
    "viewport": {"width": 1400, "height": 560, "deviceScaleFactor": 2}
  },
  "steps": [
    {
      "action": "command",
      "text": "echo hello world",
      "clear_before": true,
      "wait_for_text": "hello world",
      "timeout_ms": 5000,
      "result_shot": "01-hello"
    }
  ]
}
```

`scripts/render_<scenario-name>.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail
SKILL_ROOT="${SKILL_ROOT:-$HOME/.claude/skills/terminal-capture-workflow}"
if [ ! -d "$SKILL_ROOT" ]; then
  SKILL_ROOT="$HOME/.codex/skills/terminal-capture-workflow"
fi
cd "$(dirname "$0")/.."
python "$SKILL_ROOT/scripts/terminal_capture.py" render <engine> scenarios/<scenario-name>.json
```

`scripts/setup_<scenario-name>.sh`（占位）：

```bash
#!/usr/bin/env bash
set -euo pipefail
# Put repo-specific prep here.
# Examples:
#   pip install -e .
#   source venv/bin/activate
#   bash scripts/prefetch_fixtures.sh
```

### 2. `references/project-layout.md`

新增中英双语小节说明：

- 推荐的目录布局（同上）
- 为什么 setup 脚本和 render 脚本要分开（setup 描述 repo-specific 环境；render 描述哪个 scenario 怎么跑）
- 为什么 scenario 文件在 `scenarios/`、render 在 `scripts/` —— 跟 makefile 风格约定贴合
- 如何把这套接入 README badge / CI
- 输出路径建议：默认 `.terminal-capture-output/`（已加 `.gitignore`）；若要团队共享，显式 `--output-root docs/captures/` 写到 repo 内

### 3. 一致性：现有引用同步更新

- `SKILL.md` "Workflow" 第 6 项之前加一条"如果是新 scenario，先 `terminal_capture.py init <name>` 生成骨架"
- `README.md` / `README_zh.md` "Quick Start" 加引用

## 向后兼容

新增子命令；现有用法零影响。

## 验收标准 (Codex)

```bash
codex exec '
mkdir -p /tmp/init-test
cd /tmp/init-test
python "$HOME/.codex/skills/terminal-capture-workflow/scripts/terminal_capture.py" init my-demo --engine vhs --with-setup
test -f scenarios/my-demo.json
test -x scripts/render_my-demo.sh
test -x scripts/setup_my-demo.sh
bash scripts/render_my-demo.sh
test -f .terminal-capture-output/vhs/my-demo/my-demo.mp4
'
```
