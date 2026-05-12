# [P1][Track C+H] 新增 `wait_until_stable` step 字段

## 背景

`wait_for_text` 的命中策略是"pattern 一旦出现就立刻 resolve"。这对一次性输出的命令足够，但有两类常见场景会拍到"半截画面"：

1. **流式 token 输出**：codex / claude / ollama / OpenAI CLI 等 LLM 工具是流式吐 token，pattern 命中瞬间画面还在变。
2. **带 spinner 的命令**：`npm install` / `pip install` / `cargo build` 等用 `⣾⣽⣻⢿` 这类 braille spinner，输出在持续刷新，截图随机帧。

跨项目调研里很多 `Sleep 1500ms` / `Sleep 1800ms` 是为了等这种情况稳定下来（animedex hero.tape 是典型）；但 sleep 是猜值，慢就慢得不必要、快就拍残。

## 改动方案

### 新字段（step 级别）

```json
{
  "action": "wait_for_text",
  "pattern": "Done.",
  "timeout_ms": 15000,
  "wait_until_stable": { "ms": 800 }
}
```

或在 `command` step 内：

```json
{
  "action": "command",
  "text": "codex exec '简单解释 RAG'",
  "wait_for_text": "▎",  // codex 输出结尾常见行起始符
  "timeout_ms": 60000,
  "wait_until_stable": { "ms": 1200 },
  "result_shot": "codex-final"
}
```

### 语义

`wait_until_stable.ms` 表示：pattern 命中之后，再连续观察 `ms` 毫秒——如果期间 buffer 没有新增字符，认为画面稳定，返回；如果有变化，重置计时再观察。可设置最大 wall-clock cap（用 step 的 `timeout_ms` 即可，超出后强制 resolve 并打 warning）。

### ttyd 实现

接 #4 的 buffer-based wait，加一个 length 比较循环：

```js
async function waitUntilStable(page, pattern, timeoutMs, stableMs, flags = "m") {
  await waitForText(page, pattern, timeoutMs, flags);  // 先命中
  const start = Date.now();
  let lastLen = await getBufferLength(page);
  let stableStart = Date.now();
  while (Date.now() - start < timeoutMs) {
    await sleep(150);
    const cur = await getBufferLength(page);
    if (cur !== lastLen) {
      lastLen = cur;
      stableStart = Date.now();
      continue;
    }
    if (Date.now() - stableStart >= stableMs) return;
  }
  // 强制返回 + warning（实际 logger 处理）
}
```

### VHS 实现

VHS tape 语法本身不支持"等到稳定再继续"。两种处理：

1. **简化**：在 tape 里替换为 `Wait+Screen /pattern/` + `Sleep <stableMs>ms`——把不可观察等价为固定 sleep。这虽然不是真的"等到稳定"，但比纯猜的 sleep 好（至少在 pattern 命中后才开始计时）。
2. **文档说明**：明确告知 VHS 端 `wait_until_stable` 是降级实现；要求强稳定性请用 ttyd 引擎。

### CLI / scenario lint 联动

`validate-scenario --lint`（#9）加一条 info-level 规则：当 scenario 中出现 `codex` / `claude` / `ollama` 命令但没设 `wait_until_stable`，提示建议设。

## 调研证据

- animedex hero.tape 全部用固定 `Sleep 600-1800ms`，多次重渲才稳定
- 用户明确诉求："这一次还需要强化针对 codex 和 claude 这些东西的录制能力"

## 向后兼容

新增字段；现有 scenario 不受影响。

## 验收标准 (Codex)

```bash
codex exec '
cat > /tmp/spinner.json <<JSON
{
  "name": "spinner-stable",
  "cwd": "/tmp",
  "shell": ["bash","--noprofile","--norc","-i"],
  "ttyd": {"viewport":{"width":1200,"height":400}},
  "steps": [
    {
      "action": "command",
      "text": "(for c in / - \\\\ \\\"|\\\"; do printf \"\\r%s working...\" \"$c\"; sleep 0.15; done; printf \"\\rdone.\\n\")",
      "clear_before": true,
      "wait_for_text": "done\\.",
      "wait_until_stable": {"ms": 500},
      "timeout_ms": 10000,
      "result_shot": "after-stable"
    }
  ]
}
JSON
python "$HOME/.codex/skills/terminal-capture-workflow/scripts/terminal_capture.py" render ttyd /tmp/spinner.json
# after-stable.png 应稳定显示 "done."，没有 spinner 残影
ls .terminal-capture-output/ttyd/spinner-stable/after-stable.png
'
```
