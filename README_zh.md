# Terminal Capture Workflow

[English](./README.md)

![tmux + vi showcase](./assets/tmux-vi-showcase.gif)

`terminal-capture-workflow` 是一个 agent skill，用来生成终端截图、分阶段 PNG、GIF、MP4/WebM 演示，以及用于人工视觉验收的抽帧结果，而且不依赖操作系统级别的桌面鼠标键盘注入。同时兼容 OpenAI Codex CLI（`$terminal-capture-workflow`）和 Anthropic Claude Code（`/terminal-capture-workflow`，或由 `SKILL.md` 的 `description` 自动触发）。

## 覆盖能力

- 面向文档、操作指引、报告、评论区的 `ttyd + Playwright` 截图
- 面向 `gif`、`mp4`、`webm` 和关键帧截图的 `VHS` 渲染
- 动态资源默认在结尾驻停，同时支持用户自定义驻停时长
- 泛化输入模型，支持任意文本、多行粘贴、按键、组合键和多阶段交互流程
- 真实 TUI 和 shell 交互，例如 `tmux`、`vi`/`vim`、`less`、确认提示、向导式 CLI
- 通过分页器处理长输出，而不是硬塞进一张图
- 通过探测媒体信息和抽帧做人工视觉验收
- 同时支持用户指定 ttyd 和 VHS 的窗口大小
- 支持按列宽自动续行长命令，避免窄终端里命令输入覆盖原行显示

## 输入模型

scenario 不只支持 `y/N` 这类固定确认，而是可以自由组合交互动作：

- `type`：输入文本，但暂时不回车
- `paste`：快速注入文本，支持多行内容
- `press`：按一个键或组合键，例如 `ctrl+b`、`ctrl+shift+*`、`ctrl+[`、`alt+enter`、`pagedown`
- `input`：把 `text`、`paste`、`press`、`sleep` 事件组合成复杂交互序列
- `raw_vhs`：当你需要写显式 VHS tape 指令时使用的逃生口

对于 `command` 步骤，还可以配置按列宽自动续行：

- `wrap_at_columns`：目标终端字符宽度
- `wrap_indent`：续行缩进，默认是 `2`
- `prompt_columns`：首行可见 prompt 宽度
- `continuation_prompt_columns`：续行时可见 prompt 宽度

设置这些字段后，渲染器会在输入前把超长 shell 命令改写成带反斜杠续行的多行命令。这样可以避免一种常见问题：终端展示宽度和 shell 行编辑器感知宽度不一致时，长命令会在录制画面里覆盖当前行内容。

修饰键名称会做大小写无关归一化，所以 `ctrl+b`、`Ctrl+B`、`CONTROL+b` 都能识别。像 `ctrl+*`、`ctrl+shift+*`、`ctrl+%`、`ctrl+[` 这类“修饰键 + 可打印字符”组合，两条引擎链路都支持。如果你需要的是 VHS 自身语法不接受的“修饰键 + 特殊键”组合，优先走 `ttyd + Playwright`。

## 安装 skill

### Codex CLI

```bash
git clone https://github.com/HansBug/terminal-capture-workflow "${CODEX_HOME:-$HOME/.codex}/skills/terminal-capture-workflow"
```

之后通过 `$terminal-capture-workflow` 显式调用。

### Claude Code

```bash
git clone https://github.com/HansBug/terminal-capture-workflow "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/terminal-capture-workflow"
```

之后通过 `/terminal-capture-workflow` 显式调用，或者依赖 `SKILL.md` 的 `description` 自动触发。

### 同时装到两边

```bash
git clone https://github.com/HansBug/terminal-capture-workflow ~/src/terminal-capture-workflow
ln -s ~/src/terminal-capture-workflow "${CODEX_HOME:-$HOME/.codex}/skills/terminal-capture-workflow"
ln -s ~/src/terminal-capture-workflow "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/terminal-capture-workflow"
```

## 安装依赖

Debian 或 Ubuntu 基础包：

```bash
sudo apt update
sudo apt install -y ttyd ffmpeg less python3-pil nodejs npm
```

安装 VHS：

```bash
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://repo.charm.sh/apt/gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/charm.gpg
echo "deb [signed-by=/etc/apt/keyrings/charm.gpg] https://repo.charm.sh/apt/ * *" | sudo tee /etc/apt/sources.list.d/charm.list >/dev/null
sudo apt update
sudo apt install -y vhs
```

在 skill 目录里安装 Playwright 包：

```bash
npm install
```

如果系统里没有 Chrome 或 Chromium：

```bash
npx playwright install chromium
```

## 基本使用

在开始设计稍微复杂一点的 scenario 前，先读 [`references/field-notes.md`](./references/field-notes.md)。里面整理了真实项目里最容易踩的坑：长命令续行、等待条件不稳、按命令拆分交付，以及不同引擎的 setup 取舍。

先检查环境：

```bash
python scripts/terminal_capture.py check
```

在你的项目里一键生成一个 scenario 的三件套骨架（scenario JSON + render 脚本 + 可选 setup 脚本）：

```bash
python scripts/terminal_capture.py init my-demo --engine vhs --with-setup
# → scenarios/my-demo.json, scripts/render_my-demo.sh, scripts/setup_my-demo.sh
bash scripts/render_my-demo.sh
```

完整 rationale、输出路径约定、README badge / CI 接入方式见 [`references/project-layout.md`](./references/project-layout.md)。

渲染已有 scenario：

```bash
python scripts/terminal_capture.py render all /path/to/scenario.json
```

选择抽帧时间点前先探测媒体信息：

```bash
python scripts/terminal_capture.py probe-media /path/to/demo.mp4
```

从视频或 GIF 中抽取验收帧：

```bash
python scripts/terminal_capture.py extract-frames /path/to/demo.mp4 --times 0.8,2.4,4.8
```

## 仓库结构

- [`SKILL.md`](./SKILL.md)：Codex 与 Claude Code 都会加载的 skill 正文
- [`AGENTS.md`](./AGENTS.md) / [`CLAUDE.md`](./CLAUDE.md)：仓库层面的维护约定（`CLAUDE.md` 是 `AGENTS.md` 的 symlink）
- [`scripts/terminal_capture.py`](./scripts/terminal_capture.py)：环境检测、统一渲染入口、媒体验收辅助能力
- [`scripts/render_ttyd_scenario.js`](./scripts/render_ttyd_scenario.js)：ttyd + Playwright 渲染器
- [`references/environment-and-install.md`](./references/environment-and-install.md)：依赖与安装说明
- [`references/scenario-patterns.md`](./references/scenario-patterns.md)：scenario 结构与交互模式
- [`references/field-notes.md`](./references/field-notes.md)：实战经验、踩坑记录与脱敏后的真实示例
- [`assets/tmux-vi-showcase.gif`](./assets/tmux-vi-showcase.gif)：由这套工作流真实渲染出的展示 GIF

## 说明

- scenario JSON 应该放在目标工作区，而不是 skill 目录里。
- 能等可见文本时，就优先用可见文本等待，不要滥用固定 sleep。
- 脆弱的 shell pipeline 先封装成工作区脚本，再放进 scenario。
- 长输出优先接到 `less -R` 或其他分页器，而不是强行塞进一张图。
- 对于单行很长的 shell 命令，优先给 `command` 配 `wrap_at_columns`，不要赌终端模拟器和 shell prompt 的自动换行能刚好对齐。
- 动态输出默认会在最后一帧额外停 2 秒；如果用户要自己控制，就设置 `vhs.endHoldSeconds`，设成 `0` 则关闭。
