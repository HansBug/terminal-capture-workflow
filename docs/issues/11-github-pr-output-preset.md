# [P2][Track G] 新增 `"github-pr"` 输出预设 + 文档说明 WebM 不能 PR

## 背景

GitHub `gh image` upload 拒绝 WebM 内容（返回 422 `content_type is not included in the list`）。跨多个 Codex 会话（最早 2026-04-09，最近 2026-05-09 animedex 系列）反复见到这个症状。下游用户最终的实操套路是 `"outputs": ["gif", "mp4"]`——GIF 自动循环、MP4 可以暂停。但每次都要手写两元素数组，且 `references/scenario-patterns.md` 给的例子是 `["mp4", "gif"]`（顺序）和 `["mp4", "gif", "webm"]`（多 demos），容易诱导用户加 webm 然后传不上去。

## 改动方案

### 1. 支持字符串预设

`vhs.outputs` 允许接收字符串，渲染时展开：

```python
OUTPUT_PRESETS = {
    "github-pr": ["gif", "mp4"],
    "all": ["gif", "mp4", "webm"],
    "gif-only": ["gif"],
    "mp4-only": ["mp4"],
}
```

修改 `resolve_vhs_outputs`：

```python
def resolve_vhs_outputs(cfg: dict[str, Any]) -> list[str]:
    raw = cfg.get("outputs", ["mp4"])
    if isinstance(raw, str):
        if raw not in OUTPUT_PRESETS:
            raise ValueError(f"Unknown outputs preset: {raw}. Try {sorted(OUTPUT_PRESETS)}")
        return list(OUTPUT_PRESETS[raw])
    return [str(ext).lower() for ext in raw]
```

### 2. validate-scenario 联动

`validate-scenario --lint` （依赖 #9）：

- 若 `vhs.outputs` 含 `webm` 且 scenario 名称包含 "pr" / "github" / "issue" 等关键词，info-level 提示"WebM 不能直接 PR，考虑 outputs: github-pr"
- 不强制——本地保留 WebM 是合法的

### 3. 文档同步

- `references/scenario-patterns.md` 把示例的多 demo 用法改为 `"outputs": "github-pr"` 并说明预设
- `references/field-notes.md` "Recommended Review Checklist" 加一条 "PR 投递不要带 webm"
- `SKILL.md` Scenario 参数速查表（#1）的 `vhs.outputs` 行补充"特殊值：github-pr / all / gif-only / mp4-only"

## 调研证据

- pyfcstm Codex session 原话："`gh image` content-type 白名单：GIF / PNG / MP4 都通过，**WebM 被 422 拒**（`content_type is not included in the list`）。所以 PR 里 GIF + MP4 双格式就够了：GIF 自动循环、MP4 带原生 `<video>` 控件可暂停。"
- 多个 04-09 / 04-10 / 05-09 会话见相同错误

## 向后兼容

数组形式 `["gif","mp4","webm"]` 等仍然完全支持；新增字符串语义。

## 验收标准 (Codex)

```bash
codex exec '
cat > /tmp/preset.json <<JSON
{
  "name": "preset-test",
  "cwd": "/tmp",
  "shell": ["bash","--noprofile","--norc","-i"],
  "vhs": {"width":1280,"height":400,"outputs":"github-pr"},
  "steps": [
    {"action":"command","text":"echo hi","wait_for_text":"hi"}
  ]
}
JSON
python "$HOME/.codex/skills/terminal-capture-workflow/scripts/terminal_capture.py" render vhs /tmp/preset.json
test -f .terminal-capture-output/vhs/preset-test/preset-test.gif
test -f .terminal-capture-output/vhs/preset-test/preset-test.mp4
test ! -f .terminal-capture-output/vhs/preset-test/preset-test.webm

# 验证未知预设报清楚的错
cat > /tmp/bad-preset.json <<JSON
{"name":"bad","cwd":"/tmp","shell":["bash","--noprofile","--norc","-i"],
 "vhs":{"width":1280,"height":400,"outputs":"webp-preset"},"steps":[]}
JSON
python "$HOME/.codex/skills/terminal-capture-workflow/scripts/terminal_capture.py" render vhs /tmp/bad-preset.json 2>&1 | grep "Unknown outputs preset"
'
```
