# [P0][Track A] 在 SKILL.md 顶部加 Scenario 参数速查表 + 引擎决策树

## 背景

跨项目调研显示，模型在初次为一个项目设计 scenario 时，频繁出现"渲染失败 → 翻 `references/field-notes.md` → 找到 `wrap_at_columns` → 重渲"这种 2-3 轮才稳的模式。问题根因是 SKILL.md 只描述工作流，没有把可调参数集中暴露出来。

参数现在散落在：

- `references/scenario-patterns.md` 顶部 "Shared Structure" 示例
- `references/field-notes.md` 中夹叙夹议提到 `wrap_at_columns` / `prompt_columns`
- `scripts/terminal_capture.py` 函数 `build_vhs_tape` 和 `wrap_shell_command_text` 默认值

涉及但不易发现的参数（不完全枚举）：

- `ttyd.viewport.{width,height,deviceScaleFactor}`、`ttyd.fontSize`、`ttyd.typingDelayMs`、`ttyd.theme`、`ttyd.rendererType`
- `vhs.{width,height,fontSize,padding,windowBar,borderRadius,theme,typingSpeed,framerate,playbackSpeed,waitTimeout,outputs}`
- `vhs.endHoldSeconds` / `vhs.endHoldMs`
- `screenshots.{autocrop,padding}`
- step 级别：`wrap_at_columns` / `wrap_indent` / `prompt_columns` / `continuation_prompt_columns` / `typed_shot` / `result_shot` / `result_delay_ms` / `timeout_ms` / `clear_before` / `pattern_by_engine` / `wait_for_text_by_engine`

引擎选择目前也只有散落的"prefer ttyd for ... prefer vhs for ..." 句子，没有决策树。

## 调研证据

- pyfcstm 系列大量使用 `wrap_at_columns: 150` / `prompt_columns: 17`；写法是从 `references/field-notes.md` 复制过去的，但 SKILL.md 没有直接指引。
- animedex `hero.tape` 完全没用任何 wait 字段，全靠固定 `Sleep`，重渲多次后才稳定（`5054.. animedex .. e726ad13-*.jsonl` 多处）。
- pyplantuml 用户原话："改成 `docs/cli-demo.{setup.sh,hello.puml}` 提交进仓库，配 `scripts/render_cli_demo.sh` 一键再生" —— 显示他在自己摸索约定，skill 未提供。

## 改动方案

在 `SKILL.md` 现有 "Workflow" 节之前插入两节：

### 1. Scenario 参数速查表

按"作用域 / 字段 / 默认值 / 何时调整"四列展示。例：

```
作用域      字段                          默认          何时调整
顶层        cwd                           scenario 同目录  跨目录引用资源
ttyd        viewport.width                1400           需要更宽终端
ttyd        viewport.height               560            需要更高终端
ttyd        viewport.deviceScaleFactor    2              输出图过糊或过大时
vhs         width                         1280           匹配 ttyd 视宽
vhs         height                        760            匹配 ttyd 视高
vhs         endHoldSeconds                2              motion 最后一帧需要更长可读时间
vhs         outputs                       ["mp4"]        需要 gif/webm 或多格式
screenshots autocrop                      true           需要原图边距
step        wrap_at_columns               未启用         长命令在窄终端覆盖前一行
step        prompt_columns                0              wrap_at_columns 已开启且 PS1 较长
step        timeout_ms                    10000          慢命令（solver/网络）
...
```

### 2. 引擎选择决策树

```
你要的产物是？
├── 单张或多张静态 PNG → 优先 ttyd
│   ├── 命令含多修饰符特殊键（ctrl+shift+left 等）→ 必须 ttyd
│   └── ttyd 环境缺失 → 退化用 vhs Screenshot 步骤
├── GIF / MP4 / WebM 动图 → 必须 vhs
│   ├── 同时要静态图 → engine: all
│   └── 投递到 GitHub PR → 配 outputs: "github-pr"（见 #11）
└── 录制 codex / claude 这类 TUI agent → vhs + wait_until_stable（见 #10）
```

同步：

- `references/scenario-patterns.md` 在顶部 "Shared Structure" 块加锚点链接，避免双份维护
- `README.md` / `README_zh.md` 加一行引用速查表的位置

## 向后兼容

纯文档变更，零代码风险。

## 验收标准 (Codex)

```bash
codex exec '在干净环境读 ~/.codex/skills/terminal-capture-workflow/SKILL.md，回答：
1. wrap_at_columns 的默认值和"何时启用"是什么？
2. 如果只需要 GitHub PR 用的两种 motion 输出，应选哪个引擎、用哪个 outputs 预设？
3. 录制一个带 spinner 的 TUI agent 时，速查表里建议同时调高哪两个参数？
'
```

预期答案均能在 SKILL.md 单页内找到，无需翻 references。
