# [P1][Track C] 新增 `wait_for_prompt` 语糖 + scenario lint

## 背景

`references/field-notes.md` 推荐做法之一是"等 prompt 回归"，但目前需要用户每次手写正则：

```json
{ "wait_for_text": "demo \\$", "timeout_ms": 30000 }
```

跨项目里见到的 prompt 正则有十几种变体（`bash-5\.2\$` / `>` / `demo\$` / `\(venv\) repo\$` / `❯` …），重复劳动 + 容易写错（pyfcstm-2 早期就写过 `demo\$` 漏了空格匹配，timeout）。同时 scenario 里"command 紧跟 screenshot 但没 wait"这种结构性错误，肉眼也不容易发现。

## 改动方案

### 1. 新增 step 字段 `wait_for_prompt`

可接两种值：

- `true`：使用内置默认 prompt 正则
- `string`：用户自定义 prompt 正则

实现在 `command` 步骤和独立 `wait_for_prompt` 动作里都生效：

```json
{
  "action": "command",
  "text": "long_cmd || true",
  "wait_for_prompt": true,
  "timeout_ms": 30000
}
```

或独立用：

```json
{ "action": "wait_for_prompt", "prompt": "❯" }
```

### 2. 默认 prompt 正则

```python
DEFAULT_PROMPT_REGEX = r"[\$#%▶❯>]\s*$"
```

这个表达式覆盖：
- bash / zsh / sh 默认 `$` 或 `#`
- 老 csh `%`
- starship / fish 的 `❯` / `▶`
- 一些自定义 `>`

加 `\s*$` 容忍尾部空格；用 multiline 模式时还能配合 `\n` 后跟字符。

### 3. 优先级

如果 step 同时给了 `wait_for_text` 和 `wait_for_prompt`，规则：

- 两个都等：先等 `wait_for_text`（具体到内容），再等 `wait_for_prompt`（命令真正返回）
- 这套组合就是 field-notes 推荐的"先等 summary 行，再等 prompt 回归"

### 4. Scenario lint

新加 `python scripts/terminal_capture.py validate-scenario <file> --lint`（依赖 #9 的 validate-scenario 子命令）。lint 规则：

| 编号 | 规则 | 严重度 |
|---|---|---|
| L01 | `command` 后紧跟 `screenshot` 但 step 自身既没 `wait_*` 也没 `result_shot`/`typed_shot` | warning |
| L02 | `command` 既没 `wait_for_text` 也没 `wait_for_prompt`，且没设 `result_delay_ms` | warning |
| L03 | `wait_for_text` 的 pattern 含未转义元字符（`(`, `?`, `*`, `+`），且没显式 `flags` | info |
| L04 | `screenshot` 步骤的 `name` 重名（覆盖前一张） | error |
| L05 | `wrap_at_columns` 启用但 `prompt_columns=0` | info |
| L06 | step 用了 `raw_vhs` 但同时引擎指定为 ttyd | error |

输出格式参考 ruff：`scenario.json:step[2]:L01 command-followed-by-screenshot-without-wait`。

### 5. 文档同步

- `references/scenario-patterns.md` 新增 "Wait for Prompt Pattern" 小节
- `references/field-notes.md` 把"等 prompt 回归"段重写为引用 `wait_for_prompt: true`
- `SKILL.md` Common Pitfalls（#2 落地后）的第一条改成引用 `wait_for_prompt`

## 向后兼容

新增字段，旧 scenario 不受影响。lint 是新子命令，可选用。

## 验收标准 (Codex)

```bash
codex exec '
cat > /tmp/prompt-wait.json <<JSON
{
  "name": "prompt-wait",
  "cwd": "/tmp",
  "shell": ["bash","--noprofile","--norc","-i"],
  "vhs": {"width":1280,"height":480,"outputs":["mp4"]},
  "steps": [
    {"action":"command","text":"for i in $(seq 1 50); do echo line $i; done","clear_before":true,"wait_for_prompt":true,"timeout_ms":15000,"result_shot":"after"}
  ]
}
JSON
python "$HOME/.codex/skills/terminal-capture-workflow/scripts/terminal_capture.py" render vhs /tmp/prompt-wait.json
# 修复后：拿到 after.png；before-fix 必须显式写 wait_for_text 才能稳。
python "$HOME/.codex/skills/terminal-capture-workflow/scripts/terminal_capture.py" validate-scenario /tmp/prompt-wait.json --lint
# lint 应安静通过，没有 warning
'
```
