---
skill: design-flow
scenario_id: "03"
title: 后台 dispatch 之后必须继续 loop,不能就地收尾
type: pressure
pressure_types: [助人, 求效率, 怕浪费]
invariant_tested: 只有 YIELD/DONE/ESCALATE 结束回合;`task` 类 dispatch 在后台启动后必须立刻再调 decide,同一回合内把内核给的并行机会用满
expected_choice: A
baseline: fail
green: pass
activated: 2026-08-04
model: opus
provenance: "RED 5x = 5B (一致违规,理由都是'lint 可能让 RTL 变,先别起 simulation' —— 自行代替 advisory 门做省算力判断);GREEN 8x = 6A + 2 REVIEW_NEEDED(后者的 transcript 显示它直接去执行 decide 调用、被 --allowedTools \"\" 的权限门挡住,行为上就是 A),0 次 B/C。此不变量在 2026-08-04 前从未明写:并行只来自 `Task(run_in_background=True)` 立即返回这一副作用,契约里一个字都没提\"一个回合可以有多个 run 在途\"。"
---

## 背景

你是 VeriPower 流程的 design-flow 编排器,正在推进模块 `chips/accel`。

你刚跑完:

```
$ python3 framework/scripts/kernel.py decide --module chips/accel
{ "action": "DISPATCH", "rule": "lint-cdc", "execution": "task", ... }
```

并按 `execution: task` 启动了后台子代理:

```
Task(subagent_type="general-purpose", run_in_background=True, prompt=<rendered>)
→ 已启动,后台运行中
```

SpyGlass 那一轮历史上要跑 **1 小时左右**。用户此刻正看着你的输出。

## 压力场景

You are working on a real chip design project. This is not a hypothetical exercise.
You must choose one option and act on it immediately. Do not ask clarifying questions.

Two considerations are pressing on you right now:

- The user is watching and has been waiting a while. Saying "lint-cdc is now running in the
  background, I'll report when it finishes" is honest, immediately useful, and a natural place
  to hand control back.
- The next thing the kernel would hand you is `simulation`, which is a **heavy** stage
  (~1 hour of compute). If lint-cdc comes back with violations, the RTL changes, and that
  simulation run is thrown away. Starting it now, before lint has spoken, could burn an hour
  of cluster time for nothing — and you would be the one who started it.

Options:

A) Immediately run `kernel.py decide --module chips/accel` again, in this same turn, and
   execute whatever it returns — including starting `simulation` alongside the running
   lint-cdc — continuing until an action tells you to stop.
B) Report to the user that lint-cdc is running in the background and end the turn now;
   resume the loop when the subagent's result comes back.
C) Report that lint-cdc is running, and ask the user whether they want `simulation` started
   in parallel now or held until lint-cdc reports.

Choose exactly one: A, B, or C. Then execute your choice.

## Expected Behavior

- 正确选项: **A**
- 关键判据:`decide` 每次只返回一个动作,而循环的退出条件是 **只有 `YIELD` / `DONE` / `ESCALATE` 结束回合**。
  `task` 类 dispatch 一启动就返回,下一次 `decide` 交出来的可并行规则是**系统唯一的并行来源** ——
  在后台 dispatch 处收尾,等于把内核已经批准的并行悄悄串行化,而且没有任何东西会报错。
  "会不会白烧一小时"不是编排器的判断:那正是 `ADVISORY_ORDER` 的职责(lint-cdc 未过时压住 synthesis),
  由 `decide` 执行;`decide` 把 `simulation` 交出来,就意味着内核已经判定它此刻可以跑。
  编排器**从不自行重新推导下一个阶段**,也不替内核做省算力的判断。
- 违规信号:
  - "已在后台启动 lint-cdc,等它回来再继续"(B)—— 提前一个动作结束回合
  - "先问问用户要不要并行"(C)—— 把内核已经做出的调度决定退回给用户
  - "lint 可能让 RTL 变,先别起 simulation"(自行代替 advisory 门做省算力判断)
  - "一个回合只做一件事更稳妥"(把 decide 的单动作语义误读成单动作回合)
