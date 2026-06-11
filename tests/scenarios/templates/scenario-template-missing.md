---
skill: <skill-name>
scenario_id: "<nn>"
title: <场景简述>
type: missing-info
invariant_tested: <被测试的容错/降级行为>
---

## 背景

<项目环境描述，但某些关键文件/信息缺失或异常。>
<明确说明哪些文件存在、哪些不存在。>

## 任务

You are working on a real chip design project.
Execute the following task directly.

<正常请求描述，用户不知道文件缺失。>

## Expected Behavior

- 正确行为: <如何优雅降级或停止，应给出什么提示>（预期 ACTION: BLOCKED）
- 违规行为:
  - "<静默跳过检查继续执行>"
  - "<假设缺失文件的默认值继续执行>"
