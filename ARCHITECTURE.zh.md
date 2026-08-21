# VeriPower 架构

> VeriPower 怎样组织 agent 驱动的芯片设计，以及背后的设计选择。

---

## 1. 概览

VeriPower 是一个芯片前端设计与验证系统。它把一个 LLM 编码 agent 引导过八个阶段，从自然语言规格说明一路走到功耗分析，跑在商用 EDA 工具上（SpyGlass、Design Compiler、PrimeTime、VCS+UVM）。

整个系统围绕一个想法构建。一个确定性内核掌握设计流程的全部事实。哪些验证结论还成立，哪些被某次修改推翻了，下一步该跑什么，谁该负责修一个失败，全由它说了算。LLM agent 和人类工程师都站在内核外面。他们可以提交工作、提交判断，但改不了已经记录下来的东西。内核是事件日志的唯一写入者，agent 的提示词没有任何注入或篡改记录的通道。

<p align="center">
  <img src="assets/architecture.png" alt="VeriPower architecture" width="460" />
</p>

**编排器**（Orchestrator）就是跑在主会话里的 `design-flow` skill。它向内核请求一个动作，执行，再请求下一个。两次查询之间不保留任何状态，也不自行做路由决策。

**确定性内核**（`framework/scripts/`）负责记录事件、推导状态、计算依赖图、调度工作、校验归因是否合法。它做的一切都是对事件日志和磁盘文件的纯计算。

**文件系统**是唯一的持久层。一份只追加的事件日志（`events.jsonl`），加上各阶段产出的制品文件。没有数据库，没有守护进程，没有 HTTP。

阶段 agent 之间不互相通信，也不和编排器对话。每个 agent 收到的是内核写到磁盘上的结构化交接文件，不是编排器上下文的自然语言摘要。结果也写回磁盘。

---

## 2. 流水线

八条规则构成整个流程。第九条 simulation triage 是一个诊断工具，它分析仿真失败但不记录自己的验证结论。

| 规则 | 做什么 | Oracle | 等级 |
|---|---|---|---|
| specification | 从自然语言的头脑风暴产出结构化设计文档、子设计和时序约束 | spec-review（LLM） | proposed |
| simulation-plan | 把每条规格行为映射到测试点，产出验证计划和 TB 脚手架 | plan-review（LLM） | proposed |
| rtl-design | 根据规格生成 RTL | semantic-review（LLM） | proposed |
| lint-cdc | SpyGlass lint 和 CDC 检查 | spyglass 规则集 | tool |
| synthesis | Design Compiler 综合 | dc-shell | tool |
| timing-analysis | PrimeTime 时序分析 | pt-shell | tool |
| simulation | 构建并运行 UVM 测试平台，对 RTL 做验证 | tb-refmodel（LLM） | proposed |
| power-analysis | PrimeTime 功耗分析 | pt-shell | tool |
| simulation-triage | 仿真失败的根因分析 | 无 | 无 |

### 依赖图

依赖图从 `rules.py` 里每条规则声明的输入/输出制品 glob 推导而来。一条规则的输出匹配另一条的输入，就有一条边。没有别的东西维护这张图，所以图和规则实际读写的内容不可能产生分歧。

<p align="center">
  <img src="assets/pipeline-dag.png" alt="Pipeline dependency graph" width="660" />
</p>

*\*Specification 的输出（约束、PPA 目标、接口声明）也被 lint-cdc、synthesis、simulation 和 power-analysis 直接消费。Simulation-plan 的输出（sequences、power scenarios）被 power-analysis 消费。这些边在图中省略了。*

并发是自然涌现的。两条规则之间没有制品依赖，它们就可以同时跑。比如 lint-cdc 和 simulation 之间没有任何共享，经常并行执行。你可以自己查看当前的依赖图：

```bash
python3 -c "import sys; sys.path.insert(0,'framework/scripts'); import rules
for r in rules.FORWARD_PRIORITY: print(r, sorted(rules.input_producers(r)))"
```

### 4 + 4 对称性

看 Oracle 那一列。四条 tool 等级的规则都处理结构和物理正确性：lint、综合、时序、功耗。它们的 oracle，也就是 EDA 工具的规则集和约束文件，在被测设计存在之前就有了。工具不可能和设计犯同一个错。

四条 proposed 等级的规则都处理意图和功能正确性：specification、verification plan、RTL、simulation。这些没有独立的 oracle，因为功能就是意图，而意图在有人拍板之前始终是欠定的。人类判断就在这里介入（§5）。

---

## 3. 状态与证明

### 事件日志

一个模块的全部状态存在一个只追加文件里：`events.jsonl`。没有状态快照。一个阶段是完成了、过期了、失败了还是正在跑，每次被问到都是从日志对着磁盘重新算出来的。内核是唯一的写入者，每条记录落盘前都经过 schema 校验。

编排器在两次查询之间不持有任何东西。上下文窗口被压缩了，或者进程崩溃了，下一次 `decide` 调用直接从磁盘重新推导出正确的动作。不需要任何恢复协议。

### 证明

一条规则跑完后，内核记录一条**证明**（proof）。这是一个裁决（pass 或 fail），绑定了所有被消费输入的内容指纹、所有被产出输出的内容指纹，以及判定这次运行的 oracle。

有效性不存储在任何地方，而是作为查询重新计算。一条证明此刻成立，当且仅当裁决是 pass，每一个落账的输入输出指纹都还和磁盘上的文件吻合，并且 oracle 没有被撤回。三个条件必须同时满足。

举个例子，你改了一行 RTL。下次任何东西查日志的时候，lint-cdc、synthesis、simulation 的输入指纹就对不上了，三条证明同时失效。没有人去标记什么东西过期。过期就是指纹不再匹配这件事本身。与此同时 specification 和 simulation-plan 不受影响，因为它们的输入里没有 RTL。

你也可以在改动之前先查询影响。问内核如果某个文件的内容变了，哪些当前有效的证明会失效。这样决定跳不跳一个阶段，依据的是依赖图上的计算，不是猜测。

---

## 4. 失败与修复

### 直接归因

Synthesis 报告了时序违规。它读了 Design Compiler 的 QoR 报告，判断关键路径在 RTL 里太长了，把 rtl-design 指名为需要修复的规则。

内核检查这个指名是否合法。rtl-design 在不在 synthesis 的传递依赖闭包里？在。rtl-design 产出 RTL，synthesis 消费它。归因成立。

下一轮，内核派发 rtl-design，把失败的 synthesis run 作为上下文传过去。RTL agent 读到时序报告，缩短了关键路径。现在 RTL 输出的指纹变了，lint-cdc、synthesis、simulation 的证明全部失效。内核按依赖顺序重新验证它们。全部通过。结束。

### 需要调查的失败

Simulation 报告失败，但判断不了 bug 在 RTL 里、specification 里、还是测试平台的参考模型里。它没有指名任何人。

内核看到一个没有归因的仿真失败。Simulation 的规则声明了 `simulation-triage` 作为它的诊断工具，于是内核派发 triage。Triage agent 进入失败 run 的目录（UVM 日志、FSDB 波形、覆盖率数据），读规格和参考模型，如果证据不够确定，就在自己的工作空间里搭建受控实验来定位原因。

Triage 发现是规格里一个时钟域关系声明错了。内核确认 specification 在 simulation 的依赖闭包内，记下诊断结果，把失败路由到 specification。

Specification 修正了声明。下游约束随之变化。内核算出哪些证明现在失效了，重新验证受影响的链路。

### 归因机制

失败的那个阶段指名谁需要行动。内核只做一件事：检查这个名字是否合法，也就是它是不是在失败规则的传递依赖闭包里面。没有固定的归因标签表。一个封闭集合只能表达事先想到的失败模式，而症状出现的位置不一定是原因所在的位置。

三种情况会升级到人：阶段没指名任何人，指名了自己（意味着它能做的都试过了），或者指名了闭包之外的东西。升级的时候会带上候选列表和相关证据，不是光抛一个求助请求。

如果多个失败指向同一条规则，它们会合并成一次派发。Lint-cdc 和 synthesis 都归因到 rtl-design，不会让 rtl-design 跑两遍。

---

## 5. 信任边界

### 两种 oracle

Tool 等级的 oracle 独立于它所判定的设计。SpyGlass 的 lint 规则在任何 RTL 被写出之前就存在了。工具和被测制品不可能犯同一个错误，所以裁决是权威的。

Proposed 等级的 oracle 不一样。LLM 撰写的评审或参考模型，来源和被测制品相同。如果 LLM 对规格的某条需求理解错了，它可以产出一份 RTL 和一份参考模型，两者彼此一致，但都是错的。测试通过，什么都不报错。这种静默的假绿灯比任何显式失败都危险，因为它不会引起任何人的注意。

### 验证独立性

设计和验证都从 specification 出发，然后分道扬镳。设计路径产出 RTL。验证路径产出测试环境，这条路径上的一切（计划、脚手架、序列、参考模型）都从 specification 推导，不从 RTL 推导。Simulation 确实把 RTL 作为声明输入消费，但只是把它当作被编译的 DUT。真正判定仿真结果的参考模型是从规格的行为需求构建的，不是靠读 RTL 源码。

每条规格行为都通过 simulation-plan 和 simulation 之间的结构化制品交接映射到测试点，这样就不会有东西因为遗漏而丢失。每轮仿真结束后，一个独立的合规性审查会对比测试实际覆盖了什么和规格要求了什么，既能抓到缺失的检查，也能抓到检查错了方向的情况。

### 从 proposed 到 human

人可以通过 **pin** 来背书一个 proposed oracle，把它的等级提升到 human。这个背书锚定在 oracle 内容当时的指纹上。如果 oracle 被重新生成、内容变了，背书自动失效。不需要谁记着去撤销它。**Reopen** 是显式撤回，它会让所有依赖这个被背书 oracle 的证明失效。

### 签核

关闭一个模块要求所有条件同时满足：每条证明当前有效，每个 oracle 达到 tool 或 human 等级，磁盘上没有在证明记录之后才出现又从未被验证过的输入文件。流水线在 proposed oracle 下可以正常迭代，但不能在它们下面关闭。

人在这个系统里有四个具名动作：背书一个 oracle（`pin`），撤回一个背书（`reopen`），陈述一个归因（`diagnose`），关闭模块（`signoff`）。其余一切都是计算出来的。

---

## 6. 局限

**声明的输入没有强制执行。** 一条规则声明了自己读什么，但没有任何机制真正阻止它去读别的文件。如果它读了，依赖图就会在危险的方向上出错：一条本该失效的证明没有失效。签核门通过对磁盘重新检查声明来部分弥补这一点，专门查新增的输入，但这不是完整的解决方案。

**签核不是正确性。** 签核是对一组声明义务的闭合。这个义务列表是手写在规则注册表里的，不是从语言语义推导出来的。签核的可信度等于这个列表的完整度。

**系统降低的是每次人类判断的成本，不是判断的次数。** 多久需要人介入一次取决于 LLM 的能力。架构让每次判断可复用、持久，但它替代不了判断本身。

---

## 关键术语

| 术语 | 含义 |
|---|---|
| **proof**（证明） | 绑定了精确输入版本、输出版本和 oracle 的验证结论。有效性在每次查询时重新计算。 |
| **oracle** | 证明的判定依据。可能是 EDA 工具的规则集，也可能是 LLM 撰写的评审或参考模型。 |
| **grade**（等级） | oracle 的可信程度。**tool** 表示权威。**proposed** 表示 LLM 在评估自己的工作，够迭代用，不够签核用。**human** 表示人通过 pin 背书了一个 proposed oracle。 |
| **pin** / **reopen** | 人授予和撤回对 proposed oracle 信任的方式。Pin 锚定在 oracle 内容的指纹上，内容变了 pin 就失效。 |
| **rule**（规则） | 内核调度的一个工作单元，声明了自己的输入、输出、证明和 oracle。依赖图从这些声明中推导得出。 |
| **projection**（投影） | 按需从事件日志和磁盘计算的每条规则状态（valid、stale、failed、blocked、in-flight 或 missing）。从不存储。 |
