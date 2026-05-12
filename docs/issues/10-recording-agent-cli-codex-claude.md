# [P1][Track H] 新增 `references/recording-agent-cli.md` + Codex/Claude TUI starter scenarios

## 背景

用户明确诉求："这一次还需要强化针对 codex 和 claude 这些东西的录制能力"。

当前 skill 默认面向"录 bash 单命令 demo"，但实际录制 codex / claude 这类 LLM TUI 时有一系列特殊问题：

### 录制 codex / claude 时的真实障碍

| 问题 | 现象 | 当前 skill 怎么处理 |
|---|---|---|
| 流式 token 输出 | wait_for_text 命中瞬间画面还在变 | 无原语，靠固定 sleep |
| spinner 动画 | 截图随机抓到 ⣾ ⣽ ⣻ ⢿ 任一帧 | 无原语 |
| tool call 边框 panel | 终端窄了会丑陋折行 | 无指导 |
| slash 命令弹窗 | `/help` 弹下拉菜单，按 esc 关闭，时机敏感 | 无指导 |
| 多行输入需要按上键 / 编辑 | 现有 input{} 够用但没示例 | scenario-patterns.md 有但不针对 agent CLI |
| API key 注入 | 不能写进 scenario | 无指导 |
| 长输出 + 长 session | 几屏后滚出 viewport | 依赖 #4 修复 |
| codex 的"思考中"画面应该不应该录 | 用户偏好不同 | 无指导 |

## 改动方案

### 1. 新增 `references/recording-agent-cli.md`（中文）

章节大纲：

#### 1.1 选 one-shot 还是交互
- `codex exec "<prompt>"` 和 `claude -p "<prompt>"` 是 one-shot 模式：进程跑完就退，适合录"问 → 答 → 完"三幕
- 不带 `exec`/`-p` 进入交互 TUI：适合录多轮、tool use 编排、slash command 演示
- one-shot 模式录制更简单，推荐作为入门起点

#### 1.2 viewport 与字体
- 一般推荐 `vhs.width >= 1400`，`vhs.height >= 800`；codex/claude 的 tool panel 边框宽度对窄终端不友好
- `fontSize` 18-22；过小看不清，过大装不下
- ttyd 录制时 `viewport.deviceScaleFactor: 2` 出 retina 清晰图

#### 1.3 wait_until_stable 必备
- 配合 #7：`wait_until_stable: { ms: 1200 }` 是 LLM 流式输出的下限
- pattern 选行尾标志：claude 用 `^❯` 或 `Total cost` 或自定义结束语；codex 用最后 sandbox status 行
- 不要用响应内容里的特定词做 pattern——LLM 输出不可预测

#### 1.4 API key 与凭据
- **绝对不要**把 key 写进 scenario JSON
- 推荐方法：scenario `pre_warm` 里用 `export ANTHROPIC_API_KEY=$(cat ~/.config/anthropic/key)` 或 `source ~/.config/codex/auth.sh`
- 或者用环境变量从 shell 注入：`ANTHROPIC_API_KEY=... bash scripts/render_xxx.sh`
- README 加一条 banner 提示

#### 1.5 录交互 TUI 的常见模式
- 输入 prompt：`paste` 多行；不要 `type` 几百字（typingDelayMs 拖慢）
- 等待生成：`wait_for_text` + `wait_until_stable`
- 截 tool call panel：在 panel 完整渲染后单独 `screenshot`
- 关闭弹窗：`press: esc` 后 `sleep 200ms` 等动画
- 退出：`/exit` 或 ctrl+c

#### 1.6 隐藏 API key 之外还能 hide 什么
- 第一次启动的 onboarding banner（用 `hide` 包 `--print` warmup 或预先 `claude /clear`）
- shell prompt 噪音：在 pre_warm 里 `export PS1='❯ '`
- 终端宽度提示：`stty rows 50 cols 180` + `clear`

#### 1.7 处理"思考中" UI
- claude 默认显示 "thinking..." spinner 几秒；codex 显示 sandbox 信息
- 录教学视频时通常保留（增加节奏感）
- 录"功能 demo"时可加更长 `wait_until_stable`，截最终静态画面

#### 1.8 验证产物的清单
- 起始帧：能看到 prompt 已输入
- 中间帧（如果保留）：spinner / 流式
- 终态帧：完整答案 + 行尾标志
- endHoldSeconds：教程类 >= 4s

### 2. 新增 starter scenarios

放 `references/starters/`。`init` 子命令（#5）可以 `--from-starter <name>` 直接拷贝。

#### `references/starters/recording-codex-session.json`

```json
{
  "name": "codex-rag-demo",
  "cwd": ".",
  "shell": ["bash","--noprofile","--norc","-i"],
  "vhs": {
    "fontSize": 18,
    "width": 1500,
    "height": 900,
    "padding": 16,
    "framerate": 30,
    "endHoldSeconds": 5,
    "outputs": ["gif", "mp4"]
  },
  "ttyd": {
    "fontSize": 16,
    "viewport": { "width": 1500, "height": 900, "deviceScaleFactor": 2 }
  },
  "pre_warm": [
    { "action": "command", "text": "test -n \"$OPENAI_API_KEY\" || (echo 'set OPENAI_API_KEY first' && false)", "wait_for_prompt": true }
  ],
  "steps": [
    { "action": "command", "text": "codex exec '一句话解释什么是 RAG'", "clear_before": true, "wait_for_prompt": true, "wait_until_stable": { "ms": 1500 }, "timeout_ms": 60000, "result_shot": "01-final" }
  ]
}
```

#### `references/starters/recording-claude-session.json`

```json
{
  "name": "claude-greeting-demo",
  "cwd": ".",
  "shell": ["bash","--noprofile","--norc","-i"],
  "vhs": {
    "fontSize": 18,
    "width": 1500,
    "height": 900,
    "padding": 16,
    "framerate": 30,
    "endHoldSeconds": 5,
    "outputs": ["gif", "mp4"]
  },
  "ttyd": {
    "fontSize": 16,
    "viewport": { "width": 1500, "height": 900, "deviceScaleFactor": 2 }
  },
  "pre_warm": [
    { "action": "command", "text": "test -n \"$ANTHROPIC_API_KEY\" || (echo 'set ANTHROPIC_API_KEY first' && false)", "wait_for_prompt": true }
  ],
  "steps": [
    { "action": "command", "text": "claude -p '用三句话介绍 Claude Code 是什么'", "clear_before": true, "wait_for_prompt": true, "wait_until_stable": { "ms": 1500 }, "timeout_ms": 90000, "result_shot": "01-final" }
  ]
}
```

#### `references/starters/recording-claude-interactive.json`

录交互模式 + slash command。略，结构同上，加 `input` 步骤包 `/clear`、prompt、`/exit`。

### 3. `init` 子命令联动

`init` 支持 `--from-starter codex-session | claude-session | claude-interactive`，直接复制 starter 模板。

### 4. SKILL.md 引用

"References" 节加 `references/recording-agent-cli.md`，说明"录制 codex / claude 等 agent CLI 时先读此文"。

## 向后兼容

新增 references 文件 + starter 文件 + `init --from-starter` flag；零既有行为变化。

## 验收标准 (Codex)

```bash
codex exec '
# 复制 starter，替换实际 prompt，跑一次录制
SKILL_ROOT="$HOME/.codex/skills/terminal-capture-workflow"
mkdir -p /tmp/codex-rec && cd /tmp/codex-rec
python "$SKILL_ROOT/scripts/terminal_capture.py" init my-codex --from-starter codex-session
test -f scenarios/my-codex.json
test -f scripts/render_my-codex.sh

# 实际跑（需要 OPENAI_API_KEY）
export OPENAI_API_KEY=...
bash scripts/render_my-codex.sh

# 视检：末帧应是 codex 完整答案，无 spinner 残影
python "$SKILL_ROOT/scripts/terminal_capture.py" extract-frames .terminal-capture-output/vhs/codex-rag-demo/codex-rag-demo.mp4 --auto-final
'
```

读 `references/recording-agent-cli.md`，让 Codex 回答：

```bash
codex exec '
读 ~/.codex/skills/terminal-capture-workflow/references/recording-agent-cli.md
回答：
1. 录制流式 token 输出时为什么必须用 wait_until_stable
2. API key 应该放在哪里，绝对不能放哪里
3. tool call panel 容易破相时应该把哪个参数调多大
'
```
