# OpenCode v1 适配需求与已确认事实

记录日期：2026-11-25。VeriPower 调查基线为当前主线 `bb24efe1b7692cdd743e4adb03b7f7bf296baa89`
（0.2.10）；本机 `opencode --version` 为 `1.19.0`，由用户从 v2 降级。

目标是在独立的 OpenCode v1 适配分支上，让 v1.19.0 承接当前 VeriPower 的技能、执行与
流程语义；主线继续使用 OpenCode v2 适配。本文件记录已经确定的需求、事实和验证范围，
作为当前及后续执行、讨论的锚点。已在 `/home/mhc/veripower-opencode-v1` 建立 `opencode-v1` 分支并开始适配。

## 已确定的需求

1. **目标宿主为 OpenCode v1.19.0。** 以这个版本的实际接口和行为为依据。
   历史 VeriPower 适配只作为参考，不能把当时的限制和变通直接带入新实现。
2. **以当前各平台适配为设计基准。** 阅读 Claude Code、Codex、DSH 和 OpenCode v2 的
   实现、执行说明及相关测试，理解它们如何承接共享流程，再使用 v1.19.0 的原生能力实现。
3. **使用独立 v1 适配分支。** 从当前主线建立分支，改造其中的 OpenCode 适配；主线继续
   使用 v2。共享 `framework/` 和 `skills/` 沿用当前实现，不回退到历史 VeriPower 版本。
   当前没有同包双入口的实施要求。
4. **保持当前职责边界。** 技能负责工程工作和判断，kernel 负责事件、调度、工件有效性和
   收集，宿主负责原生工具、执行器生命周期及执行权限。适配层提供技能接入、安装路径、
   工具说明及所需的调度上下文。
5. **输出 token 上限属于宿主和模型配置。** 不纳入 VeriPower 的适配逻辑、安装要求或
   配套调优说明。
6. **不预设后续维护限制。** 当前不添加“不承诺跟随每个主线版本”、冻结更新范围、
   支持期限等约束；后续同步和更新在实际需要时讨论。上游 v1 后续开发减少是分支选择的
   背景，不由此推导额外的产品承诺限制。

## 当前各平台适配的共同职责

[架构说明](../ARCHITECTURE.md)、[framework 指南](../../framework/README.md)和
[design-flow](../../skills/design-flow/SKILL.md)定义共享执行语义。各适配使用不同的宿主机制：

| 平台 | 技能接入与路径 | 父子 agent 的执行说明 | 后台执行与收集 |
|---|---|---|---|
| [Claude Code](../../.claude/README.md) | 原生插件发现，技能使用 `veripower:` 命名空间 | `SessionStart`、`SubagentStart` hooks 注入安装位置和原生操作说明 | 原生 `Agent` 后台执行与完成通知 |
| [Codex](../../.codex-plugin/README.md) | manifest 声明 skills；执行说明要求读取安装位置的 `SKILL.md` | 父子启动 hooks 分别注入 | `spawn_agent` 创建独立上下文，`wait_agent` 收集完成消息 |
| [DSH](../../.dsh/README.md) | 独立的原生 filesystem skill provider | system prompt section 供父子作用域使用 | 原生 `subagent` 与完成通知 |
| [OpenCode v2](https://github.com/chipweaver/veripower/blob/bb24efe1b7692cdd743e4adb03b7f7bf296baa89/.opencode/README.md) | `ctx.skill.transform` 注册，保留技能安装路径 | 每次模型请求的 context hook 注入 | 原生后台 `subagent` 与完成通知 |

v1 适配需要承接以下行为：

- 父会话和独立子会话都能获得正确的技能、安装路径和原生工具说明；子会话不依赖继承
  父会话的讨论历史。相对引用仍以实际安装的技能目录为基准。
- kernel 的 dispatch 准备并记录工作，宿主真正启动执行器。按阶段声明选择主会话执行或
  独立后台执行；启动后台执行器后继续查询 `decide`，使其他就绪工作能推进。
- 通过宿主确认执行器退出后，再用 `decide --wake RULE:RUN` 和 `reap` 收集结果；
  `result.json` 出现或 kernel 返回 `YIELD` 都不能代替退出确认。
- 执行器等待自己启动的工作结束，通过所属阶段 CLI 关闭。独立审查、工件责任和
  工程授权继续由共享技能定义。
- 保留宿主的执行权限和拒绝结果。适配层不自行增加命令审批、改写命令或放开目录权限。

调度提醒按宿主机制实现：Claude 使用工具完成 hook，DSH 添加额外上下文，OpenCode v2
从会话历史重建提醒；当前 Codex 适配通过执行说明指导启动与等待，没有同样的提醒 hook。
这些实现的共同要求是支持共享流程，不要求每个平台采用相同的 hooks 或消息注入方式。

实现参考入口：
[Claude hooks](../../.claude/hooks.json)、[Claude 执行说明](../../.claude/instructions.md)、
[Codex 执行说明](../../.codex-plugin/instructions.md)、
[DSH 适配](../../.dsh/plugins/veripower.js)、
[调查基线的 OpenCode v2 适配](https://github.com/chipweaver/veripower/blob/bb24efe1b7692cdd743e4adb03b7f7bf296baa89/.opencode/plugins/veripower/server.js)。

## OpenCode v1.19.0 已确认的接口事实

| 接入点 | 已确认行为 | 对适配的意义 |
|---|---|---|
| 插件入口 | 支持默认导出的 `{ id, server }`，`server()` 返回 hooks；也支持旧式插件函数 | v1 分支可直接使用原生 v1 入口 |
| 技能发现 | `config.skills.paths` 可注册安装位置的共享 skills，父子会话均可发现 | 无需向用户的其他平台技能目录建立软链接 |
| 技能调用 | `skill({ name: X })` 使用裸技能名 | 由适配说明原生参数，不在共享技能中写宿主调用形式 |
| 会话说明 | 有 `experimental.chat.system.transform`，会在请求准备时调用 | 可把工具说明放入 system 上下文，无需修改首条用户消息 |
| 后台执行 | `task` 支持 `subagent_type`、`description`、`prompt` 和 `background`，结束后通知父会话 | 使用原生独立执行器和完成通知 |
| 后台开关 | 仍需 `OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS=true`；关闭时 schema 不暴露 `background`，强行调用会报错 | 属于 v1.19.0 的实际运行条件 |
| 命令工具 | 使用 `bash` | 由适配说明，与 v2 的 `shell` 区分 |
| 本地插件自动发现 | 只扫描 `.opencode/plugin(s)/*.{ts,js}` | 当前嵌套的 `plugins/veripower/server.js` 不会被自动发现；安装方案需处理这一差异 |
| 包入口解析 | 读取包的 `exports["./server"]`，并支持相应本地目录解析 | 显式配置包或 checkout 根目录是可用的接入方式 |

调查基线中的插件只导出 `{ id, setup }`。在本机 v1.19.0 显式加载该 checkout 时，日志报错：

```text
Plugin ... must default export an object with server()
```

源码依据均固定到 v1.19.0：
[插件类型](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/plugin/src/index.ts)、
[入口解析](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/opencode/src/plugin/shared.ts)、
[插件加载](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/opencode/src/plugin/index.ts)、
[技能发现](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/opencode/src/skill/index.ts)、
[请求上下文](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/opencode/src/session/llm/request.ts)、
[task](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/opencode/src/tool/task.ts)、
[自动发现](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/opencode/src/config/plugin.ts)。

## 本机运行时验证

2026-11-25 使用本机 OpenCode 1.19.0、临时本地插件目录和脚本化 localhost
OpenAI-compatible provider 进行了验证。插件原型接入当前仓库的 12 个共享技能；
测试命令使用模拟 kernel 返回值，不执行真实阶段。原型包含双入口以验证接口，正式
v1 分支无需保留双入口。

| 验证内容 | 观察结果 |
|---|---|
| 原生技能路径注册 | 12 个 VeriPower skills 可发现；子会话加载的 `lint-cdc` 正文与当前仓库一致 |
| 独立后台子会话 | 子会话收到自己的任务和适配说明，未携带父任务标记 |
| 原生完成通知 | 子会话结束后，父会话收到完成内容并继续请求模型 |
| 调度提醒 | dispatch 后出现；执行器启动后仍保留；下一次 `decide` 后消失 |
| 命令权限拒绝 | 配置 `bash: deny` 时，测试命令没有执行 |
| 后台开关关闭 | schema 不提供 `background`；测试调用报告缺少后台开关，未启动子会话 |
| 使用 system hook 的新原型 | 父子模型请求的 system 上下文均含原生工具说明，用户消息保持原样；技能加载、后台完成和调度提醒仍正常 |

system hook 原型按当前适配职责组织，验证了无需沿用旧版首条用户消息注入方式。
这些结果属于脚本化原生运行时验证，不代表真实模型、打包安装或完整 EDA 流程已经通过。
命令拒绝实验在较早的临时原型上完成，正式适配仍需在最终实现上验证权限行为。

本机临时证据在 `/tmp/veripower-opencode-v1-research-ali5fe26/`：
`native_probe.py`、`current_style_probe.py` 及各 `native-*` 目录中的
`facts.json`、`requests.json`、`messages.json` 和 `server.log`。
临时脚本与原始日志不进入仓库；本节保留实验方法、观察及证据范围。

## 历史参考的适用范围

VeriPower 0.2.5 的 OpenCode 适配曾在 1.18.30 上验证；`6f764c1`（0.2.6）切换到 v2。
这段历史用于查找接口和理解演进，不作为恢复旧实现的要求。

本次逐文件比较 OpenCode 的 `v1.18.30` 和 `v1.19.0` tags，以下五处源码完全相同：
`packages/opencode/src/tool/task.ts`、`packages/opencode/src/config/plugin.ts`、
`packages/opencode/src/plugin/shared.ts`、`packages/opencode/src/skill/index.ts`、
`packages/plugin/src/index.ts`。不能仅由版本升级推断这些接口上的限制已经消失。

VeriPower 历史上的技能软链接已在 `5b99815` 移除；命令审批规则和审批说明前缀已在
`cdf15ac` 随工程授权设计调整移除。它们都不是新适配的设计前提。

官方也支持同包双入口，且 v1 对对象入口的支持始于 1.18.29；这是宿主能力事实，
不改变当前采用独立分支的决定。
[官方说明](https://opencode.ai/docs/build/plugins/migrate-v1/#support-v1-and-v2-from-one-package)

## 实施与验证记录

已从调查基线建立 `opencode-v1` 分支，独立工作区为 `/home/mhc/veripower-opencode-v1`。
适配入口为 `.opencode/plugins/veripower.js`；共享 kernel 和 skills 没有修改。
安装方式、后台开关和取消后的恢复方式写在该分支的 `.opencode/README.md`。

已完成打包安装、技能与父子上下文、正常完成通知、权限允许与拒绝、拒绝审批、取消后
显式恢复、关闭后台能力、本地发现、更新来源及移除后的原生验证。
真实 DeepSeek 模型完成了 specification 交付、独立后台审查、修复与 kernel 收集，
两个并发后台检查、权限拒绝、普通 CLI 执行，以及更新安装来源和重启后的原会话续接；
环境技能还执行了实际 EDA smoke。

此前分项实验没有建立完整 IC 流程通过的证据。用户要求补充的小模块完整真实实验已在
`/home/mhc/veripower-opencode-v1-e2e/counter4` 完成，包含全部阶段、真实 EDA 运行、
独立审查、发现修复、后台收集及实验接受。独立复查为八个 proofs 全部 valid，
`decide --closing` 返回 DONE，`signed_off: true`。证据和问题处理见
[完整流程实验](../experiments/opencode-v1-full-flow-2026-11-25.zh.md)。

详细方法、观察、实际问题和证据范围记录在 `opencode-v1` 分支的
`docs/experiments/opencode-v1-2026-11-25.zh.md`。发布操作在实际需要时确定。

后续讨论和执行以本文件中的已确定需求为基准；新增决定或证据写回相应章节。
