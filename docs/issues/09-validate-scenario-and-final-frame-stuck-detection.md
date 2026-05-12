# [P2][Track E] 新增 `validate-scenario` 子命令 + final-frame 卡帧检测

## 背景

两个独立但相关的 QA 痛点：

### A. Scenario 拼写错误悄悄被吃掉

`load_scenario` 只 `json.loads` 然后按需取字段。未识别字段（`typo` 之类）默默忽略；不合法的 enum 值（如 `action: "commnd"`）在渲染时才报。下游：

- pyfcstm-2 早期 scenario 写 `wait_for_text_by_engin` 漏 `e`，跑出来"wait 0 秒立刻截屏"
- animedex tape 写 `Sleep 1.5s` （正确）vs `Sleep 1500ms` 行为一致但 lint 时机不一

### B. 最终画面卡帧 / 空白没人检测

`probe-media` 现在只给 duration / fps / resolution。但 motion 输出最常见的问题是：

- 最终画面是空黑屏（脚本意外退出）
- 最终画面卡了一帧但内容不全（pattern 命中过早）
- spinner 残影（见 #7）

`extract-frames` 需要用户手动给 timestamp；如果不知道"最后稳定画面"在哪一秒，就要先 probe-media 再凭感觉填——多个会话里看到 2-3 轮才找到对的时间点。

## 改动方案

### 1. 新增子命令 `validate-scenario`

```bash
python scripts/terminal_capture.py validate-scenario <path> [--lint] [--strict]
```

- 默认：JSON schema validation（用 `jsonschema` 库或手写）。schema 在 `references/scenario.schema.json`。
- `--lint`：额外跑 lint 规则（含 #6 列的 L01-L06）
- `--strict`：把所有 warning 视为 error，CI 友好

schema 关键约束：

- 顶层必须有 `name`、`steps`；`steps` 是数组
- `vhs.outputs` 元素须为 `gif` / `mp4` / `webm`（或预设 `"github-pr"` / `"all"`，依赖 #11）
- 每个 `step.action` 必须在白名单：`sleep`/`type`/`paste`/`press`/`input`/`wait_for_text`/`wait_for_prompt`/`screenshot`/`command`/`hide`/`show`/`raw_vhs`
- 互斥字段：同 step 不能既 `pattern` 又 `pattern_by_engine`（已隐含但需 lint）
- `screenshot.name` 全局唯一

### 2. `probe-media` 增强

加 `--final-frame-check`：抽最后 `N`（默认 30）帧，逐帧 SSIM。返回：

```json
{
  "duration_seconds": 8.5,
  "width": 1280,
  "height": 760,
  "fps": 30.0,
  "codec": "h264",
  "final_frame": {
    "stable_for_seconds": 1.8,
    "ssim_min_in_window": 0.998,
    "stuck": false,
    "blank": false
  }
}
```

- `stuck`：最后 N 帧 SSIM > 0.999 且 stable_for_seconds >= 1.0 —— 通常合理（最终静止画面）
- `blank`：最后帧像素平均亮度 < 阈值（接近全黑）—— 警示
- `stable_for_seconds`：最后多少秒一直保持稳定

这给用户一个"录得对不对"的二级信号。

### 3. `extract-frames` 增强

加 `--auto-final`：

```bash
python scripts/terminal_capture.py extract-frames demo.mp4 --auto-final
```

自动找"最后一个非空、稳定的帧"前 200ms 抽一张。等同于：

```bash
python scripts/terminal_capture.py probe-media demo.mp4 --final-frame-check
# 算出 stable_for_seconds → 时间戳 = duration - stable_for_seconds + 0.2
python scripts/terminal_capture.py extract-frames demo.mp4 --times <t>
```

### 4. 依赖

`probe-media --final-frame-check` 需要 SSIM 计算。最小依赖：

- 用 `ffmpeg` 的 `select` + `metadata=print` 算出像素差（不引入新 python 包）
- 或者用 Pillow（已可选依赖）做帧间像素 diff——非 SSIM 但够用

推荐方案 1，避免新依赖。

## 调研证据

- animedex 用 extract-frames 验"最后一帧" 多次 retry
- pyfcstm-2 早期 scenario typo 经过半小时才发现 wait 失效

## 向后兼容

新增子命令 / 新增 flag；旧用法不变。

## 验收标准 (Codex)

```bash
codex exec '
# A. validate-scenario
cat > /tmp/bad-scenario.json <<JSON
{
  "name": "bad-demo",
  "steps": [
    {"action": "commnd", "text": "echo x"},
    {"action": "screenshot", "name": "shot"},
    {"action": "screenshot", "name": "shot"}
  ]
}
JSON
python "$HOME/.codex/skills/terminal-capture-workflow/scripts/terminal_capture.py" validate-scenario /tmp/bad-scenario.json --lint --strict 2>&1
# 应报：action 不在白名单、screenshot.name 重复

# B. final-frame check
cat > /tmp/blank-tail.json <<JSON
{
  "name": "blank-tail",
  "cwd": "/tmp",
  "shell": ["bash","--noprofile","--norc","-i"],
  "vhs": {"width":1280,"height":400,"outputs":["mp4"]},
  "steps": [
    {"action":"command","text":"echo visible","wait_for_text":"visible"},
    {"action":"sleep","ms":1500}
  ]
}
JSON
python "$HOME/.codex/skills/terminal-capture-workflow/scripts/terminal_capture.py" render vhs /tmp/blank-tail.json
python "$HOME/.codex/skills/terminal-capture-workflow/scripts/terminal_capture.py" probe-media .terminal-capture-output/vhs/blank-tail/blank-tail.mp4 --final-frame-check
# 输出应含 final_frame.stable_for_seconds > 1
python "$HOME/.codex/skills/terminal-capture-workflow/scripts/terminal_capture.py" extract-frames .terminal-capture-output/vhs/blank-tail/blank-tail.mp4 --auto-final
'
```
