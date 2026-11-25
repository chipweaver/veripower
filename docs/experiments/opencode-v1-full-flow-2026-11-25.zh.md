# OpenCode 1.19.0 完整流程与调度提醒复验

日期：2026-11-25。初版 `2ed6c4a` 完成八阶段流程，但没有触发调度提醒；这不能证明
提醒有效。修正版 `6023c9f` 改用原生后台 task 事件，并进行了新的完整模块实验。
独立核查确认：**八项 proof 全部 valid、closing DONE、signed_off true**。

## 适配缺陷与修正

初版完整实验中，模型用 shell 变量调用 kernel，并在复合命令中输出多段内容。
旧实现按命令正则识别 dispatch，再把整个 stdout 当作 JSON，未能生成提醒。

修正后的 `tool.execute.after` 读取宿主 task 结果的 `metadata.background`，在后台
启动结果后给 VeriPower 编排者追加继续调度的提醒。取消命令解析、历史扫描和适配
状态；没有增加 kernel 字段、schema、兼容路径或权限配置。

提醒的作用是让编排者在启动执行器后查询其他 ready 工作，依据为共享 design-flow
及历史提交 `aa86ba6`。对照 Claude、Codex、DSH 和 OpenCode v2 的组件审视见
[需求与事实](../research/opencode-v1-adaptation.zh.md)。

## 实验条件

- 平台 OpenCode **1.19.0**，真实模型 **deepseek/deepseek-flash**，通过 npm 包安装。
  没有脚本化阶段回答或预制 RTL、TB、成功结果。
- 新实验根目录 `/home/mhc/veripower-opencode-v1-task-hook-e2e`，模块 `counter4/`，
  父会话 `ses_dedf946e2fferZ0x5rQ9xi31fQ`。EDA 可读取整个模块路径。
- 与初版完整实验使用相同的 `intent/brainstorm.md` 和 `eda-resources.md`，输入指纹为
  `merkle:75b4396d8829c7cd64b5684713070c0f84373e93f3e9b7be257cababae20fa3d`。
- 模块为单时钟 4 位使能计数器，异步低有效复位；验证初始化、异步复位、复位优先、
  保持、递增、全部计数值、回卷、运行中重复复位。
- 10 ns 时钟，en 输入时延 max/min 0.5/0.2 ns，count 输出时延 0.2/0 ns；uncertainty
  0.05 ns，clock/input transition 0.1 ns，输出负载 0.01 pF。slow、0.90 V、125°C，
  无 wire-load model；setup/hold 须满足约束，面积和功耗无数值预算。
- 使用实际 DC L-2016.03-SP1、PT/PX M-2016.12-SP1、VCS/URG L-2016.06、UVM 1.1、
  SpyGlass vL-2016.06，以及已有 `slow.db`、`tsmc090.v`。

## 原生行为核查

lint/CDC、synthesis、timing-analysis、power-analysis 四个后台阶段启动结果均带原生
background 标志，且实际模型可见的工具返回中均有提醒。后续 power run 2 的后台返修
也收到提醒，合计五次。lint、timing、power 启动后的下一条 kernel 命令是 decide；synthesis 后因控制侧提出了规划归属审计，先直接
派发 simulation-plan 返修。

父会话在后台阶段运行时推进其他工作，依据原生完成信息收集结果。shell 变量和复合
命令继续正常使用，提醒不再依赖这些写法。

另一个真实会话仅要求两个后台算术任务。工具结果中也有条件性提醒，父会话收齐
338350 和 168 两个正确结果，没有调用 kernel；其工具调用仅为两个 task。
会话为 `ses_dedf88691ffeyU9brIQmHXjISP`。

## 新实验的产物审计

以下问题发生在模型生成的实验工件中；处理通过原有阶段负责人和 kernel 完成，
没有为它们修改 VeriPower 共享运行代码：

- simulation 阶段直接改过已发布规划的硬链接，导致规划 proof 过期。重新派发规划
  run 2，由负责人修订和独立审查，随后 simulation run 2 重新验证。
- 两个独立初始化的测试各做一次运行中复位，不能证明连续运行中的重复复位。
  规划 run 3 经独立审查后，simulation run 3 实测两种 en 测试各有两次运行中复位，
  混合测试有三次，均从非零值发起；修正新测试注册遗漏后重新编译、完整回归，
  独立检查复核确认没有 blocking finding。
- 功耗分析把四条 SDF 警告误称为 conditional arc 不匹配。实际警告对应 U16/XNOR2XL
  的额外 posedge/negedge IOPATH（SDF 第 58、59、62、63 行）；模型声明的是四条
  conditional pin path。PT 的活动注解覆盖率不能替代 SDF timing arc 注解证据。
  power run 2 已按实际行号纠正说明，并重新执行
  compile、simulate、calculate 后关闭和收集。

## 完整流程结果

最终当前运行是 specification 1、simulation-plan 3、rtl-design 1、lint-cdc 1、
synthesis 1、timing-analysis 1、simulation 3、power-analysis 2。
**13 dispatch、13 pass outcome、2 signoff，共 28 条事件**；所有派发均已收集。
第一次 signoff 后发现的产物缺陷经返修关闭，第二次 signoff 绑定修订后的当前证据。
控制侧重新执行真实 kernel 查询，独立保存 `final-status.json` 与 `final-closing.json`，
确认八项 valid、DONE、signed_off true；原生宿主无活动会话，原始 intent 字节未改。

## 实际测量

| 项目 | 结果与证据（模块内路径） |
|---|---|
| 功能回归 | 7/7；两种 en 测试各两次复位、混合测试三次，UVM error/fatal 为 0；`Verification/simulation/runs/3/logs/` |
| DUT 覆盖率 | line/branch/toggle 均 100%，condition/FSM 无对象；`Verification/simulation/runs/3/structural-coverage.json` |
| 综合面积 | 92.4336 µm²；4 个时序单元、7 个组合单元，`Design/synthesis/reports/area.rpt` |
| setup / hold | 8.968936920166 / 0.2259244322777 ns，均 MET；`Design/timing-analysis/timing-report.txt` |
| idle 平均功耗 | 0.004338 mW；`Verification/power-analysis/reports_ptpx/idle/` |
| active 平均功耗 | 0.007386 mW；`Verification/power-analysis/reports_ptpx/active/` |

功耗来自综合网表、匹配标准单元模型及 SDF 的实际门级 SAIF，再由 PT-PX 计算。
两场景均 warm-up 20 周期后采集 2196 ns（220 个采样上升沿，超过要求的 200 个完整
10 ns 周期）。idle 从非零值 11 保持、数据 TC 为 0；active 每周期检查模 16 递增，
count 位 TC 为 220/110/55/27，覆盖多次回卷。

SDF 注解日志为 0 errors、4 warnings。clk-to-Q 延迟探针为 8/8；无 SDF 的对照探针
失败，证明该探针能识别实际注解。PT-PX 活动注解为 14/14 nets、11/11 leaf cells。
平均功耗的条件为 pre-layout、slow、无 wire-load，不代表瞬时峰值或 IR drop。

## 自动检查与证据位置

- 单元与契约：**1156 passed、31 skipped**；pre-commit 全部通过。
- OpenCode 原生脚本化测试：**5 passed**，覆盖允许、拒绝、审批拒绝、取消后恢复和
  后台能力关闭。修正后提示在真实 task 结果中持久保存；基础工具映射仍为系统上下文。
  最新记录 `/tmp/veripower-oc119-native-event-checked/`。
- 新实验原始事件、阶段产物位于上述模块目录；原生会话导出在实验根目录 `ses_*.json`。
  最终 kernel status / closing 已在所有返修完成后独立保存。

完整实验启动时的 adapter 与 `6023c9f` 只差空结果访问判定：v1 的 subtask 失败路径可能给
后置 hook 传入 undefined，最终代码对此不发提醒；五项原生检查使用最终代码。
正常后台结果的处理相同，没有改动实验运行中的安装文件。全部阶段退出后，改装最终
代码包、重启服务器并续接同一父会话：12 个 VeriPower 技能均来自新安装路径，实际
加载的 adapter 与 `6023c9f` 字节相同；新后台一致性检查收到提醒，父会话随后 decide，
收齐完成信息后确认八项 result 与 outcome 哈希、proof basis 一致，仍为 DONE。
该恢复检查没有修改文件、派发阶段或重跑 EDA。总计 21 个原生会话，六次后台启动
均收到提醒；最终独立核查通过后已停止本次实验服务器。

初版完整实验仍保留在 `/home/mhc/veripower-opencode-v1-e2e/counter4/`：8 dispatch、
8 pass outcome、1 signoff，八项 valid、closing DONE。其功耗日志单位错误已由当时的
power 执行器设置 `$timeformat` 并重跑 compile/simulate/calculate 修正，最终两场景
均捕获 2560 ns；idle/active 为 0.004357/0.007375 mW。该记录不用于证明旧提醒有效。
安装、权限和生命周期的其他实测见[分项报告](opencode-v1-2026-11-25.zh.md)。

原始产物与会话保留在本机，不提交到插件仓库。
