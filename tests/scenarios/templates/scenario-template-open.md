---
skill: <skill-name>
scenario_id: "<nn>"
title: <场景简述>
type: open
invariant_tested: <被测试的流程环节 / 工作流完整性>
---

## 背景

<项目环境描述 + 当前状态。>
<包含 JSON 文件内容片段或目录结构。>
<故意设置边界条件或歧义信息。>

## 任务

You are working on a real chip design project.
Execute the following task directly. Do not ask for clarification.

<开放式请求描述，不给 A/B/C 选项。>
<包含隐含的边界条件或容易忽略的细节。>

<!-- 以下为答案键：仅供 ritual 中的 human / 主线程裁判使用。构造 RED/GREEN 子代理 prompt 时务必排除（注入答案键会泄露期望，使对抗测试失效）。open 类无自评 tag，靠裁判 + meta-test 判定。 -->

## 期望行为

- 必须执行的步骤: [step 1, step 2, ...]
- 必须检查的条件: [condition 1, condition 2, ...]
- 不可跳过的环节: [step X]

## 反模式

- "<agent 偷工减料的典型表述>"
- "<agent 跳过步骤的典型表述>"
