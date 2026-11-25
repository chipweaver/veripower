# OpenCode 1.19.0 小模块完整流程实验

日期：2026-11-25。结论：**完整流程通过**。独立核对结果为八个 stage proofs 全部
`valid`，`decide --closing` 返回 `DONE`，`signed_off: true`；原生宿主没有仍在执行的会话。

本实验补齐[此前分项验证](opencode-v1-2026-11-25.zh.md)没有建立的完整流程证据。
全部阶段由真实模型通过安装后的 OpenCode v1.19.0 适配执行，使用实际设计、验证和
EDA 工具产物；没有把环境 smoke 或脚本化模型响应作为阶段结果。

## 实验输入与环境

- VeriPower 分支 `opencode-v1`，运行代码提交 `2ed6c4a`，通过 `npm pack` 产物安装。
  本次没有修改共享 kernel、skills 或适配运行代码。
- 平台 OpenCode `1.19.0`；真实模型请求 `deepseek/deepseek-flash`。
- 原生父会话 `ses_dee4431b5ffeROeAr2n55pJ3ch`，从新会话开始，不继承此前调研和局部实验讨论。
- 工作区 `/home/mhc/veripower-opencode-v1-e2e`，模块 `counter4/`。EDA 容器已直接验证能
  读取该模块；所有阶段工作目录处于容器挂载的 `/home/mhc` 下。
- 原始输入是 `counter4/intent/brainstorm.md` 和 `eda-resources.md`，没有预制 RTL、TB 或
  成功结果。输入指纹为
  `merkle:75b4396d8829c7cd64b5684713070c0f84373e93f3e9b7be257cababae20fa3d`。

模块是单时钟、4 位、带使能、异步低有效复位的模 16 计数器。功能要求包含初始化、
异步复位、复位优先、保持、递增、全部计数值、回卷和运行中重复复位。

时序合同：10 ns 时钟；en 输入时延 max/min 为 0.5/0.2 ns，count 输出时延 max/min 为
0.2/0 ns；clock uncertainty 0.05 ns，时钟/输入 transition 0.1 ns，输出负载 0.01 pF。
采用 slow 标准单元库、无 wire-load model，setup/hold 必须满足约束。面积和功耗实际
测量，没有数值预算。功耗要求门级实现、匹配的模型和 SDF、真实 SAIF 与 PT-PX，idle
与 active 各在 warm-up 后捕获至少 200 个完整周期。

使用站点已有的 DC L-2016.03-SP1、PT/PX M-2016.12-SP1、VCS/URG L-2016.06、
UVM 1.1、Verdi/FSDB L-2016.06、SpyGlass vL-2016.06 包装器及工具兼容环境。
库和模型为已有 `slow.db`、`tsmc090.v`。没有修改部署配置或安装软件。

## 各阶段的实际结果

以下路径均相对模块根目录；每个阶段的 run 均为 1。修复发生在对应 run 的关闭和
收集之前，保留了独立审查、决定记录及原始日志。

| 阶段 | 结果与关键证据 |
|---|---|
| specification | pass；完成需求账本、边界、时钟和检查提示，独立审查后修复账本遗漏及追溯问题，并取得复核。`Design/specification/spec-review/` |
| simulation-plan | pass；补充真正的 between-edge 异步复位探测、采样约定、功能覆盖收集及功耗窗口语义，独立复核完成。`Verification/simulation-plan/plan-review/` |
| rtl-design | pass；17 行 SystemVerilog 实现，实际 VCS 编译/展开及独立 RTL 审查。`Design/rtl-design/src/counter4.sv`、`semantic-review/` |
| lint-cdc | pass；SpyGlass lint 0 errors / 0 warnings / 4 infos，CDC 0 errors / 0 warnings / 14 infos；没有 waiver，时钟/复位树覆盖四个寄存器。`Design/lint-cdc/evidence/` |
| synthesis | pass；DC 映射为四个时序单元、七个组合单元，总单元面积 **92.4336 µm²**；生成真实网表、SDC 和 SDF。`Design/synthesis/out/`、`reports/area.rpt` |
| timing-analysis | pass；独立 PT setup worst slack **8.968936920166 ns**，hold **0.2259244322777 ns**，均 MET；同步 setup/hold/out 检查无遗漏或违例。`Design/timing-analysis/timing-report.txt` |
| simulation | pass；实际完整 UVM/VCS 回归 **6/6**，requirement-derived RM、真实异步复位探测及独立检查审查；DUT 子树 line/branch/toggle **100%**。`Verification/simulation/` |
| power-analysis | pass；门级 SDF 仿真、两份实际 SAIF、PT-PX 计算和条件分析完成。idle **0.004357 mW**，active **0.007375 mW**。`Verification/power-analysis/` |

物理测量条件为 slow、0.90 V、125°C，pre-layout、无 wire-load model；功耗是捕获窗口
的平均值。异步复位释放由外部在有效边沿之外提供，STA 的复位例外有原始需求依据。

## 原生调度与完成收集

真实 kernel 建立 dispatch，阶段通过所属 CLI 关闭，父会话依据原生执行器完成信息
进行 wake/reap。lint/CDC 后台执行时，主会话进行功能验证；综合后台执行又与功能验证
及其独立审查重叠。timing-analysis 和 power-analysis 也分别通过原生后台 task 执行。
没有以结果文件出现代替宿主的执行器完成确认。

全程保留十二个原生会话（父会话、阶段执行器和独立审查会话）。最终事件历史为：
**8 dispatch、8 pass outcome、1 signoff，共 17 条**，所有派发运行已收集。
`signoff` 的 provenance 明确为意图授权的实验验证 agent，并绑定本次证据。

原始工具与运行产物在模块工作区；原生会话导出和独立复查结果在实验根目录。
`final-status.json` 记录八个 valid 和 `signed_off: true`，`final-closing.json` 记录
`action: DONE` 及八项当前 basis。它们由实验控制侧重新执行真实 kernel 查询获得，
并非复制模型最终回答。

## 实测问题及处理

### 独立审查空返回

首轮规格 reviewer 会话结束但没有报告，原生 task 返回空完成内容。主会话发现缺失
文件，重新委派审查，没有将空返回当作审查通过。第二轮产生实际报告后才继续修复和
复核。报告缺失与重试的原生会话记录均保留。

### 规格与规划的实际缺陷

规格审查发现一项 blocking：账本没有完整转录独立审查及处理发现的义务。主会话补齐，
并修复错误的约束文件名、检查提示关联及数值来源说明，经独立复核后 finalize。

规划审查指出，edge-only RM 不能证明两个时钟边沿之间的复位。修复后的计划和实际 TB
增加 before-next-edge 的异步清零探测，明确 reset dominance、seen-values 收集和稳定
采样窗口；不是以运行更久代替该检查。复核后规划通过，最终回归也实际运行该用例。

### 功耗日志单位错误

独立证据审计发现，门级 TB 在 `1ns/1ps` 下用 `%0t` 输出，却把字段标为 ns，导致
日志出现 `duration_ns=2560000`，与 SAIF 的 `TIMESCALE 1 ns / DURATION 2560` 不一致。
捕获周期和活动本身没有改变，但测量来源说明有误。

父会话核对后，通过原生 task 续接原 power 执行器，由该阶段负责人修复。TB 设置
`$timeformat(-9, 3, " ns", 0)` 并输出显式单位，重新执行 **compile、simulate、calculate**，
更新 analysis 和结果，再进行 kernel 收集及实验接受。最终日志为：

| 场景 | 日志捕获区间 | SAIF | 实际行为 |
|---|---|---|---|
| idle | 170.000–2730.000 ns，2560.000 ns，256 cycles | 1 ns × 2560 | count 保持 5；四个 count 位 TC 均为 0，时钟持续切换 |
| active | 220.000–2780.000 ns，2560.000 ns，256 cycles | 1 ns × 2560 | 每周期递增，16 次回卷；count[0..3] TC 为 256/128/64/32 |

两种场景均在 warm-up 后捕获，状态 PASS 在行为检查及 SAIF 写出后产生。PT-PX 两次均
注解 14/14 nets、11/11 leaf cells；internal、switching、leakage 与总功耗在报告舍入
范围内相符。修复没有改动原始输入、时序合同、捕获要求或预算。

### 工具警告与审查建议的评估

SDF 注解为 0 errors、4 warnings，四条均涉及 XNOR2XL/U16 的额外 edge-style IOPATH。
已独立对照实际 SDF 和 `tsmc090.v`：模型只声明按另一输入 0/1 条件区分的四条路径；
SDF 中对应 conditional IOPATH 均存在并注解，警告的额外 edge-style 路径没有模型
声明。其余十个单元无注解警告，没有以“忽略所有 warning”代替分析。

PT-PX `check_power` 报告四个 out-of-range ramps，没有缺表或缺函数；阶段 analysis
记录了 slew/load 外推对这次平均功耗估计的含义。没有数值功耗预算或 peak-power 结论。

功能覆盖按 DUT 子树判断，没有使用包含 TB 的 aggregate 代替。condition/FSM 无对象
的原因已在独立审查中对照 RTL 和实际 instrumentation 核对；计数值、递增、保持、复位
及回卷的功能检查保留在回归日志中。非阻塞追溯/可观察性建议保留了具体评估。

## 与此前分项问题的关系

此前 v2 安装说明遗留和测试辅助代码 URL 编码比较已在适配提交中修复。本次完整流程
还修复了上述真实阶段工件问题。取消子会话不发送正常完成通知属于 v1.19.0 的宿主
行为，已验证宿主确认退出后显式恢复的路径，没有修改其取消语义。

本次所有阶段直接使用 `/home/mhc` 下的可见工作区，解决了此前 `/tmp` 不在 EDA
容器挂载中的实验条件问题；没有靠把 smoke 结果复制成真实阶段结果来完成验收。

## 证据入口

- 模块原始输入、append-only 事件和全部阶段工件：
  `/home/mhc/veripower-opencode-v1-e2e/counter4/`。
- 最终独立复查：实验根目录的 `final-status.json`、`final-closing.json`；
  原生会话导出为同目录的 `ses_*.json`，凭据不进入仓库。
- 功能回归：`Verification/simulation/case-results.json`、`regression-log.txt`、
  `structural-coverage.json`、`cov_merge/`、`check-review.md`。
- 时序：`Design/timing-analysis/timing-report.txt`、`reports/effective_constraints.sdc`。
- 功耗：`Verification/power-analysis/saif/`、`reports_ptpx/`、`analysis.md`、
  `evidence/sdf_annotation_excerpt.txt`。

原始工作目录与日志留在实验工作区，不提交到插件仓库。本报告保留了输入条件、真实
执行路径、实际问题、修复及最终验收结果。
