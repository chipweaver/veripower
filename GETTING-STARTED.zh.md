# VeriPower 上手指南

> 把一个模块从想法一路推进到签核闭合。本指南完整走一遍流程，
> 用占位模块名 `{module}` 演示，请替换成你自己的模块名。这是「怎么做」；想了解
> VeriPower「为什么这样设计」，见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

## 一分钟看懂它怎么跑

VeriPower 通过一条 9 个阶段的流水线，把一个已批准的想法变成完成前端签核的设计。
有两点决定了你的使用体验：

- **头脑风暴（brainstorm）先行，且在独立会话中进行。** 进入流水线之前，你先运行
  `brainstorm` 技能来敲定需求与架构；它产出一份冻结的 `asic/{module}/brainstorm.md`。
  只有当该文件的 `Status: approved` 时，流水线才会启动。
- **一句话启动流水线。** 你对 agent 说一句*「为 {module} 运行设计流程」*，
  `design-flow` 协调器（Orchestrator）就会接管——它会自举模块状态，然后沿着阶段图
  逐级推进，逐个派发各阶段并记录每一步。

它**并非**全程无人值守。你恰好有三个介入点：

1. **brainstorm** 对话（流水线之前）。
2. 当 `simulation-plan` 把验证计划呈现给你时，**批准该计划**。
3. **响应升级（escalation）**——流程在极少数需要人来决策的时刻。

其余一切都自主运行并随时汇报。每一个决策都会追加进审计日志（`events.jsonl`），
你随时可以查询状态。

## 前置条件

- **加载了插件的 Claude Code：**
  ```bash
  claude --plugin-dir /path/to/veripower
  ```
- **Python 3**，外加 [`requirements.txt`](requirements.txt) 中的两个依赖
  （`jsonschema`、`referencing`）。
- **EDA 工具——仅工具相关阶段需要。** 有五个阶段会调用 Synopsys 商业工具
  （`lint-cdc` → SpyGlass、`synthesis` → Design Compiler、`timing-analysis` →
  PrimeTime、`simulation` → VCS + UVM、`power-analysis` → PrimeTime PX），需要
  [`docs/eda-env.md`](docs/eda-env.md) 中描述的环境——工具在 `PATH` 上、一个 license
  服务器，以及 `LIB_DB` / `LIB_V` / `UVM_HOME` 变量。其余四个阶段（`brainstorm`、
  `specification`、`simulation-plan`、`rtl-design`）仅靠 Claude Code + Python
  即可运行。

## 流水线

```
[brainstorm] (pre-pipeline, own session) → approved brainstorm.md ↓

[specification] → [simulation-plan] → [rtl-design]
                                            │
                          ┌─────────────────┴──────────────────┐
                          ↓                                    ↓
                     [lint-cdc]                          [simulation]
                          │                                    │
                          ↓                                    │
                     [synthesis]                               │
                          │                                    │
                          ↓                                    │
                  [timing-analysis]                            │
                          │                                    │
                          └─────────────────┬──────────────────┘
                                            ↓
                                    [power-analysis]
                                            │
                                            ↓
                                 kernel.py signoff  (you, Step 5)
```

## 第 1 步 —— 头脑风暴你的模块

在一个独立会话中，让 agent 为你的模块做头脑风暴——这会运行 `brainstorm` 技能：

> 为新模块 {module} 做头脑风暴

它会进行一套结构化的 D0–D7 对话（需求、接口、架构——每次问一个问题），并写出
`asic/{module}/brainstorm.md`。审阅它，并把 frontmatter 设为 `Status: approved`。
这份冻结文件是流水线唯一的上游输入——流水线绝不会再回头去重开这段头脑风暴对话。

> **【真实运行记录——即将补充】** 待第一次 benchmark 扫测完成后，这里会放入一段
> 真实的头脑风暴节选。

## 第 2 步 —— 启动流程

在一个加载了插件的会话中，对 agent 说：

> 为 {module} 运行设计流程

`design-flow` 协调器会校验已批准的 `brainstorm.md`，建立模块状态，并开始沿流水线
推进。从这里开始你基本只是旁观——仅在下述介入点出手。

> **【真实运行记录——即将补充】** 这里放启动时的对话记录。

## 第 3 步 —— 哪些自动跑，你在哪里介入

协调器按依赖顺序派发各阶段。最早的两个阶段在「需要你参与多少」上有所不同：

- **`specification`（自主）。** 从你的头脑风暴推导出冻结的设计真源：`design.md`、
  各子模块的子设计、`manifest.json`，以及约束文件对
  （`<TOP>.sdc` / `<TOP>.sgdc`）。无对话——它读取已批准的头脑风暴并产出规格。
- **`simulation-plan`（你来审阅）。** 起草验证计划（testpoint + 功耗场景），并把
  `verification-plan.md` **呈现给你批准**。只有你批准后，该阶段才会通过。

之后，其余阶段自主运行并汇报结果：`rtl-design` 先跑，然后图分叉为实现签核分支
（`lint-cdc` → `synthesis` → `timing-analysis`）与 `simulation` 分支；两条分支在
`power-analysis` 汇合，流水线到此为止。闭合签核是另一件由你开口要的事（第 5 步）。

**随时查看进度**——直接问 agent：

> {module} 现在到哪一步了？

这会回到 `design-flow`，由它汇报每个阶段的状态——该状态是按需从事件日志与磁盘指纹
计算得出的（`kernel.py status`），并非读取某个存储的快照。每个阶段也会在磁盘上
留下一份 `result.json`——设计类阶段在 `Design/` 下，验证类阶段在 `Verification/` 下。

> **【真实运行记录——即将补充】** 这里放一份真实的状态快照。

## 第 4 步 —— 当某个阶段失败（返工 rework）

阶段失败会被**自动路由**——一个确定性的决策器（decider）选定返工目标，协调器
重新派发对应阶段。你不需要手动路由任何东西，已经在执行中的工作也不会被丢弃。
（完整的依赖图与状态模型见 [`ARCHITECTURE.md §3`](ARCHITECTURE.md#3-rule-registry-and-the-derived-dependency-graph)
与 [`§4`](ARCHITECTURE.md#4-state-model-the-event-log)。）

有一类失败会升级给**你**：当需求本身需要修改时，`specification` 会以
*「requirements need revision: …」* 的 `fail_reason` 升级。恢复办法：

1. 重新运行 `brainstorm` 技能，并重新批准更新后的 `brainstorm.md`。
2. 这就是全部的失效操作。`brainstorm.md` 是 `specification` 记录在案的输入，改动它
   会让规格证明（proof）的指纹与磁盘不再匹配——该阶段在下一次查询时自动过期变为
   stale，凡是消费了该规格的下游证明也随之一并过期。没有任何失效命令需要执行。
3. 让 agent 再次运行设计流程——`decide` 会从新的头脑风暴重新推导，并重建已过期的阶段。

> **【真实运行记录——即将补充】** 这里放一个真实的返工示例。

## 第 5 步 —— 闭合签核

交付（delivery）只把每个阶段推到证明有效为止。签核是另一件事，一次刻意的动作：
你开口要它，流程就循环 `decide --objective signoff`——它要求同一批证明去过一道更严的
门：每个证明当前有效、没有未经验证的文件带外混入，且**每一个 LLM 自撰的裁判都由你
pin 过**。但凡差一点，都会以 `ESCALATE` 回来，并指名是什么卡住了它（通常是「去把它
pin 掉」）。

门干净时，签核还没有闭合——闭合它的是你。经你批准后，流程执行：

```bash
kernel.py signoff --module {module} --provenance <you> --reason "<why>"
```

这会记下是谁闭合了该模块、以及为什么。此后 `kernel.py status` 会报告
`signed_off: true`——但这只在它脚下每个证明持续有效期间成立。改动一个设计文件，或
`reopen` 掉一个 pin，它就自行跌回；签核的成色，不会超过它脚下那批证明。

它背后是每次运行都会产生的审计轨迹：

- `asic/{module}/events.jsonl` —— 仅追加、经 schema 校验的事件日志；**唯一**的持久状态文件（真源）。
- 每个阶段的状态 —— **不**存储在任何地方；`kernel.py status` 按需从事件日志与磁盘指纹
  计算得出，因此它绝不会与磁盘上的真实内容发生漂移。

> **【真实运行记录——即将补充】** 这里放一次真实的签核闭合。

## 接下来去哪

- [`ARCHITECTURE.md`](ARCHITECTURE.md) —— 规则注册表、派生出的依赖图与设计原理。
- [`docs/eda-env.md`](docs/eda-env.md) —— 工具相关阶段所需的 EDA 工具 / license /
  环境配置。
- [`CONTRIBUTING.md`](CONTRIBUTING.md) —— 扩展或替换某个阶段技能。
