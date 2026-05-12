# Issue 草稿索引

本目录是 `terminal-capture-workflow` 一次系统性打磨的 issue 草稿集，对应 GitHub 上的 [Tracking issue #13](https://github.com/HansBug/terminal-capture-workflow/issues/13)。子 issue 编号 #1 ~ #12 与本目录的 `NN-*.md` 严格对齐。

每份 `NN-*.md` 是一个独立 issue 的 body 草稿；落库后保留作为本地参考，也方便未来 PR 引用证据/方案。如果要再开一个独立 issue：

```bash
gh issue create --title "<标题>" --body-file docs/issues/NN-*.md --label <label>
```

## 调研结论摘要

- 真实下游使用：animedex（VHS 主力，5 个会话 / 含 40MB 单文件）、pyfcstm-2（wait race 重灾区）、pyfcstm（wrap_at_columns 诱因）、pyplantuml-bundled（GitHub PR 投递模式）、KohakuHub、12306 等。
- 复现率最高的痛点：① VHS / ttyd 的 `wait_for_text` 都受 viewport 限制；② motion 输出最后一帧太短；③ scenario 配置参数发现性差；④ Live API demo 网络抖动 / schema 漂移；⑤ scenario 可复现性每个项目各自造轮子。
- 跨源交叉验证：3 个独立 subagent 抽取的 top 痛点高度一致，结论可靠。

## 优化轨道总览

| Track | 主题 | 涉及 issue |
|---|---|---|
| A | 可发现性（文档前置） | #1 #2 |
| B | Scenario 模板和脚手架 | #5 |
| C | Wait / timing 鲁棒性 | #6 #7 |
| D | Fixture / pre-warm 原语 | #8 |
| E | 探针校验增强 | #9 |
| F | 渲染器代码 bug 修复 | #3 #4 |
| G | 多 scenario / 多格式编排 | #11 #12 |
| H | Codex / Claude TUI 录制能力 | #10 |

## 优先级与建议落地顺序

| Issue | 标题 | Track | 优先级 | 依赖 |
|---|---|---|---|---|
| [#1](https://github.com/HansBug/terminal-capture-workflow/issues/1) | 在 SKILL.md 顶部加 Scenario 参数速查表 + 引擎决策树 | A | P0 | 无 |
| [#2](https://github.com/HansBug/terminal-capture-workflow/issues/2) | 把三大常见踩坑（长输出 wait race / motion 收尾短 / WebM 不能 PR）前置到 SKILL.md | A | P0 | 无 |
| [#3](https://github.com/HansBug/terminal-capture-workflow/issues/3) | 修复 `escape_vhs_text` 漏转义 `\` + `wrap_shell_command_text` 末位续行多重转义 | F | P0 | 无 |
| [#4](https://github.com/HansBug/terminal-capture-workflow/issues/4) | ttyd 的 `wait_for_text` 从 DOM viewport 改成 xterm.js buffer | F+C | P0 | 无 |
| [#5](https://github.com/HansBug/terminal-capture-workflow/issues/5) | 新增 `init` 子命令 + `references/project-layout.md` | B | P1 | 无 |
| [#6](https://github.com/HansBug/terminal-capture-workflow/issues/6) | 新增 `wait_for_prompt` 语糖 + scenario lint | C | P1 | 无 |
| [#7](https://github.com/HansBug/terminal-capture-workflow/issues/7) | 新增 `wait_until_stable` step 字段 | C+H | P1 | #4 推荐 |
| [#8](https://github.com/HansBug/terminal-capture-workflow/issues/8) | 新增 `pre_warm` scenario 字段 + `references/fixtures-and-mocks.md` | D | P2 | 无 |
| [#9](https://github.com/HansBug/terminal-capture-workflow/issues/9) | 新增 `validate-scenario` 子命令 + final-frame 卡帧检测 | E | P2 | 无 |
| [#10](https://github.com/HansBug/terminal-capture-workflow/issues/10) | 新增 `references/recording-agent-cli.md` + Codex/Claude TUI starter scenarios | H | P1 | #7 |
| [#11](https://github.com/HansBug/terminal-capture-workflow/issues/11) | `"github-pr"` 输出预设 + 文档说明 WebM 不能 PR | G | P2 | 无 |
| [#12](https://github.com/HansBug/terminal-capture-workflow/issues/12) | `render` 子命令支持多 scenario + `--parallel` | G | P2 | 无 |

## 向后兼容约束（所有 issue 共用）

**严格 additive only**：

- 现有 scenario JSON 字段语义、默认值、输出路径**不变**
- 已提交在 animedex / pyfcstm / pyfcstm-2 / pyplantuml 等仓库里的 scenario 文件必须一行不改还能继续跑
- 所有新功能通过新字段或新子命令引入
- 任何"默认值更合理化"的诱惑都通过新字段实现，不动旧默认

## Codex 验收循环

每个 issue 末尾都附带 `验收标准 (Codex)` 节：实现完成后通过 `codex exec` 在干净环境里一键复现。验收脚本所需文件统一放 `tests/acceptance/<NN>/`（实现时落地）。

## 标签建议（创建时）

- `enhancement`：#1 #2 #5 #6 #7 #8 #9 #10 #11 #12
- `bug`：#3 #4
- `documentation`：#1 #2（兼）#10
- 优先级标签 `P0` / `P1` / `P2`
