<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-text-dark.png">
    <img alt="VeriPower" src="assets/logo-text-light.png" width="320">
  </picture>
</p>

<h3 align="center">面向 coding agent 的芯片前端设计与验证</h3>

<p align="center"><a href="README.md">English</a> | 中文</p>

---

VeriPower 是面向 coding agent 的开源芯片前端开发插件，**支持从原始需求出发，协同开展设计、验证与功耗、性能、面积（PPA）评估**。它以完整交付为目标，推动实现及其检验成果共同满足任务要求。

VeriPower 接入 Claude Code、OpenCode、DeepSeek Harness、Codex 等 agent harness，将领域 skills 的专业指导与流程引擎的跨阶段协调结合，**使设计与检验在持续反馈和关联修订中围绕共同需求协同演进。**

<p align="center">
  <a href="assets/veripower-methodology-and-mechanisms.png">
    <img src="assets/veripower-methodology-and-mechanisms.png" alt="设计与检验围绕共同需求协同演进；编排 agent 与流程引擎协调多轮任务执行" width="960">
  </a>
  <br>
  <sub>开发方法与执行机制 · <a href="assets/veripower-methodology-and-mechanisms.png">查看原图</a></sub>
</p>

## 核心能力

- **设计论证与早期反馈。** 规格与 RTL 实现任务从功能要求与 PPA 目标出发，结合自顶向下的需求细化与自底向上的可行性分析，论证结构选择和资源取舍。验证规划与独立评审在方案细化过程中及早提供反馈，支持设计选择的确认与修订。
- **需求驱动验证。** 以原始需求和独立参考材料建立测试点、参考模型与判定依据。功能仿真、lint/CDC、综合、时序和功耗分析检查功能及工程指标；独立评审核查激励、观测和检查逻辑能否检出不符合要求的行为并触发失败判定。
- **诊断与关联修订。** 执行者结合成因诊断与修改影响评估，确定负责修改的任务，并分析修订对其他要求及成果配套关系的影响。由负责相应成果的任务实施修订，并协调受影响的工作。

流程引擎使各轮工作有序衔接。**它依据成果依赖协调执行，维护检验结论与成果版本的对应关系，识别需要重新评估的工作，并保留仍然适用的通过结果**。成果与运行记录保存在模块工作目录中，支持跨会话继续开发。

**交付内容包括规格、RTL、UVM 验证环境、约束、综合网表，以及验证和分析报告。**

## 运行条件

Agent 使用的执行环境需要具备：

- Python 3.10 或更高版本，以及 [requirements.txt](requirements.txt) 中列出的依赖。
- **完整流程所需的 Synopsys SpyGlass、VCS/UVM、Verdi 波形工具、Design Compiler 和 PrimeTime，以及相应许可证和单元库**。具体配置见 [EDA 环境说明](docs/eda-env.zh.md)。

开始开发前，可以在独立会话中使用 `env-precheck` skill，检查工具和许可证是否可用。

## 快速开始

1. **安装并启用 VeriPower。** 按所用平台的指南操作：[Claude Code](.claude/README.md)、[OpenCode](.opencode/README.md)、[DeepSeek Harness](.dsh/README.md) 或 [Codex](.codex-plugin/README.md)。开启会话，让 agent 列出 VeriPower skills，确认插件已加载。

2. **准备原始需求。** 将需求保存为 `{module_dir}/intent/brainstorm.md`，引用材料复制到 `{module_dir}/intent/`。`{module_dir}` 表示模块工作目录的绝对路径。已有合适规格可以直接使用；需要讨论需求时，在独立会话中使用 `brainstorm` skill，并在开始流程前复核生成的文档。

3. **开启已启用 VeriPower 的新会话，提出：**

    > 为 {module_dir} 运行 design-flow skill。

Agent 在已有授权范围内继续工作，需要你补充信息或作出决定时再提出。发布的成果位于模块工作目录下的 `Design/` 和 `Verification/`。

## 文档导航

- [用户指南](docs/USER-MANUAL.zh.md)：准备输入、跟进进度、复核成果、修订需求及恢复中断的工作。
- [架构文档](docs/ARCHITECTURE.zh.md)：开发方法、任务职责与多轮开发的协调机制。
- [Contributing](CONTRIBUTING.md)：开发原则与验证要求。

版本： v0.2.10 · [MIT 许可证](LICENSE) · [问题反馈](https://github.com/chipweaver/veripower/issues)
