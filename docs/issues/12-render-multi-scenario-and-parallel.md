# [P2][Track G] `render` 子命令支持多个 scenario + `--parallel`

## 背景

跨项目调研里见到的批量渲染模式：

- **animedex**：一次性渲染 `hero.tape` + `quickstart.tape` + `anilist.tape` + `jikan.tape` + `trace.tape` + `nekos.tape` 共 6 个。模型写 for 循环串行，每个 60s timeout 累计上分钟级。
- **pyfcstm**：4 个 scenario（`01_notpatched_static_check` / `02_notpatched_validate` / `03_patched_static_check` / `04_patched_validate`），同样串行。
- **pyplantuml**：单 scenario，但同一个会话里 PR 改了后需要重渲——手动重跑 render 命令。

当前 `render` 子命令只接受 **一个** scenario 路径。批量场景下用户每次都写 shell for 循环。可改进点：

1. 接受多个 scenario 路径
2. 提供 `--parallel N`，独立子进程并发渲染（每个进程独立 ttyd 端口 / 独立 VHS 进程）
3. `--continue-on-error` 让单 scenario 失败不中断整批

## 改动方案

### 1. CLI 签名

```bash
python scripts/terminal_capture.py render <engine> <scenario> [<scenario>...] \
    [--output-root <dir>] \
    [--cwd <dir>] \
    [--parallel N] \
    [--continue-on-error]
```

- 单 scenario：行为完全不变（向后兼容）
- 多 scenario：每个都按顺序处理；`--parallel N` (N>=2) 时用 `concurrent.futures.ProcessPoolExecutor` 并发
- `--continue-on-error`：遇到 scenario 失败仍跑剩下的，最后汇总错误并 exit 非零

### 2. 并发安全考虑

- **ttyd 端口冲突**：现有 `render_ttyd_scenario.js` 用 `15000 + (process.pid % 10000)` 选端口。并行进程的 PID 不同，理论上端口不会冲突；保险起见加端口在用检测和重试一两次。
- **VHS 文件锁**：每个 scenario 写自己 tape 到 `output_root/generated/<name>.tape`，名字唯一，无冲突。
- **共享 output 目录**：每个 scenario 输出到 `output_root/<engine>/<scenario_name>/`，目录唯一。
- **stdout / stderr 交错**：并行时输出可能交错；用 prefix `[<scenario_name>] ` 标注每行（或先在内存里累积、按 scenario 顺序冲刷）。

### 3. 默认行为

`--parallel` 默认为 1（串行）。多 scenario 但不开 parallel 时按命令行顺序依次处理，方便调试。

### 4. 失败汇总输出

```
Rendered 5/6 scenarios.
Failed:
  - scenarios/trace.json (subprocess exit 1)
    last output:
      Wait+Screen timeout after 30000ms
```

退出码：

- 全部成功 → 0
- 任一失败 + 没 `--continue-on-error` → 立刻退出，返回失败 scenario 的 exit code
- 任一失败 + 有 `--continue-on-error` → 跑完所有再退，返回 1

### 5. 配合 init 模板

`init` 生成的 `scripts/render_<name>.sh` 仍是单 scenario；新增 `scripts/render_all.sh`（如检测到 `scenarios/*.json` 多于一个）：

```bash
#!/usr/bin/env bash
set -euo pipefail
SKILL_ROOT="${SKILL_ROOT:-$HOME/.claude/skills/terminal-capture-workflow}"
cd "$(dirname "$0")/.."
python "$SKILL_ROOT/scripts/terminal_capture.py" render vhs scenarios/*.json --parallel 2 --continue-on-error
```

## 调研证据

- animedex 多次见到 `for tape in scenarios/*.tape; do vhs "$tape"; done` 模式
- pyfcstm 4 段 scenario 串行渲染耗时 user 手动等待

## 向后兼容

单 scenario 用法完全不变；新 flag 都是可选。

## 验收标准 (Codex)

```bash
codex exec '
mkdir -p /tmp/multi-render && cd /tmp/multi-render
cat > scenarios/a.json <<JSON
{"name":"a","cwd":"/tmp/multi-render","shell":["bash","--noprofile","--norc","-i"],
 "vhs":{"width":1024,"height":300,"outputs":["mp4"]},
 "steps":[{"action":"command","text":"echo A","wait_for_text":"A"}]}
JSON
cat > scenarios/b.json <<JSON
{"name":"b","cwd":"/tmp/multi-render","shell":["bash","--noprofile","--norc","-i"],
 "vhs":{"width":1024,"height":300,"outputs":["mp4"]},
 "steps":[{"action":"command","text":"echo B","wait_for_text":"B"}]}
JSON
mkdir -p scenarios && mv a.json b.json scenarios/

time python "$HOME/.codex/skills/terminal-capture-workflow/scripts/terminal_capture.py" render vhs scenarios/a.json scenarios/b.json --parallel 2
test -f .terminal-capture-output/vhs/a/a.mp4
test -f .terminal-capture-output/vhs/b/b.mp4

# 故意失败 + continue-on-error
cat > scenarios/bad.json <<JSON
{"name":"bad","cwd":"/tmp/multi-render","shell":["bash","--noprofile","--norc","-i"],
 "vhs":{"width":1024,"height":300,"outputs":["mp4"]},
 "steps":[{"action":"command","text":"sleep 60","wait_for_text":"never","timeout_ms":2000}]}
JSON
python "$HOME/.codex/skills/terminal-capture-workflow/scripts/terminal_capture.py" render vhs scenarios/a.json scenarios/bad.json scenarios/b.json --continue-on-error 2>&1 | tee /tmp/log
grep "Failed" /tmp/log
test -f .terminal-capture-output/vhs/b/b.mp4  # b 仍要渲染
'
```
