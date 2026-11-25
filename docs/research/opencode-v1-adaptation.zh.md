# OpenCode v1 适配需求与事实

日期：2026-11-25。从主线 `bb24efe`（VeriPower 0.2.10）建立 `opencode-v1` 分支，
工作区为 `/home/mhc/veripower-opencode-v1`。本机 OpenCode 为 `1.19.0`。

## 已确定的需求

- 支持 OpenCode 1.19.0，采用独立 v1 分支；主线保持 v2。
- 参考当前 Claude Code、Codex、DSH 和 OpenCode v2 的职责分工。历史 v1 实现仅作参考。
- 共享 kernel、skills 及工程判断职责保持一致，适配负责原生技能接入和工具说明。
- 使用宿主的独立后台执行、完成信息和权限机制。
- 模型参数由宿主配置，输出上限不进入 VeriPower 的实现或安装要求。
- 后续同步和维护有实际需要时再讨论，不预设支持期限或更新限制。

职责依据见[架构](../ARCHITECTURE.md)和 [design-flow](../../skills/design-flow/SKILL.md)。
适配对照当前 [Claude Code](../../.claude/README.md)、[Codex](../../.codex-plugin/README.md)、
[DSH](../../.dsh/README.md)及主线 `bb24efe` 的 OpenCode v2：

| 作用 | 其他适配的做法 | OpenCode 1.19.0 的选择 |
|---|---|---|
| 安装与技能发现 | Claude/Codex manifest、DSH skill provider、v2 skill registry | 单层插件入口、包的 server export、原生 skills.paths |
| 父子会话取得执行说明 | Claude/Codex 启动 hooks；DSH/v2 系统上下文 | system transform，父子会话均覆盖 |
| 独立执行和收集 | 各宿主原生后台执行器与等待/完成机制 | task 后台执行、原生完成通知、kernel wake/reap |
| 启动后继续调度 | 共享 design-flow；Claude/DSH 工具后提醒、v2 历史上下文提醒 | 原生后台 task 结果追加条件性提醒 |
| 命令与权限 | 由宿主执行、审批和取消 | bash 与宿主权限，不改权限配置 |
| 更新、移除和恢复 | 各平台安装指南说明实际生命周期 | 检查加载路径、新会话发现和取消后显式恢复 |

其他适配的命令正则不构成 v1 上正确识别的证据；本次已用实际失败写法核查。
删改前先核对组件的作用和引入依据，再对照当前各平台及 OpenCode 原生能力。
保留必要行为，设计简洁；不增加兜底、降级、向后兼容或无消费者的字段和契约。
验证须覆盖具体功能是否生效，完整流程通过不能替代这一检查。

## 已确认的宿主接口

v1 使用 `{ id, server }` 插件入口，`config.skills.paths` 注册技能，system transform
向父子会话提供执行说明。技能用裸名加载，后台执行器使用原生 `task`，命令使用 `bash`。
后台能力需要 `OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS=true`。

本地自动发现只扫描 `.opencode/plugin(s)/*.{ts,js}`，因此入口采用单层文件。
显式加载目录或包时，宿主读取 `exports["./server"]`。实现与用法见
[OpenCode README](../../.opencode/README.md)。

宿主源码依据固定到 v1.19.0：
[插件接口](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/plugin/src/index.ts)、
[技能发现](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/opencode/src/skill/index.ts)、
[task](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/opencode/src/tool/task.ts)、
[插件发现](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/opencode/src/config/plugin.ts)。

## 实施与验证

初版适配 `2ed6c4a` 通过原生接口检查和真实小模块全部八个阶段，closing 为 DONE，
并记录实验 signoff。审视发现，原先按 shell 文本和整个 stdout 识别 dispatch 的提醒
没有覆盖变量调用和复合命令。现改为在原生后台 task 启动后提供调度提醒，使用宿主
已有的 background 标志；共享 design-flow 和 kernel 仍负责调度与收集。
提醒的引入依据见 `aa86ba6`：长会话中模型可能漏掉下一次调度查询，损失并发；启动
执行器不能使提醒消失。当前提醒放在原生启动结果之后，直接覆盖这个决策节点。
修正提交为 `6023c9f`。单元与契约 1156 passed、31 skipped，五项原生场景通过；
新的完整实验及产物返修后，八项 proof valid、closing DONE，并记录当前证据的 signoff。
提醒已在实际后台启动结果中验证，最终包更新、重启及同一会话恢复检查也通过。
详细方法和证据见
[实验报告](../experiments/opencode-v1-full-flow-2026-11-25.zh.md)。

最新工作区、工具报告和完整事件保存在
`/home/mhc/veripower-opencode-v1-task-hook-e2e/counter4/`。
安装指南负责用户操作，本文件保留需求与决定，实验报告保留方法、观察和证据。
