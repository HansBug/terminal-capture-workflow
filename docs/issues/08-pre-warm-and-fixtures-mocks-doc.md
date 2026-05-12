# [P2][Track D] 新增 `pre_warm` scenario 字段 + `references/fixtures-and-mocks.md`

## 背景

API-heavy 的 CLI demo（animedex 最典型）渲染时常遇到三类问题：

1. **rate limit**：连续录 4 个 backend tape，AnimeChan 等服务 429。
2. **冷启动慢**：第一次拉某 endpoint 比稳定后慢 2-3 倍，导致 wait 命中时间漂移。
3. **schema 漂移**：第三方 API 字段名变更（animedex `trace.gif` 用 `.anilist.title.romaji` 渲完才发现真实 schema 是 `.anilist_title.romaji`，整段重录）。

用户在 animedex 里自己造了 fixture-cache pre-warm 工具（隐藏阶段先把缓存喂热再开始可见录制），但 skill 没有原语支持，导致每个 API-heavy 项目都要重造一遍。

## 改动方案

### 1. Scenario 顶层新增字段 `pre_warm`

```json
{
  "name": "anilist-demo",
  "pre_warm": [
    { "action": "command", "text": "bash scripts/prefetch_fixtures.sh", "timeout_ms": 30000 },
    { "action": "command", "text": "export HTTP_PROXY=http://127.0.0.1:8080", "wait_for_prompt": true }
  ],
  "steps": [
    ...
  ]
}
```

`pre_warm` 元素结构和 `steps` 子集相同（支持 `command` / `type` / `paste` / `press` / `sleep` / `wait_for_text` / `wait_for_prompt` / `input`）；但 **`screenshot` 在 pre_warm 中无效**（lint warning）。

### 2. 实现策略

- **VHS**：渲染前，先把 `pre_warm` 段当作 Hide → ... → Show 的隐藏前缀注入到 tape 顶部。视频里不可见。
- **ttyd**：直接执行 `pre_warm` 步骤，但 `screenshot`/`typed_shot`/`result_shot` 全部跳过 + lint warning。

### 3. 不强制依赖任何 fixture 库

`pre_warm` 自身只是"能跑任意命令"。具体怎么 mock / 怎么 prefetch，留给用户在 `scripts/` 写脚本。但配套文档要给套路。

### 4. 新增 `references/fixtures-and-mocks.md`

中文。三套常见模式：

#### 模式 A：fixture cache 预热

适合：API 响应可重放、自家工具有缓存层（如 animedex）

```bash
# scripts/prefetch_fixtures.sh
animedex anilist show 154587 --jq '.title.romaji' >/dev/null
animedex jikan show 52991 --jq '.data.title' >/dev/null
animedex nekos categories --json --jq '.[:5]' >/dev/null
```

scenario 里：

```json
{ "pre_warm": [{ "action": "command", "text": "bash scripts/prefetch_fixtures.sh", "wait_for_prompt": true, "timeout_ms": 60000 }] }
```

#### 模式 B：本地 mock server

适合：API 不稳定、需要确定性响应

推荐工具：`mockoon-cli`、`prism`、`json-server`、`python -m http.server` + 静态 fixture 文件。

```bash
# scripts/start_mock.sh
prism mock api-spec.yaml --port 4010 &
echo $! > .mock.pid
```

scenario：

```json
{
  "pre_warm": [
    { "action": "command", "text": "bash scripts/start_mock.sh && export API_BASE=http://localhost:4010", "wait_for_prompt": true }
  ]
}
```

附 teardown 提示（用户自行写）。

#### 模式 C：HTTP VCR / 录制重放

适合：完整 HTTP 会话需要重放

推荐：`vcrpy`（Python）、`nock`（Node）、`pytest-recording`。在源代码里启用 VCR；scenario 不需要特殊处理。

### 5. SKILL.md 同步

"Workflow" 之后加一条：

> 如果命令依赖 live API 或网络资源，先看 `references/fixtures-and-mocks.md` 选 mock 策略，然后把准备步骤放进 scenario 的 `pre_warm`。

## 调研证据

- animedex Codex 5/9 session（`~/.codex/sessions/2026/05/09/rollout-2026-05-09T10-49-07-*.jsonl`，47MB）多处 429 + 用户造 quote-cache 预热
- pyplantuml 需 `pip install -e .` 预先安装

## 向后兼容

新增字段；未写 `pre_warm` 的 scenario 行为不变。

## 验收标准 (Codex)

```bash
codex exec '
mkdir -p /tmp/prewarm-test && cd /tmp/prewarm-test
cat > prefetch.sh <<SH
#!/usr/bin/env bash
echo "warming up..."
sleep 0.3
echo "done warmup"
SH
chmod +x prefetch.sh

cat > scenario.json <<JSON
{
  "name": "prewarm-demo",
  "cwd": "/tmp/prewarm-test",
  "shell": ["bash","--noprofile","--norc","-i"],
  "vhs": {"width":1280,"height":400,"outputs":["mp4"]},
  "pre_warm": [
    {"action":"command","text":"./prefetch.sh","wait_for_prompt":true,"timeout_ms":5000}
  ],
  "steps": [
    {"action":"command","text":"echo visible","clear_before":true,"wait_for_text":"visible","result_shot":"after"}
  ]
}
JSON

python "$HOME/.codex/skills/terminal-capture-workflow/scripts/terminal_capture.py" render vhs scenario.json
# 视频里应只看到 echo visible，看不到 warming up
ffmpeg -i .terminal-capture-output/vhs/prewarm-demo/prewarm-demo.mp4 -frames:v 1 /tmp/first.png 2>&1 | tail
'
```
