# [P0][Track A] 把三大常见踩坑前置到 SKILL.md "Common Pitfalls"

## 背景

跨 4 个项目（animedex、pyfcstm、pyfcstm-2、pyplantuml）反复踩同样三个坑。教训目前埋在 `references/field-notes.md`，新会话 / 新模型不一定会先读 references 再设计 scenario，导致同一个错误在多个项目里重演。

## 三大踩坑

### 1. VHS 与 ttyd 的 `wait_for_text` 都是 viewport-bounded

VHS 的 `Wait+Screen /pattern/` 只匹配当前可见行；ttyd 的 `waitForText` 用 `document.querySelector(".xterm-rows")?.innerText` 也只读可见 DOM。当输出超过一屏，目标行滚出 viewport，wait 永远命中不到。

**真实证据**：
- `~/.claude/projects/-home-zhangshaoang-oo-projects-pyfcstm-2/0db8ebc6-*.jsonl:27+` 原话："Wait+Screen /pattern/ 在长输出里不能等"中间某行" — 那行可能滚出 viewport 后再 wait 就 race condition 失败。改成等 prompt 回归（demo $）+ 命令尾加 `|| true` 让非零退出码也回 prompt"。

**推荐做法**：

```json
{
  "action": "command",
  "text": "long_command_with_many_lines || true",
  "wait_for_text": "demo \\$",
  "timeout_ms": 30000
}
```

或者用 `wait_for_prompt: true`（待 #6 落地后）。

### 2. Motion 输出最后一帧太短

`endHoldSeconds` 默认 2 秒。对 GIF 演示（自动循环）这通常够；但对 PR review、homepage hero、教程类视频，2 秒读不完最终终态。

**真实证据**：
- animedex `hero.tape`（位于 `wtf-projects/animedex/docs/source/_static/gifs/hero.tape`）内部最后只 `Sleep 600ms` 收尾，最终用户手工补到 `Sleep 4000ms` 才稳定。
- pyfcstm 推荐 GIF 投递 PR 时 `endHoldSeconds >= 3`，`field-notes.md` 已记但 SKILL.md 未提。

**推荐做法**：

```json
{
  "vhs": {
    "endHoldSeconds": 3
  }
}
```

经验值：教程 / hero / PR review → 3-5s；纯 loop GIF → 2s（默认）就行；演示流程总结画面 → 4-6s。

### 3. GitHub `gh image` 不接受 WebM

`gh image` upload 的 content-type 白名单包括 GIF / PNG / MP4，**不包含 WebM**。曾经因为 `"outputs": ["gif", "mp4", "webm"]` 渲染了三种，结果 WebM 提交时返回 422 `content_type is not included in the list`，浪费时间。

**真实证据**：
- 多份 Codex session（2026-04-09 ~ 2026-05-09）原文出现 `content_type is not included in the list`
- 用户在 PR 中最终统一只贴 GIF + MP4

**推荐做法**：

PR 投递用：

```json
{ "vhs": { "outputs": ["gif", "mp4"] } }
```

或者待 #11 落地后用 `"outputs": "github-pr"` 预设。

## 改动方案

在 `SKILL.md` 中插入 "Common Pitfalls" 节，紧跟 "Workflow" 之后。每条 4-6 行：症状 / 现象 / 解决 / 引用。

文末加一句指向 `references/field-notes.md` 作为深入阅读。

`references/field-notes.md`：保留现有内容，开头加一段 "Top 3 lessons see SKILL.md → Common Pitfalls"，避免双份维护。

## 向后兼容

纯文档变更。

## 验收标准 (Codex)

```bash
codex exec '阅读 ~/.codex/skills/terminal-capture-workflow/SKILL.md "Common Pitfalls" 节，回答：
1. 在长输出里 wait_for_text 为什么经常 race，应改成等什么？
2. 给 PR 投递一个 hero 演示视频，endHoldSeconds 推荐设多少？
3. 录三种格式 ["gif","mp4","webm"] 时 PR 上哪个会传不上去？
'
```
