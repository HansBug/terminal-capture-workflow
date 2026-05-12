# [P0][Track F+C] ttyd `wait_for_text` 从 DOM viewport 改成 xterm.js buffer

## 背景

跨项目调研里"wait 命中不到 / timeout"是出现频率最高的痛点。`references/field-notes.md` 把责任归到 VHS 的 `Wait+Screen` 是 viewport-bounded，但**实际上 ttyd 端也有同样的 bug**，文档和代码都没明说。

## 现状代码

`scripts/render_ttyd_scenario.js:113-122`：

```js
async function waitForText(page, pattern, timeoutMs = 10000, flags = "m") {
  await page.waitForFunction(
    ({ source, regexFlags }) => {
      const text = document.querySelector(".xterm-rows")?.innerText || "";
      return new RegExp(source, regexFlags).test(text);
    },
    { source: pattern, regexFlags: flags },
    { timeout: timeoutMs },
  );
}
```

xterm.js 的 `.xterm-rows` DOM 只渲染当前可见行（terminal viewport），scrollback 不在 DOM 里。一旦命令输出超过一屏（终端高 50 行 ≈ 50 行输出），目标 pattern 滚出 viewport 后 `waitForText` 永远命中不到，最终 timeout。

## 调研证据

- `~/.claude/projects/-home-zhangshaoang-oo-projects-pyfcstm-2/0db8ebc6-*.jsonl:27+` 用户原话："Wait+Screen /pattern/ 在长输出里不能等"中间某行"… 那行可能滚出 viewport 后再 wait 就 race condition 失败"
- animedex 完全跳过 wait，全用固定 sleep；侧面验证 wait 不可靠时模型会绕开它
- `references/field-notes.md` "Prefer Stable Wait Targets Over Final-Frame Guesses" 节给的解决思路（等 summary 行 / 等 prompt 回归）实际上是 viewport-bounded 的工作绕过法，不是根因修复

## 改动方案

### 改动 1：用 xterm.js Buffer API 取代 DOM 查询

xterm.js 暴露 `term.buffer.active.length`（含 scrollback）和 `term.buffer.active.getLine(i).translateToString(false)`。需要从 ttyd 客户端把 `term` 实例挂到 `window`。

新 waitForText 实现：

```js
async function waitForText(page, pattern, timeoutMs = 10000, flags = "m") {
  await page.waitForFunction(
    ({ source, regexFlags }) => {
      const term = window.term || window.__ttydTerm;
      if (!term || !term.buffer || !term.buffer.active) {
        // fallback：保留 DOM 模式以防 xterm 实例还没挂载
        const text = document.querySelector(".xterm-rows")?.innerText || "";
        return new RegExp(source, regexFlags).test(text);
      }
      const buf = term.buffer.active;
      let text = "";
      for (let i = 0; i < buf.length; i += 1) {
        const line = buf.getLine(i);
        if (!line) continue;
        text += line.translateToString(false) + "\n";
      }
      return new RegExp(source, regexFlags).test(text);
    },
    { source: pattern, regexFlags: flags },
    { timeout: timeoutMs },
  );
}
```

ttyd 默认会把 xterm.js 的 `term` 暴露到 `window.term`；需要确认主流 ttyd 版本（>=1.7.x）行为，做兼容判断。

### 改动 2：把 ttyd 启动时的 scrollback 调大

`scripts/render_ttyd_scenario.js:420` 附近构造 `clientOptions`：

```js
clientOptions.push(["scrollback", String(ttydConfig.scrollback || 5000)]);
```

scenario 顶层新增可选 `ttyd.scrollback`，默认 5000（够装 100 屏）。

### 改动 3：VHS 端文档说明

VHS 自身确实只能等 viewport，目前无法绕过。所以：

- 修复 ttyd 后，**ttyd 是更可靠的 wait 引擎**，文档需说明
- VHS 上还是推荐"等 prompt 回归"或"等 summary 行"（field-notes.md 已写）
- 引擎决策树（#1）加一条："命令输出可能超过一屏 → 优先 ttyd"

### 改动 4：field-notes.md 修订

把"Prefer Stable Wait Targets"节改成两段：

- VHS：仍然推荐 stable wait target
- ttyd（修复后）：可以等任意行，包括滚出 viewport 的行

## 向后兼容

`wait_for_text` API 不变。**行为变化方向是"原本 timeout 的现在会成功"**——属于 strict bugfix。

## 验收标准 (Codex)

```bash
codex exec '
cd terminal-capture-workflow

cat > /tmp/scrollback-test.json <<JSON
{
  "name": "scrollback-test",
  "cwd": "/tmp",
  "shell": ["bash","--noprofile","--norc","-i"],
  "ttyd": {"viewport":{"width":1200,"height":400}},
  "steps": [
    {"action":"command","text":"for i in $(seq 1 200); do echo line $i; done; echo MARKER_END","clear_before":true,"wait_for_text":"MARKER_END","timeout_ms":15000,"result_shot":"end"}
  ]
}
JSON

python scripts/terminal_capture.py render ttyd /tmp/scrollback-test.json
# 修复前：超时 timeout
# 修复后：拿到 end.png，截图里能看到 line 199 line 200 MARKER_END（viewport 显示的是最后几行）
ls .terminal-capture-output/ttyd/scrollback-test/end.png
'
```
