# VeriPower 用户手册

面向前端设计/验证工程师。从装环境到签核，按实际操作顺序走一遍。人工介入点在流程中标出，末尾附两张速查表。

---

## §0 一句话介绍

VeriPower 把一份已经敲定的模块需求，一路推到前端签核。Spec、验证计划、RTL、lint/CDC、综合、时序、仿真、功耗，九个阶段由 Orchestrator 自动派发和返工，你在四类节点上出手来把控质量。**第一责任人仍然是你**，它不替你做决策，但会是一个听话的助手。它也不接管你已有的 RTL 和 testbench，目前是从 spec 重新生成，不是导入。

---

## §1 完整流程

以下用 `{module}` 表示模块名。整棵工作树就放在同名目录下，命令里给的也是它。不在它的上一层目录里时，给出到该目录的路径。

### 1.1 开跑前

**装本插件**

```bash
claude plugin marketplace add chipweaver/veripower
claude plugin install veripower@chipweaver
```

或 clone 源码后从命令行启动：`claude --plugin-dir /path/to/veripower`。

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

> /env-precheck

它逐行核对工具与变量，再实跑一遍各工具命令确认能 checkout，最后报出这台机器能跑的阶段清单。只报告，不改环境。缺变量时打印 `export` 行给你自己贴。

### 1.2 输入件

整条流水线只认一个输入文档：`{module}/brainstorm.md`。它怎么来有两条路。

**一、你已经有详细规格文档**：直接存成这个路径和文件名，不用再跑 brainstorm。

**二、从零生成**：在**独立会话**里：

> /brainstorm {module}

它和你做一轮 D0–D7 的结构化对话，一次问一个问题，给选项由你选：

| 维度 | 谈什么 |
|---|---|
| D0 | 意图与范围（先定这个） |
| D1 | 功能与特性清单 |
| D2 | 接口与互连 |
| D3 | 时钟与复位 |
| D4 | 架构分区候选（**强制 2–3 个**，并排 mermaid 对比） |
| D5 | 时序场景 |
| D6 | PPA 目标 |
| D7 | 验证输入字段就绪度 |

跑完它**只把路径交给你**，不回显正文。你读磁盘上那份文件，**确认内容没问题即可启动流水线**。

不管走哪条路，`specification` 都要从这份文档里读出上面八个维度。**走第一条路时对着这张表自查一遍**。D6 的 PPA 目标缺了，综合和功耗就没有数值门槛可判。D3 的时钟表和 D2 的顶层接口缺了或对不上，约束派生会失败，退回去重做。

> **目前不支持**：把已有的 RTL、testbench 作为工程件导入。它们只能作为对话素材喂进 brainstorm，RTL 和 TB 仍由流水线重新生成。

### 1.3 启动

在**独立会话**里：

> /design-flow {module}

Orchestrator 接管。它每一轮问一次调度器「下一步干什么」，调度器返回**恰好一个**动作，由它执行。从这里开始你只在介入点出手。

### 1.4 逐阶段推进

```
[brainstorm]  (流水线之前，独立会话)
     ↓
brainstorm.md
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
                                      签核（你，§1.6）
```

工作树按阶段分在 `Design/` 和 `Verification/` 下。每个阶段只说三件事：**干什么**、**产物**、**你的动作**。

产物表第三列标出要不要你看。**必看**表示门上会把路径交到你手上。**选看**表示复核时才需要翻。没标的不用读，脚本把关或直接被下游工具消费。

**你不用自己盯着什么时候该出手。** 标着**门**的地方，流水线会停下来问你（specification 两道、simulation-plan 一道）。出事要你归因时会停。签核时会逐份拦着要你认可。

剩下标着「读 xx / 扫一眼 xx」的是复核动作，流水线不为它们停。`semantic-review` 和 `refmodel` 会在你签核时被拦下来补上。只有 lint-cdc 的 `waiver.tcl` 全程没有提示点，想核就自己去看。

---

#### specification

**干什么**：把 brainstorm 推导成冻结的设计文档与边界文件。分三步走。分解（划分子模块），各子模块子设计（并行 ×N），逐子模块语义评审（并行 ×N）。

**产物**（`{module}/Design/specification/`）

| 文件 | 是什么 | 要你看吗 |
|---|---|---|
| `design.md` | 模块总览 §1.1–1.6，§1.7 指向 manifest | **必看** |
| `<child>.md × N` | 每个子模块的子设计 | **必看** |
| `manifest.json` | 子模块划分：`module` + `children[]` | **必看**，在分区门 |
| `ppa.json` | PPA 目标，逐字来自 brainstorm D6 | **必看，逐字** |
| `spec-review/<child>.md` / `decisions.md` | 各子模块评审，以及你对 blocking 项的裁决 | **必看** |
| `features.json` / `check-hints/<child>.json` | 特性清单，以及每个特性由哪些检查覆盖 | 选看 |
| `clocks.json` / `top-io.json` / `interconnects.json` | 边界信息：时钟、顶层端口、切开的连线 | `design.md` §1.4 是它们的人读版本 |
| `constraints/<TOP>.sdc` / `.sgdc` | 由 clocks + top-io 生成的约束对 | 生成物，不是决策 |

**你的动作：两道门**

- **分区门**（第一步之后）：去看 `design.md` §1.4，确认这个划分，或给合并意见让它重划。
- **规格门**（第三步之后）：重点看 `design.md` 和各 `<child>.md` 的内容细节是否符合你的设计，`ppa.json` 那几个数字是不是你要的（综合和功耗后面按它判定），以及 `spec-review/<child>.md` / `decisions.md` 发现的问题和决策你是否认同。

> 流水线越靠前的决策影响越大，spec 阶段是后面一切开发验证的来源，需认真确认。

---

#### simulation-plan

**干什么**：从规格推出测试点矩阵、TB 骨架、激励序列和功耗场景。

**产物**（`{module}/Verification/simulation-plan/`）

| 文件 | 是什么 | 要你看吗 |
|---|---|---|
| `verification-plan.md` | §3 测试点矩阵 + §4 功耗场景，你在计划门看的就是这份 | **必看** |
| `plan-review/review.md` / `decisions.md` | 计划评审的发现，以及你的裁决 | **必看** |
| `tb-scaffold.json` | TB 骨架：testpoint 与 agent 的定义 | 选看，plan §3 是它的人读版本 |
| `power-scenarios.json` | 功耗场景，由 power-analysis 消费 | 选看，plan §4 是它的人读版本 |
| `sequences.json` | 激励序列定义 | 不用看 |

**你的动作：计划门。** 看 `verification-plan.md` 的测试点矩阵和 `plan-review/review.md` 的发现，三选一：

- **approve**：批准整份计划（测试点矩阵、TB 骨架）。如果你认下了评审标为 blocking 的发现，你的原话会记进 `plan-review/decisions.md`。
- **request changes**：你提修改意见，它增量改后重新回到这道门。
- **reject**。

> 测试点矩阵定下来之后，TB、回归、覆盖率收敛全按它走，这道门值得花时间。

---

#### rtl-design

**干什么**：按各子设计写 RTL，并把这份 RTL 隐含的时序例外和生成时钟声明到 `constraint-annotations.json`，下游 lint-cdc 和 synthesis 的约束都从这里来。

**产物**（`{module}/Design/rtl-design/`）

| 文件 | 是什么 | 要你看吗 |
|---|---|---|
| `semantic-review/*.md` | 对照设计意图审 RTL 的评审 | **必看**，签核前要你认可 |
| `*.v` | RTL 本体 | 选看 |
| `constraint-annotations.json` | 这份 RTL 隐含的时序例外与生成时钟，按真实模块名。lint-cdc 与 synthesis 的约束都从这里来 | 选看 |
| `rtl-files.json` | 按子模块的 `files[]` + `incdirs[]`，下游每一份 filelist 都由它生成 | 不用看 |

**你的动作：读 `semantic-review/*.md`。** 它是签核前要你认可的四份判据之一（§1.6）。流水线不会在这里停下来等你，但提前读掉可以少一轮返工。

这一阶段跑完，流水线分叉成实现签核链和仿真链两条并行推进。

---

#### lint-cdc

**干什么**：后台跑 SpyGlass lint 与 CDC 检查。

**产物**（`{module}/Design/lint-cdc/`）

| 文件 | 是什么 | 要你看吗 |
|---|---|---|
| `scripts/waiver.tcl` | 它判为「可接受」的 violation，每条带理由 | **必看** |
| `lint-report.txt` / `cdc-report.txt` | SpyGlass 原始报告 | 选看 |
| `lint-violations.json` / `cdc-violations.json` | 结构化的 violation 清单 | 选看 |
| `scripts/local.sgdc` | 本阶段补的 SGDC 标注，seed 无从得知的端口/时钟关联 | 选看 |
| `scripts/constraints.sgdc` | 实际用的 SGDC，由 spec 的 seed + RTL 标注 + `local.sgdc` 装配而成 | 改它没用，下一轮会重装 |

**你的动作：扫一眼 `scripts/waiver.tcl`。** 它自己判为「可接受」的 violation 会写成 `waive` 并附理由。**lint 干净不等于零 violation。** 判定本身由 SpyGlass 规则集给出，不需要你表态。

---

#### synthesis

**干什么**：后台用 `compile_ultra` 综合，按 `ppa.json` 自判 PPA。

**产物**（`{module}/Design/synthesis/`）

| 文件 | 是什么 | 要你看吗 |
|---|---|---|
| `reports/qor.rpt` | QoR 报告，PPA 判定读的就是这份 | 选看 |
| `constraints.local.sdc` | 转写自 `constraint-annotations.json` 的时序例外 | 选看 |
| `out/<TOP>_syn.v` / `_syn.sdc` / `_syn.sdf` | 综合后 netlist、导出 SDC、延时标注 | 下游 timing / power 消费 |
| `constraints.sdc` | 实际用的约束，由 spec 的 SDC + `constraints.local.sdc` 装配而成 | 装配产物 |

**你的动作：无。** 要复核就看 `reports/qor.rpt`。判定由 dc_shell 的 QoR 报告给出，基准是你在规格门批过的 `ppa.json`。它不会自己发明时序例外。SDC 里的例外只能转写自 rtl-design 声明的 `constraint-annotations.json`，一条路径真收不进来就返工回上游，不会加一条 false path 蒙过去。

---

#### timing-analysis

**干什么**：后台读综合出来的 netlist + SDC 跑静态时序。

**产物**（`{module}/Design/timing-analysis/`）

| 文件 | 是什么 | 要你看吗 |
|---|---|---|
| `timing-report.txt` | setup / hold slack 报告，判定读的就是这份 | 选看 |

**你的动作：无。** 要复核就看 `timing-report.txt`。判定由 pt_shell 的报告给出。

---

#### simulation

**干什么**：把验证计划落成 UVM TB，跑回归，收敛覆盖率。用例挂了而它自己判断不出该谁修时，会自动派 `simulation-triage` 去翻波形（`fsdbreport`）、失败用例清单和日志，逐条给出归因。返工由调度器按归因派回该修的那一阶段。

**产物**（`{module}/Verification/simulation/`）

| 文件 | 是什么 | 要你看吗 |
|---|---|---|
| `tb/uvm/refmodel/**` | 判对错的参考模型 | **必看**，签核前要你认可 |
| `case-results-summary.md` | 逐用例结果汇总 | 选看 |
| `structural-coverage.json` | 结构覆盖率：line / cond / branch / toggle / fsm | 选看 |
| `regression-log.txt` + `logs/` | 回归日志，以及每个用例自己的 log | 选看，查某个用例为什么挂就翻 |
| `tb/uvm/**`（其余） | UVM TB 本体 | 选看 |
| `conformance-review.md` | 逐 testpoint 的检查充分性评审 | 阶段内自用，不给人读 |
| `env.sh` / `filelist.f` / `rtl_filelist.f` / `tests/testlist.json` / `case-results.json` | 环境、编译文件表、用例清单、机器可读结果 | 不用看 |

**你的动作：细看参考模型 `tb/uvm/refmodel/*`。** 它是判对错的那把尺子，四份待你认可的判据里最该较真的一份（§1.6）。尺子错了，整片回归的绿都是假的。流水线不会在这里停下来等你，返工也不用你指派。

---

#### power-analysis

**干什么**：两条链在这里汇合。后台用综合的 netlist + SDF 和仿真的 TB 环境跑门级仿真，出 SAIF，再用 PT-PX 算平均功耗，按 `ppa.json` 自判。

**产物**（`{module}/Verification/power-analysis/`，`<id>` = 功耗场景）

| 文件 | 是什么 | 要你看吗 |
|---|---|---|
| `reports_ptpx/<id>/power_flat.rpt` | 该场景的功耗总数，PPA 判定读的就是这份 | 选看 |
| `reports_ptpx/<id>/switching_activity.rpt` | 多少翻转来自 SAIF，多少来自工具默认值 | 选看，SAIF 没标注上的话功耗数就是假的 |
| `reports_ptpx/<id>/power_hier.rpt` | 功耗花在哪，层次化明细 | 选看，要降功耗才翻 |
| `saif/<id>.saif` | 每个场景一份 SAIF，激励等价的场景只仿一次、共享结果 | 不用看 |
| `reports_ptpx/<id>/ptpx.log` | 该场景的 PT-PX 日志 | 出错时才看 |

**你的动作：无。** 要复核就看 `reports_ptpx/<id>/power_flat.rpt`。判定由 pt_shell 的报告给出。这一阶段过了流水线就到头了，签核是另一件由你开口要的事（§1.6）。

---

**随时看进度**：问一句「{module} 现在到哪一步」。每个阶段是六种状态之一：

| 状态 | 含义 |
|---|---|
| `missing` | 还没跑过 |
| `in-flight` | 正在跑 |
| `valid` | 跑过，结果当前可信 |
| `stale` | 跑过，但上游变了，结果已失效，下一轮会重建 |
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

流程会停下来，把原因**原文**给你，必要时附上候选归因。恢复的唯一通道是**人来做一次归因**，指明该由哪个阶段去修、以及为什么。

常见的一类是规格自己修不动了，通常意味着**需求本身要改**。用 brainstorm 的修订模式重跑，改完 `brainstorm.md`，规格阶段的结果就自动失效了，重新跑流程即可。

更多报错见[附录 B](#附录-b-报错速查)。

### 1.6 签核

**流水线跑完不等于签核。** 跑完只说明每个阶段都出了结果、且结果当前有效。签核是你作为责任人在这批结果上最终从头到尾检查一次并落名，它只在你开口要的时候才开始：

> 为 {module} 进行签核

**这一步为什么存在。** 八个阶段里，四个阶段「过没过」是工具说的。SpyGlass 的规则集、dc_shell 的 QoR 报告、pt_shell 的时序和功耗报告，工具报告本身就作数。另外四个阶段，「过没过」是一份 LLM 写的东西说的，需要你最终评审：

| 阶段 | 判它过没过的是什么 |
|---|---|
| specification | `spec-review/*.md`，LLM 写的规格评审 |
| simulation-plan | `plan-review/*.md`，LLM 写的计划评审 |
| rtl-design | `semantic-review/*.md`，LLM 写的 RTL 评审 |
| simulation | `tb/uvm/refmodel/*`，LLM 写的参考模型，判每个用例对错的那把尺子 |

LLM 写的东西不能自己给自己作证。**所以签核的门槛是这四份你得逐份读过、并认可。**

**你要做的三件事**

1. **说一句要进行签核**（就是上面那句）。
2. **逐份认可那四份。** 差哪份它就停下来指名，比如「rtl-design 的评审还没认可」。你去读那份文件，然后确认，并给一句理由说明为什么你认它。理由连同你的身份记进审计日志。
3. **看清你签的是什么，再批准签核。** 四份都认完、且所有阶段结果仍然有效，它会把签核依据逐个阶段摊开给你。判它过没过的是什么、这份判据现在算谁认的、你认可时那份内容是什么样、工具是哪个、这一阶段读了哪些文件。看完你批准，签核才落下，并记下是谁签的、为什么。

第 2、3 步和「撤回一次认可」都是**问过你才做**的动作，每次都会弹确认。

> **认可绑的是内容，不是文件名。** 它记下那份文件此刻的样子。文件一改，认可自动失效，要重新读、重新认。你签的是那份东西本身。

**签核会自己跌回去。** 签核之后，你改了任何一个上游设计文件，或撤回了任何一次认可，模块立刻退回未签核，不需要谁去撤销。签核的成色不会超过它脚下那批结果。

还有一条你一般碰不到：如果有文件**绕过流程**被塞进某个阶段的输入里，门也不放行。把它移走，或者让那一阶段重跑一次、正式把它记录下来。

### 1.7 产物与退出路径

**目录树**

```
{module}/
├── brainstorm.md                  # 流水线的唯一输入（你的，pipeline 只读）
├── events.jsonl                   # 审计日志，唯一的持久状态文件
├── Design/
│   ├── specification/             # design.md / <child>.md / *.json / constraints/ / spec-review/
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

入库：`brainstorm.md`、`events.jsonl`（审计轨迹）、`Design/specification/`、`Design/rtl-design/*.v` + `rtl-files.json`、`Verification/simulation-plan/`、`Verification/simulation/tb/`、各阶段最终报告。

忽略：工具中间产物和运行目录。`*.svf`、`*.pvl`、`command.log`、`pt_shell_command.log`、`simv*`、`csrc/`、综合与 PT 的 work 目录、波形（FSDB 通常很大）。

**卸载**

```bash
claude plugin uninstall veripower@chipweaver
```

**脱离这个工具，产物还能用吗**

能。RTL 是标准 `.v` 加一份 filelist（`rtl-files.json`）。TB 是标准 UVM 加 `filelist.f` + `env.sh`，`vcs` 直接能编。约束是标准 SDC/SGDC。综合、时序、功耗的产物就是各工具自己的 netlist 和报告。**只有 `events.jsonl` 属于这个工具**，删掉它不影响其余任何东西能不能跑。你丢掉的是审计轨迹，不是设计。

---

## §2 术语对照表

正文尽量用你熟悉的说法。下面是插件内部和日志里会出现的词。

| 它的词 | 你熟悉的说法 |
|---|---|
| stage / rule | 流程阶段。一个阶段 = 一条 rule |
| proof | 「这一阶段的结果当前可信」的凭据。记了它读了哪些文件、产了哪些文件（内容指纹），以及谁做的判定 |
| oracle / judge | **判据**，判这一阶段过没过的东西。工具报告，或一份 LLM 写的评审 |
| grade（`proposed` / `tool` / `human`） | 判据的成色。`proposed` = LLM 写的，签核前要你认可（认可后即 `human`） |
| pin | 你对一份 LLM 写的判据的**认可**。记的是当时那份内容的指纹 |
| reopen | 撤回一次认可 |
| stale | 上游变了，这个结果已失效。不是标出来的，是每次查询现算的 |
| event log / `events.jsonl` | 审计日志，唯一的持久状态文件 |
| dispatch / reap | 派发一个阶段去跑 / 收口它的结果 |
| decide | 调度器。问它「下一步干什么」，返回恰好一个动作 |
| DISPATCH / REAP / YIELD / DONE / ESCALATE | 派发 / 收口 / 有阶段在跑先等着 / 全绿 / **需要你介入** |
| workdir / run | 某阶段某一轮的工作目录 / 轮次号 |
| input closure | 某个结果传递依赖到的全部上游产出 |
| fix_owner | 这次失败该由哪个阶段去修 |
| signoff | 签核，在这批结果上落名的那个动作 |

---

## 附录 A 介入点速查

| # | 时机 | 阶段 | 你要决定什么 | 能跳过吗 | 详见 |
|---|---|---|---|---|---|
| 1 | D0–D7 对话 | brainstorm（流水线之前） | 需求与架构，含 PPA 目标 | 否 | §1.2 |
| 2 | 分区门 | specification 第一步后 | 确认子模块划分 | 否，且是**最后一次能改分区** | §1.4 |
| 3 | 规格门 | specification 第三步后 | design.md / 各子设计 / 评审 / **ppa.json 数字** | 否 | §1.4 |
| 4 | 计划门 | simulation-plan | approve / request changes / reject | 否 | §1.4 |
| 5 | ESCALATE | 任意阶段 | 指认该由哪个阶段去修，并给出理由 | 否 | §1.5 |
| 6 | 认可判据 | 四份 LLM 写的判据 | 读过之后确认，并给一句理由 | 签核前必做 | §1.6 |
| 7 | 签核 | 全部阶段之后 | 看完签核依据后批准 | 是，不签核就一直停在交付态 | §1.6 |

1–4 是流水线正常推进必经的。5 只在出事时出现。6–7 只在你要签核时出现。**中间没有别的地方会等你**，2、3、4 之间和 4 之后都可以挂着跑。

## 附录 B 报错速查

**调度与返工**

| 消息 | 含义 | 处置 |
|---|---|---|
| `no module directory at <path>` | 模块目录不存在，多半是路径给错了 | 用模块目录的绝对路径重说一次 |
| `<阶段>: envelope named no fix_owner` | 该阶段失败了，但它没说该谁修 | 你来指认该由哪个上游阶段去修，并说明理由（§1.5） |
| `<阶段>: fix_owner is itself, in-stage remedy exhausted` | 该阶段自己修不动了 | 往上游找。规格阶段出这条通常是**需求本身要改**，重跑 brainstorm 改需求 |
| `<阶段>: fix_owner '<x>' is outside its input closure` | 出错的那个阶段并没有读到你指的这个阶段的产物 | 重新指认，只能指向它真正读过的上游（含间接） |
| `<阶段>: diagnosis named no fix_owner` | 分析做了，但没指出该谁修 | 它会把候选列给你，你挑一个并说明理由 |
| `<阶段>: the oracle that judged this failure was reopened` | 判它失败的那份判据，认可被你撤回了 | 让它重跑这个阶段 |
| `no eligible rule, none in-flight, not done` | 没有可跑的、没在跑的、也没完成 | 不该出现，请报 issue 并附 `events.jsonl` |

**签核门**

| 消息 | 含义 | 处置 |
|---|---|---|
| `signoff blocked: <阶段> not valid` | 该阶段结果已失效 | 让流程继续跑，把它重建出来 |
| `signoff blocked: <阶段> oracle is proposed (pin it)` | 该阶段那份 LLM 写的判据，你还没认可 | 读过后确认并给出理由，见 §1.6 |
| `signoff blocked: <阶段> has unverified new input(s) <文件>` | 有文件绕过流程被塞进该阶段的输入里 | 把那个文件移走，或让该阶段重跑一次、正式把它记录下来 |

**环境与工具**

| 症状 | 原因 | 处置 |
|---|---|---|
| 某个 EDA 阶段一上来就报变量未设 | `LIB_DB` / `LIB_V` / `UVM_HOME` 没 export | 先 `echo $VAR` 确认真的没设（别急着去文件系统里翻），export 后让它重跑 |
| `compile_ultra` 检不出 license | 没有 DC-Ultra 授权 | 综合阶段整个不可用，没有退到 plain `compile` 的路子 |
| 建 `simv` 时链接报错 | 宿主 GCC 与 VCS 预编译对象不兼容 | `export VCS_CC=<gcc>` / `export VCS_CPP=<g++>`（某些 VCS + 新发行版组合下 4.8 是已知可用组合） |
| 覆盖率解析失败 | 你的 `urg` 版本报告布局和 L-2016.06 不同 | 换成 L-2016.06，或把版本差异反馈给插件维护者。它**不会**伪造一个「覆盖率达标」 |
| VCS launcher 行为怪异 | `/bin/sh` 不是 bash | Debian/Ubuntu：`sudo dpkg-reconfigure dash` 选 No |
| 检查环境时卡在 license 探测 | license server 不可达 | 先修网络，或换一台 license server |

---

## 还想看什么

- [`../ARCHITECTURE.zh.md`](../ARCHITECTURE.zh.md)：为什么这样设计。规则注册表、依赖图怎么推出来的、结果有效性怎么判、调度与信任边界。
- [`eda-env.md`](eda-env.md)：EDA 工具 / license / 环境要求的完整原文。
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md)：替换某个阶段的实现（比如换成 Verilator 的 simulation、Yosys 的 synthesis）。
