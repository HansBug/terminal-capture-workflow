# [P0][Track F] 修复 escape_vhs_text 漏转义 `\` + wrap_shell_command_text 末位续行多重转义

## 背景

代码审计发现 `scripts/terminal_capture.py` 两处转义边界 bug，目前没在生产里炸主要是因为下游 scenario 还没大量出现含字面反斜杠的命令文本，但只要一出就会破坏整段录制。

## Bug 1：`escape_vhs_text` 漏转义反斜杠

**位置**：`scripts/terminal_capture.py:188-193`

```python
def escape_vhs_text(text: str) -> str:
    return (
        text.replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace('"', '\\"')
    )
```

这个函数被 `build_vhs_type_command` 调用，输出形如 `Type "<escaped_text>"`。VHS 解析 tape 文件时，**双引号字符串里的 `\` 会触发它自己的转义**（虽然 VHS 文档没明说，charm/vhs 源码用 Go fmt 风格扫）。

**触发示例**：

```bash
echo --regex '\d+'    # 用户期待原样打入终端
```

经 `escape_vhs_text` 后写入 tape：

```
Type "echo --regex '\d+'"
```

VHS 看到 `\d` 会按它自己的逻辑处理（不一定崩，但行为依赖版本），用户期待的字面反斜杠丢失。

**field-notes.md 自己写过**：
> "make sure the renderer types a single trailing backslash" / "do not double-escape backslashes that are meant to be typed literally"

但代码并没有 guard。

## Bug 2：`wrap_shell_command_text` 末位续行多重转义

**位置**：`scripts/terminal_capture.py:170` 附近

```python
lines.append(f"{chunk} \\")
```

如果 `chunk` 末尾本身就是 `\`（比如断点恰好落在 `--regex '\d+\` 之类的位置），结果是：

```
--regex '\d+\ \
```

VHS 接到 `\d+\ \`，shell 看到的是字面 `\` + 空格 + `\` + EOL —— **shell 不会认 `\ \` 为续行**，整条命令分成两段，后半段以 `\` 开头进入下一行作为新命令。

field-notes.md 警告过 "two literal backslashes instead of one continuation marker" —— 同样源于这个边界。

## 调研证据

- `references/field-notes.md` "VHS Escape Rules Matter For Continuation Backslashes" 章节明文记录了反斜杠对续行的杀伤
- pyfcstm-2 中 wait-race 重灾区会话（0db8ebc6 / d1485495）多次见到用户手工 patch tape 的痕迹

## 改动方案

### 修复 1

```python
def escape_vhs_text(text: str) -> str:
    return (
        text.replace("\\", "\\\\")  # 必须最先
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace('"', '\\"')
    )
```

### 修复 2

```python
# 在 lines.append(f"{chunk} \\") 之前：
chunk = normalized[start:break_index].rstrip().rstrip("\\")
if not chunk:
    return normalized
lines.append(f"{chunk} \\")
```

### 同步修复 JS 端

`scripts/render_ttyd_scenario.js:207-268` 的 `wrapShellCommandText` 等价 patch（去末尾 `\`）。ttyd 端不走 VHS escape 但同样有续行 bug。

### 加单元测试

新增 `tests/test_escape_and_wrap.py`（如目录不存在则建）：

- `test_escape_vhs_text_preserves_literal_backslash`
- `test_wrap_strips_trailing_backslash_before_continuation`
- `test_wrap_quoted_region_break_safety`（已存在的不变区域用例补强）

## 向后兼容

不影响任何不含字面反斜杠的 scenario。包含反斜杠的 case 行为从"输出错乱"变成"输出正确"。

## 验收标准 (Codex)

```bash
codex exec '
cd terminal-capture-workflow
python -m pytest tests/test_escape_and_wrap.py -v

cat > /tmp/esc-bug.json <<JSON
{
  "name": "esc-bug",
  "cwd": "/tmp",
  "shell": ["bash", "--noprofile", "--norc", "-i"],
  "vhs": {"width":1280,"height":400,"outputs":["mp4"]},
  "steps": [
    {"action":"command","text":"echo regex='\''\\d+\\s*'\''","clear_before":true,"wait_for_text":"\\\\d\\\\+"}
  ]
}
JSON
python scripts/terminal_capture.py render vhs /tmp/esc-bug.json
ffmpeg -i .terminal-capture-output/vhs/esc-bug/esc-bug.mp4 -frames:v 1 /tmp/last.png 2>&1 | tail
# 视检 /tmp/last.png 终端最后一行应能看到原样 regex=\d+\s*，不是 \\d+\\s*
'
```
