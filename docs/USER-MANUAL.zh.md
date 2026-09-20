# VeriPower 用户手册

面向前端设计/验证工程师。从装环境到签核，按实际操作顺序走一遍。人工介入点在流程中标出，末尾附两张速查表。

---

## §0 一句话介绍

VeriPower 把一份已经敲定的模块需求，一路推到前端签核。Spec、验证计划、RTL、lint/CDC、综合、时序、仿真、功耗，八个阶段由 Orchestrator 自动派发和返工，需要你参与哪些决定，取决于实际问题和你的授权。

---

## §1 完整流程

以下用 `{module}` 表示模块名。整棵工作树就放在同名目录下，命令里给的也是它。不在它的上一层目录里时，给出到该目录的路径。

### 1.1 开跑前

**装本插件**

Claude Code:

```bash
claude plugin marketplace add chipweaver/veripower
claude plugin install veripower@chipweaver
```

或 clone 源码后从命令行启动：`claude --plugin-dir /path/to/veripower`。

opencode —— 把插件加进 `~/.config/opencode/opencode.json` 或项目级 `opencode.json`:

```json
{ "plugin": ["veripower@git+https://github.com/chipweaver/veripower.git"] }
```

然后带两个环境变量启动：

```bash
OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS=true \
OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX=131072 opencode
```

第一个开关启用后台子 agent。opencode 1.18.30 默认将单次输出限制为 32,000 token。
使用支持更长输出的模型时，将第二个开关设为模型声明的输出上限；`131072` 是示例值。

DeepSeek Harness —— 装进你要跑的 profile：

```bash
dsh plugin --profile web add "veripower@git+https://github.com/chipweaver/veripower.git"
dsh web
```

它以 profile 层的形式装入，并自己找到 `skills/`，无需任何配置。用 `web`，不要用一次性的
`headless` —— 派发出去的阶段会活过派发它的那个回合，而 `headless` 回合一结束就退出。

Codex — 安装原生插件（已在 Linux、CLI 0.154.0 验证）：

```bash
codex plugin marketplace add chipweaver/veripower
codex plugin add veripower@chipweaver --json
```

以 `codex --enable hooks --enable multi_agent` 启动，在 `/hooks` 中审核并信任两个
VeriPower hook，再开启新会话。插件使用原生子代理，保留宿主权限配置。
详见 [Codex 适配说明](../codex/README.md)。

**Python**

支持 **3.10 / 3.11 / 3.12**。

```bash
python3 --version
```

装依赖包：

```bash
pip install "jsonschema>=4.18" referencing PyYAML
```

或源码目录内执行：

```bash
pip install -r requirements.txt
```

**EDA 工具与 license**

要装的工具、要设的变量见 [`eda-env.md`](eda-env.md)。包括 `dc_shell` / `pt_shell` / `vcs` / `spyglass`、`fsdbreport` / `fsdb2vcd`、`make` / `urg`、license 变量、`LIB_DB` / `LIB_V` / `UVM_HOME`，还有 `/bin/sh` 要指向 `bash`。

只跑 `specification` / `simulation-plan` / `rtl-design` 的话，这段可以跳过，不需要任何 EDA 工具。

**`env-precheck` 环境检查**

环境准备好之后，在一个独立会话里：

> 运行 env-precheck 技能

它逐行核对工具与变量，再实跑一遍各工具命令确认能 checkout，最后报出这台机器能跑的阶段清单。只报告，不改环境。缺变量时打印 `export` 行给你自己贴。

### 1.2 输入件

整条流水线只认一个目录：`{module}/intent/`。文档以 `brainstorm.md` 的名字放进去，文档依赖的东西一起放进去，里面怎么组织随你。怎么来有两条路。

**一、你已经有规格文档**：直接存成 `{module}/intent/brainstorm.md`，什么形状都行，它引用的东西也放进这个目录：参考模型、寄存器表、标准原文。你的文档指为权威的文件，会由需要它的阶段在原地读取。有两件事要知道。`intent/` 外的文件不会自动作为意图交付和版本化。必要依据确实缺失时明确指出；任务要求后续准备的工具和产物交给相应阶段。符号链接按它指向哪里记账，不按那里有什么，所以共享规格在链接背后变了是看不见的——请直接拷进来。不用再跑 brainstorm：`specification` 会在 `requirements.json` 中交代原始意图，保留原文、条件与判断责任；含义相同的重述可以共用条目，不要求原文采用固定格式。

**二、从零生成**：在**独立会话**里：

> 为 {module} 运行 brainstorm 技能

它一次问一个问题，每问都附上它自己的答案和理由，所以你是在挑，不是在写。范围、功能、顶层接口、时钟复位
及其跨越、架构分区、时序场景、PPA 目标、下游阶段还缺什么，逐项要么定下、要么明确留白，才算问完。你已经
带来的东西，它不会再问一遍。

跑完它**只把路径交给你**，不回显正文。你读磁盘上那份文件，**确认内容没问题即可启动流水线**。

不管走哪条路，文档里写了什么，流水线就按什么判，多一条也没有：你没写的界限不会被判，每项义务有负责阶段、按实际授权处理的决定，或明确的外部责任。必要定义缺失会被指出；实现选择和待创建产物则分配给相应工作。

> **目前不支持**：把已有的 RTL、testbench 作为工程件导入。它们只能作为对话素材喂进 brainstorm，RTL 和 TB 仍由流水线重新生成。

### 1.3 启动

在**独立会话**里：

> 为 {module} 运行 design-flow 技能

Orchestrator 接管。它每一轮问一次调度器「下一步干什么」，调度器返回**恰好一个**动作，由它执行。从这里开始你只在介入点出手。

### 1.4 逐阶段推进

```
[brainstorm]  (流水线之前，独立会话)
     ↓
intent/brainstorm.md
     ↓
[specification] → [simulation-plan] → [rtl-design]
                                            │
                          ┌─────────────────┴──────────────────┐
                          ↓                                    ↓
                     [lint-cdc]                          [simulation]
                          ↓                                    │
                     [synthesis]                               │
                          ↓                                    │
                  [timing-analysis]                            │
                          └─────────────────┬──────────────────┘
                                            ↓
                                    [power-analysis]
                                            ↓
                                      签核（任务要求时，§1.6）
```

工作树按阶段分在 `Design/` 和 `Verification/` 下。每个阶段只说三件事：**干什么**、**产物**、**你的动作**。

产物表第三列标出要不要你看。**必看**表示相应决定需要参考的材料，由谁决定遵循任务授权。**选看**表示复核时才需要翻。没标的不用读，脚本把关或直接被下游工具消费。

**流水线遵循实际授权。** 需要你决定时呈现未决事项；明确委托范围内继续推进；任务要求时记录接受决定。

剩下标着「读 xx / 扫一眼 xx」的是复核动作，流水线不为它们停。lint-cdc 报告中的豁免消息及其依据可直接复核，没有单独的审批提示。

---

#### specification

**干什么**：从原始意图建立需求、设计选择和接口/时钟边界，生成约束并独立评审。按实际工作组织编写与委派；模块划分由 RTL 阶段决定。

**产物**（`{module}/Design/specification/`）

| 文件 | 是什么 | 要你看吗 |
|---|---|---|
| `design.md` | 模块总览 §1.1–1.5：它提议的架构、边界叙述、联合义务、时序场景 | **必看** |
| `requirements.json` | 依据原文组织的义务与判断责任。独立结论保持可区分，含义相同的重述可共用条目；账本视图列出未决项（`unassignable`）、外部责任、需要决定的事项和数值界限 | **这四组必看** |
| `manifest.json` | 顶层 RTL 模块名，仅此一项 | 选看 |
| `spec-review/findings/` / `decisions.md` | 独立评审、重要决定及其依据和授权 | **必看** |
| `check-hints.json` | 仿真将怎样观测它判的每一条要求 | 选看 |
| `clocks.json` / `top-io.json` | 边界信息：时钟与到达预算、顶层端口 | `design.md` §1.3 是它们的人读版本 |
| `constraints/<TOP>.sdc` / `.sgdc` | 由 clocks + top-io 生成的约束对 | 生成物，不是决策 |

**你的参与**：查看未决要求、数值界限和边界选择。需要你决定时会提供具体依据；已有委托范围内继续推进。交付时可查看 `design.md` 和评审记录。未解决的违约阻止本阶段通过，不能留给最后签核兜住。

---

#### simulation-plan

**干什么**：从规格推出测试点矩阵、TB 骨架、激励序列和功耗场景。

**产物**（`{module}/Verification/simulation-plan/`）

| 文件 | 是什么 | 要你看吗 |
|---|---|---|
| `verification-plan.md` | §3 测试点矩阵 + §4 功耗场景，交付回顾时你看的就是这份 | **必看** |
| `plan-review/findings.md` / `decisions.md` | 计划评审的发现，以及你的裁决 | **必看** |
| `tb-scaffold.json` | TB 骨架：testpoint 与 agent 的定义 | 选看，plan §3 是它的人读版本 |
| `power-scenarios.json` | 功耗场景，由 power-analysis 消费 | 选看，plan §4 是它的人读版本 |
| `sequences.json` | 激励序列定义 | 不用看 |

**你的参与：**查看 `verification-plan.md` 和 `plan-review/findings.md`。阶段负责人依据证据处理发现，未解决的阻塞问题使本阶段不能通过。决定遵循实际授权，并将依据记入 `plan-review/decisions.md`。

> 测试点矩阵指导 TB 编写、回归和覆盖率收敛。

---

#### rtl-design

**干什么**：按各子设计写 RTL，并把这份 RTL 隐含的时序例外和生成时钟声明到 `constraint-annotations.json`，下游 lint-cdc 和 synthesis 的约束都从这里来。

**产物**（`{module}/Design/rtl-design/`）

| 文件 | 是什么 | 要你看吗 |
|---|---|---|
| `semantic-review/*.md` | 对照设计意图审 RTL 的评审 | 复核交付时参考 |
| `*.v` | RTL 本体 | 选看 |
| `constraint-annotations.json` | 这份 RTL 隐含的时序例外与生成时钟，按真实模块名。lint-cdc 与 synthesis 的约束都从这里来 | 选看 |
| `rtl-files.json` | 全局有序 `files[]`、包含路径和仅仿真的 DPI 源文件；下游 filelist 由它生成 | 不用看 |

**你的参与：**`semantic-review/*.md` 记录 RTL 评审发现及处理依据，可用于复核交付、讨论具体疑问。

这一阶段跑完，流水线分叉成实现签核链和仿真链两条并行推进。

---

#### lint-cdc

**干什么**：后台跑 SpyGlass lint 与 CDC 检查。

**产物**（`{module}/Design/lint-cdc/`）

| 文件 | 是什么 | 要你看吗 |
|---|---|---|
| `scripts/waiver.tcl` | waiver 声明与分析选项 | 按需 |
| `lint-report.txt` / `cdc-report.txt` | 原生上报、豁免消息及记录的豁免理由 | 有豁免时复核 |
| `lint-violations.json` / `cdc-violations.json` | 结构化的 violation 清单 | 选看 |
| `scripts/local.sgdc` | 本阶段补的 SGDC 标注，seed 无从得知的端口/时钟关联 | 选看 |
| `scripts/constraints.sgdc` | 实际用的 SGDC，由 spec 的 seed + RTL 标注 + `local.sgdc` 装配而成 | 每轮重装；本阶段补充标注写入 `scripts/local.sgdc` |

按任务要求和实际授权复核被豁免的具体消息及其依据。脚本核对报告完整性与计数，不判断豁免是否合理。

---

#### synthesis

**干什么**：后台用 `compile_ultra` 综合，逐条判定 `requirements.json` 里派给综合的行。

**产物**（`{module}/Design/synthesis/`）

| 文件 | 是什么 | 要你看吗 |
|---|---|---|
| `reports/timing_setup.rpt` / `reports/area.rpt` | 高精度 setup slack 和单元面积测量 | 选看 |
| `reports/qor.rpt` | QoR 摘要及一致性对照 | 选看 |
| `constraints.local.sdc` | 转写自 `constraint-annotations.json` 的时序例外 | 选看 |
| `out/<TOP>_syn.v` / `_syn.sdc` / `_syn.sdf` | 综合后 netlist、导出 SDC、延时标注 | 下游 timing / power 消费 |
| `constraints.sdc` | 实际用的约束，由 spec 的 SDC + `constraints.local.sdc` 装配而成 | 装配产物 |

**你的动作：无。** 复核时对照时序、面积报告和 `result.json` 里的 `requirements[]`，按账本要求判断测量值。SDC 里的例外来自 rtl-design 声明的 `constraint-annotations.json`，无法满足时序的路径会路由到上游修复。

---

#### timing-analysis

**干什么**：后台读综合出来的 netlist + SDC 跑静态时序。

**产物**（`{module}/Design/timing-analysis/`）

| 文件 | 是什么 | 要你看吗 |
|---|---|---|
| `timing-report.txt` | setup / hold slack、端点检查、端口延迟及未测试原因 | 选看 |

**你的动作：无。** 复核时看 `timing-report.txt`。阶段负责人判断报告中的时序结果，以及分析范围和例外是否符合任务。

综合和 STA 按实际变化选择工作。已有测量仍适用时，可直接按当前要求重判；需要计算时，`run` 入口使用 `config.tcl` 的工具配置和临时工作目录；成功后移出已检查的产物，失败则保留日志和临时输出供诊断，直到重试。来源说明随结果保存，不作为下游硬件输入。准备、计算与关闭各自独立，新的阶段运行不意味着必须重新综合。

---

#### simulation

**干什么**：把验证计划落成 UVM TB，独立评审检查、运行回归并调查覆盖缺口。负责人依据实际证据处理发现，修复本地问题；读取 RTL 用于诊断，预期行为仍来自独立依据。用例挂了而它自己判断不出该谁修时，会自动派 `simulation-triage` 去翻波形（`fsdbreport`）、失败用例清单和日志，逐条给出归因。返工由调度器按归因派回该修的那一阶段。

**产物**（`{module}/Verification/simulation/`）

| 文件 | 是什么 | 要你看吗 |
|---|---|---|
| `tb/uvm/refmodel/**` | 判对错的参考模型 | 复核交付时参考 |
| `case-results-summary.md` | 逐用例结果汇总 | 选看 |
| `structural-coverage.json` | 结构覆盖率：line / cond / branch / toggle / fsm | 选看 |
| `regression-log.txt` + `logs/` | 回归日志，以及每个用例自己的 log | 选看，查某个用例为什么挂就翻 |
| `tb/uvm/**`（其余） | UVM TB 本体 | 选看 |
| `check-review.md` | 逐 testpoint 的检查充分性评审 | 用于本阶段的检查修复 |
| `env.sh` / `filelist.f` / `rtl_filelist.f` / `tests/testlist.json` / `case-results.json` | 环境、编译文件表、用例清单、机器可读结果 | 不用看 |

**你的参与：**`tb/uvm/refmodel/*` 为回归检查提供预期行为。评估测试结论或调查差异时可查看它。

---

#### power-analysis

**干什么**：两条链在这里汇合。读取验证计划中的测量目的，按需复用验证组件，编写完整功耗实验。检查实际运行条件并采样 SAIF，再用 PT-PX 算区间平均功耗，结合实验有效性判定要求。

**产物**（`{module}/Verification/power-analysis/`，`<id>` = 功耗场景）

| 文件 | 是什么 | 要你看吗 |
|---|---|---|
| `analysis.md` / `experiment/` | 测量解释与可运行的实验源码 | 复核时看 |
| `reports_ptpx/<id>/power_flat.rpt` | 该场景的功耗总数，PPA 判定读的就是这份 | 选看 |
| `reports_ptpx/<id>/switching_activity.rpt` | 多少翻转来自 SAIF，多少来自工具默认值 | 选看，核对实测场景的活动是否已标注 |
| `reports_ptpx/<id>/power_hier.rpt` | 功耗花在哪，层次化明细 | 选看，要降功耗才翻 |
| `saif/<id>.saif` | 各场景使用的活动数据 | 不用看 |
| `reports_ptpx/<id>/ptpx.log` | 该场景的 PT-PX 日志 | 出错时才看 |

复核时先看 `analysis.md` 的测量条件、检查和结论，再按需查看原始报告。验收含义需要决策时，按实际授权由人工或代理处理。这一阶段过了流水线就到头了，任务要求时再记录签核接受决定（§1.6）。

---

**随时看进度**：问一句「{module} 现在到哪一步」。每个阶段是六种状态之一：

| 状态 | 含义 |
|---|---|
| `missing` | 还没跑过 |
| `in-flight` | 正在跑 |
| `valid` | 已记录通过，输入与产物的指纹仍与记录一致 |
| `stale` | 已记录通过，但输入或产物发生变化，需要重新评估受影响的工作 |
| `failed` | 跑了，判定不过 |
| `blocked` | 跑不下去（环境缺件、崩了） |

### 1.5 特殊场景

**我手改了 RTL，会不会被覆盖？谁是真源？**

磁盘是真源。你改完那一刻，**产出这个文件的阶段、读了它的所有下游阶段，同时失效**。每个结果都记了自己读入和产出文件的指纹，对不上就不再有效。

**你的手改不会被回滚。** 但正因为产出它的那个阶段也失效了，下一轮调度会重建它。Agent 是在你改过的文件上**就地改**，你的版本是它的起点，不是被丢弃。

**Ctrl-C 了 / ssh 断了 / 机器重启了**

重新说一句「继续 {module} 的设计流程」即可，没有单独的恢复流程。调度器查询事件日志和落盘文件自动接续，只要目录在，任何新会话都能接上进度。

唯一要你出手的地方：被打断的那一轮会一直显示「还在跑」。你确认它死了就让它收口，下一轮重新路由。

**它卡住了 / 反复改同一个地方**

流程报告当前无法推进的原因，按实际授权处理后继续调度。阶段结果和 triage 结论已能驱动返工；`diagnose` 用于记录后续补充或修正的返工归属。
阶段可以修复自身；只有证据与授权支持改变要求时才修订意图。
更多报错见[附录 B](#附录-b-报错速查)。

### 1.6 签核

`signoff` 记录对当前验证证据的接受，任务要求时才执行。流水线先核对阶段结论与交付制品，再按实际授权处理：保留给你的决定呈现依据并等待，明确委托范围内由代理决定。`provenance` 记录决定者与授权，`reason` 记录接受依据；宿主执行权限独立生效。

签核绑定已接受的证据。证据改变会使它失效；恢复相同证据可以恢复有效性，新的阶段结论则需要重新接受。签核不替代技术验证，也不能使未通过的检查变为通过。

阶段发布目录中的文件须被该阶段记录的制品覆盖。发现未记录文件时，判断它是否属于交付，再移除或依据相关证据重新关闭阶段。

### 1.7 产物与退出路径

**目录树**

```
{module}/
├── intent/                        # 流水线的唯一输入：brainstorm.md 与它依赖的文件（你的，pipeline 只读）
├── events.jsonl                   # 审计日志，唯一的持久状态文件
├── Design/
│   ├── specification/             # design.md / *.json / constraints/ / spec-review/
│   ├── rtl-design/                # *.v / rtl-files.json / semantic-review/
│   ├── lint-cdc/                  # 报告 + violations JSON + scripts/
│   ├── synthesis/                 # out/*_syn.{v,sdc,sdf} / reports/qor.rpt
│   └── timing-analysis/           # timing-report.txt
└── Verification/
    ├── simulation-plan/           # verification-plan.md / *.json / plan-review/
    ├── simulation/                # tb/uvm/ / filelist.f / env.sh / case-results-summary.md
    ├── simulation-triage/         # 失败分析（仅在触发过时存在）
    └── power-analysis/            # reports_ptpx/*/power_hier.rpt
```

每个阶段还会落一份 `result.json`（该轮的状态信封）。

**哪些进 git**（建议，工具不强制）

入库：`intent/`、`events.jsonl`（审计轨迹）、`Design/specification/`、`Design/rtl-design/*.v` + `rtl-files.json`、`Verification/simulation-plan/`、`Verification/simulation/tb/`、各阶段最终报告。

忽略：工具中间产物和运行目录。`*.svf`、`*.pvl`、`command.log`、`pt_shell_command.log`、`simv*`、`csrc/`、综合与 PT 的 work 目录、波形（FSDB 通常很大）。

**卸载**

Claude Code:

```bash
claude plugin uninstall veripower@chipweaver
```

opencode：从 `opencode.json` 删掉插件条目，然后开启新会话。

**脱离这个工具，产物还能用吗**

能。RTL 是标准 `.v` 加一份 filelist（`rtl-files.json`）。TB 是标准 UVM 加 `filelist.f` + `env.sh`，`vcs` 直接能编。约束是标准 SDC/SGDC。综合、时序、功耗的产物就是各工具自己的 netlist 和报告。`events.jsonl` 保存 VeriPower 的审计轨迹，设计产物也可以直接交给 EDA 工具运行。

---

## §2 术语对照表

正文尽量用你熟悉的说法。下面是插件内部和日志里会出现的词。

| 它的词 | 你熟悉的说法 |
|---|---|
| stage / rule | 流程阶段。一个阶段 = 一条 rule |
| proof | 阶段的通过或失败结论，绑定记录的输入与产物指纹 |
| stale | 输入或产物变了，原通过结论已不适用；每次查询重新计算 |
| event log / `events.jsonl` | 审计日志，唯一的持久状态文件 |
| dispatch / reap | 派发一个阶段去跑 / 收口它的结果 |
| decide | 调度器。问它「下一步干什么」，返回恰好一个动作 |
| DISPATCH / REAP / YIELD / DONE / ESCALATE | 派发 / 收口 / 有阶段在跑先等着 / 全绿 / **有阻碍需要处理** |
| workdir / run | 某阶段某一轮的工作目录 / 轮次号 |
| input closure | 某个结果传递依赖到的全部上游产出 |
| fix_owner | 这次失败该由哪个阶段去修 |
| signoff | 按任务授权，对具体阶段证据记录接受决定 |

---

## 附录 A 介入点速查

| # | 时机 | 阶段 | 你要决定什么 | 能跳过吗 | 详见 |
|---|---|---|---|---|---|
| 1 | 需求对话 | brainstorm（流水线之前） | 需求与架构，含 PPA 目标 | 否 | §1.2 |
| 2 | 需求与边界决定 | specification | 根据证据处理未决要求、数值界限和边界选择 | 按实际授权；批准不代替技术证明 | §1.4 |
| 3 | 交付回顾 | specification 独立评审后 | 查看设计与评审依据；阶段通过前须处理违约 | 是 | §1.4 |
| 4 | 交付回顾 | simulation-plan | 按需查看计划与评审依据 | 是 | §1.4 |
| 5 | ESCALATE | 任意阶段 | 处理报告的阻碍，必要时明确返工归属 | 阻碍须解决，人工参与按实际授权 | §1.5 |
| 6 | 签核 | 全部阶段之后 | 按实际授权接受证据 | 仅在任务要求记录接受时需要 | §1.6 |

这些是决定与评审位置，不是强制弹出的权限询问。人工参与按实际授权安排；任务要求时由签核记录接受决定。

## 附录 B 报错速查

**调度与返工**

| 消息 | 含义 | 处置 |
|---|---|---|
| `no module directory at <path>` | 模块目录不存在，多半是路径给错了 | 用模块目录的绝对路径重说一次 |
| `<阶段>: envelope named no fix_owner` | 该阶段失败了，但它没说该谁修 | 指认失败阶段自身或其输入产出阶段来修复，并说明理由（§1.5） |
| `<stage>: fix_owner ... is neither itself nor an input producer` | 修复归属与失败阶段无关 | 指向失败阶段自身，或它实际消费产物的上游阶段 |
| `<阶段>: diagnosis named no fix_owner` | 分析做了，但没指出该谁修 | 它会把候选列给你，你挑一个并说明理由 |
| `intent tree incomplete: intent/brainstorm.md is not there…` | 流水线没有可开工的意图文档 | 把你的文档放到 `{module}/intent/brainstorm.md`，它指为权威的文件放在旁边 |

**签核门**

| 消息 | 含义 | 处置 |
|---|---|---|
| `signoff blocked: <阶段> not valid` | 该阶段没有当前有效的通过结论 | 让流程处理未完成工作、失败或证据变化 |
| `signoff blocked: <阶段> has unrecorded file(s) <文件>` | 阶段发布目录中有文件未被最新 outcome 覆盖 | 判断文件是否属于交付，再移除或依据相关证据重新关闭阶段 |

**环境与工具**

| 症状 | 原因 | 处置 |
|---|---|---|
| 某个 EDA 阶段一上来就报变量未设 | `LIB_DB` / `LIB_V` / `UVM_HOME` 没 export | 先 `echo $VAR` 确认真的没设（别急着去文件系统里翻），export 后让它重跑 |
| `compile_ultra` 检不出 license | 没有 DC-Ultra 授权 | 为 `compile_ultra` 配置 DC-Ultra 授权 |
| 建 `simv` 时链接报错 | 宿主 GCC 与 VCS 预编译对象不兼容 | `export VCS_CC=<gcc>` / `export VCS_CPP=<g++>`（某些 VCS + 新发行版组合下 4.8 是已知可用组合） |
| 覆盖率解析失败 | 你的 `urg` 版本报告布局和 L-2016.06 不同 | 换成 L-2016.06，或把版本差异反馈给插件维护者。 |
| VCS launcher 行为怪异 | `/bin/sh` 不是 bash | Debian/Ubuntu：`sudo dpkg-reconfigure dash` 选 No |
| 检查环境时卡在 license 探测 | license server 不可达 | 先修网络，或换一台 license server |

---

## 还想看什么

- [`../ARCHITECTURE.zh.md`](../ARCHITECTURE.zh.md)：为什么这样设计。流水线与依赖图怎么推出来的、结果有效性怎么判、失败怎么归因、信任边界，以及验证范围。
- [`eda-env.md`](eda-env.md)：EDA 工具 / license / 环境要求的完整原文。
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md)：替换某个阶段的实现（比如换成 Verilator 的 simulation、Yosys 的 synthesis）。
