# terminal-capture-workflow 系统性打磨追踪

## 背景

本 issue 是对 terminal-capture-workflow 的一次系统性打磨的总跟踪。

调研基于 60+ Claude session（`~/.claude/projects/`）+ 130+ Codex session（`~/.codex/sessions/`）共约半年的真实使用日志，覆盖 animedex、pyfcstm、pyfcstm-2、pyplantuml、KohakuHub、12306 等下游消费者。三个独立 subagent 抽取的 top 痛点高度一致，结论可信。

每一条子 issue 都附带"调研证据 → 改动方案 → 向后兼容声明 → Codex 一键验收脚本"五段式结构，可独立推进。

## 总原则

- **严格 additive 向后兼容**：现有 scenario JSON 字段语义、默认值、输出路径**不变**；下游 repo（animedex / pyfcstm / pyfcstm-2 / pyplantuml）里已提交的 scenario 文件必须一行不改照样跑。新功能通过新字段、新 step action、新子命令引入。
- **每条都能用 Codex 验收**：实现完成后通过 `codex exec` 在干净环境一键复现。
- **Track 划分**：A 可发现性 · B 模板/脚手架 · C Wait/timing 鲁棒性 · D Fixture/pre-warm · E 探针校验 · F 渲染器 bug 修复 · G 多 scenario/多格式编排 · H Codex/Claude TUI 录制能力。

## 任务清单

### P0（先做，零或低风险，立即收益）

- [ ] #1 [Track A] 在 SKILL.md 顶部加 Scenario 参数速查表 + 引擎决策树
- [ ] #2 [Track A] 把三大常见踩坑（长输出 wait race / motion 收尾短 / WebM 不能 PR）前置到 SKILL.md "Common Pitfalls"
- [ ] #3 [Track F] 修复 `escape_vhs_text` 漏转义 `\` + `wrap_shell_command_text` 末位续行多重转义
- [ ] #4 [Track F+C] 把 ttyd 的 `wait_for_text` 从 DOM viewport 改成 xterm.js buffer（影响 ttyd 长输出 wait 可靠性）

### P1（核心能力强化）

- [ ] #5 [Track B] 新增 `init` 子命令 + `references/project-layout.md`：把跨项目重复发明的"scenarios/ + scripts/render_*.sh"三件套官方化
- [ ] #6 [Track C] 新增 `wait_for_prompt` 语糖 + scenario lint
- [ ] #7 [Track C+H] 新增 `wait_until_stable` step 字段：解决流式 token 输出和 spinner 的截屏稳定性
- [ ] #10 [Track H] 新增 `references/recording-agent-cli.md` + Codex/Claude TUI starter scenarios：强化录制 Codex/Claude 自身的能力

### P2（质量提升）

- [ ] #8 [Track D] 新增 `pre_warm` scenario 字段 + `references/fixtures-and-mocks.md`：API-heavy demo 的网络抖动/schema 漂移解药
- [ ] #9 [Track E] 新增 `validate-scenario` 子命令 + final-frame 卡帧检测
- [ ] #11 [Track G] 新增 `"github-pr"` 输出预设 + 文档说明 WebM 不能 PR
- [ ] #12 [Track G] `render` 子命令支持多个 scenario + `--parallel`

## 推荐落地顺序

1. **第一批（P0 全部，零风险）**：#1 #2 #3 #4
2. **第二批（核心 wait/timing，解决最高频痛点）**：#6 #7
3. **第三批（新用户路径打通）**：#5 #10
4. **第四批（剩余 P2）**：#8 #9 #11 #12

依赖关系：
- #7 强烈建议在 #4 之后做（buffer 检索是稳定 stable check 的前提）
- #10 的 starter scenarios 用 #6 / #7 / #8 的新字段，建议这三条先动
- #6 的 lint 规则依赖 #9 的 validate-scenario 子命令落地

## 验收闭环

每条子 issue 末尾都有"验收标准 (Codex)"节，包含可粘贴的 `codex exec` 脚本。建议在每条 PR 合并前在干净 shell 跑一次该脚本，并把输出粘进 PR 评论。

## 草稿位置

每个 issue 的完整草稿同步保留在 `docs/issues/NN-*.md`，便于本地校对和未来 PR 引用：

- [`docs/issues/README.md`](https://github.com/HansBug/terminal-capture-workflow/blob/main/docs/issues/README.md) — 索引与原则总览
- [`docs/issues/01-*.md`](https://github.com/HansBug/terminal-capture-workflow/blob/main/docs/issues/01-skill-md-quick-reference-and-engine-decision-tree.md) ~ [`docs/issues/12-*.md`](https://github.com/HansBug/terminal-capture-workflow/blob/main/docs/issues/12-render-multi-scenario-and-parallel.md) — 每条子 issue 的本地草稿

## 调研附录

下游真实痛点的代表性引用（已脱敏）：

- pyfcstm-2 关于 wait race 的原话："Wait+Screen `/pattern/` 在长输出里**不能等"中间某行"** — 那行可能滚出 viewport 后再 wait 就 race condition 失败。改成等 prompt 回归（`demo $`）+ 命令尾加 `|| true` 让非零退出码也回 prompt，这一类录制就稳了。"
- pyfcstm 关于 PR 投递的原话："`gh image` content-type 白名单：GIF / PNG / MP4 都通过，**WebM 被 422 拒**（`content_type is not included in the list`）。"
- pyplantuml 关于复现路径的原话："改成 `docs/cli-demo.{setup.sh,hello.puml}` 提交进仓库，配 `scripts/render_cli_demo.sh` 一键再生。"
- 用户在本次打磨的目标："强化针对 codex 和 claude 这些东西的录制能力"（→ Track H / issue #10）。

## 后续

本 issue 用于跟踪所有 12 条子 issue 的状态。每个子 issue 关闭后，回这里勾掉对应 box。
