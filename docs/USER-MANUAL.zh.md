# VeriPower 用户手册

[English](USER-MANUAL.md)

本指南介绍如何准备设计任务、运行流程、复核产物，以及在修改或中断后继续工作。`{module_dir}` 表示完整设计工作区所在的目录。让 agent 操作时，请提供它的绝对路径。

## 1. 准备环境

按 [README 快速开始](../README.md#quickstart)安装 VeriPower。各宿主的配置说明分别见 [Claude Code](../.claude-plugin/README.md)、[opencode](../.opencode/README.md)、[DeepSeek Harness](../.dsh/README.md) 和 [Codex](../codex/README.md)。

Python 脚本需要 Python 3.10 或更高版本，以及 `requirements.txt` 中的依赖。在源码仓库目录下执行：

```bash
python3 -m pip install -r requirements.txt
```

完整流程使用 SpyGlass、Design Compiler、PrimeTime 和 VCS/UVM。规格、验证规划和 RTL 设计阶段可以不依赖这些 EDA 工具运行。工具路径、许可证、库文件和环境变量见 [EDA 环境说明](eda-env.md)。这些设置应导出到启动 coding agent 的环境中。

开始设计前，可在独立会话中提出：

> 运行 env-precheck skill。

该检查会查看工具和环境设置，再针对你选择的阶段运行小型工具任务。它报告哪些阶段可以运行，并为缺失的变量建议设置值，不修改你的 shell 配置。在启动受影响的阶段前，先处理报告的环境问题。

## 2. 准备设计输入

流程从 `{module_dir}/intent/brainstorm.md` 开始。文件名固定，内容可以沿用现有规格文档的格式。引用材料放在同一棵 `intent/` 目录树中。

```text
module_dir/
└── intent/
    ├── brainstorm.md
    └── ...                 参考模型、寄存器表、标准或其他依据
```

### 使用已有规格

将规格保存为 `intent/brainstorm.md`，并附上理解它所需的材料。写明要求的行为、接口、时钟、复位，以及适用的时序、面积、功耗或覆盖率目标。目标需要带上适用条件，例如功耗上限对应的运行场景。标明尚未解决的问题，以及希望由 agent 作出的选择。

将权威参考文件复制到 `intent/` 中，使其内容与规格一起被跟踪。目录树外的文件不会自动成为意图输入。符号链接记录的是目标路径，不会跟踪目标内容的变化。

已有 RTL 或测试可以作为参考材料提供，并在规格中说明它们的用途。流程会生成并记录自己的阶段交付物，将文件放进模块目录本身不会登记一个已完成的阶段。

### 与 agent 讨论需求

如果需求还需要讨论，在独立会话中提出：

> 为 {module_dir} 运行 brainstorm skill。

该 skill 会梳理需求和未决选择，再写入 `intent/brainstorm.md`。完成后返回路径，并简要说明覆盖或修改的内容。开始流程前先阅读文档。已有合适规格时，可以直接从该文件启动。

## 3. 启动与查看进度

开启独立会话，提出：

> 为 {module_dir} 运行 design-flow skill。

Agent 负责协调阶段执行和返工。它在你的授权范围内继续工作，需要你决定时，会带上相关依据。你可以按需复核交付物，阅读报告本身不要求流程暂停。

<p align="center">
  <img src="../assets/pipeline-dag.png" alt="设计与验证阶段之间的主要产物依赖" width="760" />
</p>

图中展示主要产物依赖。RTL 设计与验证规划都从规格阶段出发。具备条件的工作可以并行执行，调度器还会考虑正在运行的任务和返工。后续检查发现问题时，流程可以返回先前阶段处理。

查看进度时，可以问：

> 查看 {module_dir} 的当前状态，包括失败的检查和未完成的运行。

| 状态 | 含义 | 如何处理 |
|---|---|---|
| `missing` | 该阶段尚未收取过结果 | 让流程安排所需工作 |
| `in-flight` | 已派发的运行尚未收取 | 让 agent 检查执行者，退出后收取结果 |
| `valid` | 最新结果通过，记录的文件版本仍然一致 | 按需复核结果 |
| `stale` | 最新结果曾通过，但记录的输入或输出发生变化 | 让流程重新评估受影响的工作 |
| `failed` | 最新结果报告失败 | 查看发现并跟进返工 |
| `blocked` | 最新一次收取未能建立通过或失败结论 | 处理报告的原因，例如结果缺失或格式错误 |

`in-flight` 表示运行尚未收取，执行者也可能已经退出。`blocked` 表示执行或收取未能完成，`failed` 则包含阶段作出的技术失败结论。

## 4. 复核结果

各阶段将文件发布到 `Design/` 或 `Verification/` 下。阶段的 `result.json` 记录结论和交付产物清单。下表列出适合从哪里开始复核，目录均相对于 `{module_dir}`。

### 需求与验证计划

| 目录 | 优先查看的文件 | 复核重点 |
|---|---|---|
| `Design/specification/` | `design.md`、`requirements.json`、`spec-review/findings/`、`spec-review/decisions.md` | 行为要求、未决需求、数值目标、接口与时钟决定 |
| `Verification/simulation-plan/` | `verification-plan.md`、`plan-review/findings.md`、`plan-review/decisions.md` | 计划中的测试是否覆盖需求，评审发现如何处理 |

需求台账保留原文，并注明每个条目由谁判定。复核时关注未决条目、决策、外部责任和数值界限。`unassignable` 条目必须解决后，规格阶段才能通过。其他规格产物包括 `manifest.json`、`clocks.json`、`top-io.json`、`check-hints.json` 和 `constraints/`。

验证计划还配有 `tb-scaffold.json`、`sequences.json` 和 `power-scenarios.json`。功耗场景说明功耗阶段需要执行哪些测量。

### RTL 与静态分析

| 目录 | 优先查看的文件 | 复核重点 |
|---|---|---|
| `Design/rtl-design/` | `src/`、`rtl-files.json`、`constraint-annotations.json`、`semantic-review/` | 实现、源文件组织、时序标注和设计评审发现 |
| `Design/lint-cdc/` | `lint-report.txt`、`cdc-report.txt`、`scripts/waiver.tcl` | 报告的违规，以及每项豁免的技术依据 |
| `Design/synthesis/` | `reports/timing_setup.rpt`、`reports/area.rpt`、`reports/qor.rpt`、`out/` | 建立时间裕量、单元面积、报告一致性和综合后的设计 |
| `Design/timing-analysis/` | `timing-report.txt` | 建立与保持时间结果、分析覆盖范围和时序例外 |

RTL 源码位于 `Design/rtl-design/src/`，源文件清单及相关编译输入见 `rtl-files.json`。约束标注向 lint/CDC 和综合提供与 RTL 有关的信息。阶段本地约束包括 lint/CDC 的 `scripts/local.sgdc` 和综合的 `constraints.local.sdc`。

综合从 `timing_setup.rpt` 读取建立时间裕量，从 `area.rpt` 读取单元面积，并用 `qor.rpt` 交叉检查建立时间违例。数值判定记录在 `result.json` 的 `stage_specific.requirements` 中。`out/` 包含网表、导出的 SDC、SDF 和下游使用的支持文件。如果变化只要求重新判断已有证据，新的阶段运行可以复用仍然适用的测量结果。

### 仿真与功耗

| 目录 | 优先查看的文件 | 复核重点 |
|---|---|---|
| `Verification/simulation/` | `case-results-summary.md`、`structural-coverage.json`、`check-review.md`、`tb/uvm/refmodel/` | 实际执行的测试、DUT 覆盖率、检查逻辑和预期行为 |
| `Verification/power-analysis/` | `analysis.md`、`experiment/`、`reports_ptpx/<id>/` | 各场景的测量条件、实验检查、开关活动和功耗 |

调查失败的仿真用例时，查看 `regression-log.txt` 和 `logs/` 下的用例日志。`tests/testlist.json` 列出声明的测试，`case-results.json` 记录测试计数。编译环境见 `env.sh`、`filelist.f` 和 `rtl_filelist.f`。原因不明确时，流程可以运行 `simulation-triage`，并将分析发布到 `Verification/simulation-triage/`。

复核功耗时，先看 `analysis.md` 中的测量条件和结论。各场景的 `power_flat.rpt` 提供功耗总数，`power_hier.rpt` 提供层次明细，`switching_activity.rpt` 说明活动标注情况。SAIF 数据位于 `saif/<id>.saif`。这些结果是已执行场景的区间平均值，应与对应的需求和条件比较。

## 5. 修改与恢复

### 修改设计或测试

告诉 agent 需要修改什么，以及哪些行为必须保留。例如：

> 修改 {module_dir} 的 RTL，解决这项时序问题，然后执行受影响的检查。

如果你已经手工修改了文件，请说明文件位置和修改目的。下一次状态查询会比较记录版本与当前文件。产出该文件的阶段，以及记录了该产物的使用方，可能因此变为 `stale`。后续分析依据各自的输入重新判断，例如综合交付的网表。

新的运行会把本阶段选定的现有产物复制到新工作目录，作为 agent 开始工作的依据。Agent 可以为满足任务要求继续修改它们。将需要保留的修改纳入版本管理，并在继续工作时说明保留要求。

### 修订需求

运行中的流程将 `intent/` 视为只读输入。修订前先完成或停止正在执行的工作。可以让 agent 更新规格，也可以在独立会话中重新使用 brainstorm skill 讨论修订。随后使用更新后的输入继续流程。所有阶段都记录了意图目录树，因此其中的内容变化会使流程重新评估全部八个阶段。

### 中断后继续

保留模块目录，在新会话中提出：

> 继续 {module_dir} 的设计流程。收取结果前，先检查尚未结束的执行者。

Agent 会检查事件历史和文件，确认先前启动的任务是否还在运行。它按任务需要等待或停止这些任务，确认退出后收取运行结果。没有可用结果的运行可以被收取为 `blocked`，再处理报告的原因。已有通过结果在记录版本仍然一致时可以继续复用。

### 处理阻塞

让 agent 说明失败阶段、运行编号、相关报告和建议的返工方式。阶段可以修复自身，也可以将修改交给提供输入的阶段。需要更多信息或决定时，补充后让流程继续。后续诊断可以修正先前的返工归属。

## 6. 完成与保存交付物

所有必需阶段都有当前有效的通过结果，且所有已派发的运行都已收取时，流程结束。可以要求 agent 提供交付摘要，说明已检查的需求、关键报告和保留的外部责任。

如果任务包含接受记录，让 agent 准备 signoff。它会检查当前结果，以及已发布文件是否被阶段记录覆盖，再提供接受决定所需的证据。决定按已有授权作出，记录包括决定者和依据。

Signoff 绑定已接受的阶段证据。证据变化使结果失效时，对应接受记录也失效。新的阶段运行所得结果，在任务要求时需要重新接受。正常完成不要求额外 signoff。

版本管理中可保留原始需求、规格、RTL 源码树与文件清单、约束标注、验证计划、testbench 源码、实验源码和复核所需的报告。阶段的 `result.json` 列出了它发布的产物。

需要保存可继续工作的快照时，保留整个模块目录，包括 `events.jsonl`、已发布结果和 `runs/`，同时保存工具与库的配置。归档时保存独立副本，因为运行路径和发布路径可能通过硬链接共享文件内容。

交付的 RTL、UVM 源码、SDC/SGDC 约束、网表和报告采用 EDA 工具的常规格式。配齐所需文件与环境设置后，可以在 VeriPower 之外使用。

## 7. 常见问题

| 现象 | 下一步 |
|---|---|
| 模块目录或 `intent/brainstorm.md` 缺失 | 核对模块的绝对路径，将输入文档放入它的 `intent/` 目录 |
| EDA 工具无法运行或获取许可证 | 检查启动环境，使用 `env-precheck` 核查受影响的阶段 |
| 会话结束后运行仍为 `in-flight` | 让 agent 检查执行者，确认退出后收取运行结果 |
| 收取报告结果缺失或无效 | 查看运行日志与结果错误，让阶段完成工作并写出新的结果 |
| 无法读取覆盖率 | 按 [EDA 环境说明](eda-env.md#coverage-report-urg-text-layout)核对 URG 文本报告和 DUT 实例范围 |
| VCS 编译在 C/C++ 链接阶段失败 | 检查编译器与所装 VCS 的兼容性，以及 [EDA 环境说明](eda-env.md#optional)中的 `VCS_CC` / `VCS_CPP` 设置 |
| Signoff 报告阶段无效 | 继续流程，处理缺失、失败或过期的结果 |
| Signoff 报告存在未记录文件 | 判断文件是否属于交付，让阶段记录需要的产物或移除多余文件 |

执行与数据模型见[架构文档](../ARCHITECTURE.zh.md)。
