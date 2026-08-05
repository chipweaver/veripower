# 失败路由 v2 · 设计与验收

> **这是什么**:重写后的失败路由。判据与基线见 `00-scenario-space.md`,这里讲改了什么、为什么、以及验收结果。
> **落地范围**:`framework/scripts/{schedule,facts,rules}.py` + 三个 stage skill 的措辞 + `design-flow` 的循环不变量 + 一个场景测试。**事件 schema 未改,旧日志向前兼容。**
> **日期**:2026-08-04。

---

## 1. 一个概念:申诉(complaint)

一条 proof 的最新 outcome 是 fail,就是一条**申诉**。它**开着**,当且仅当"还有一件具体的事没做":

| | 判据 |
|---|---|
| 判决还算数 | `facts.verdict_trustworthy` —— §4.4 的条件 3、4(自身产物未漂 + 判它的 oracle 仍站得住) |
| **有主** | 开着,直到那个 owner **被派过**(`_answered`)。**输入漂移不关闭它。** |
| **无主** | 由输入漂移关闭 —— 能做的事只剩 triage 或找人,而漂移已经让他们要看的证据变了 |

**唯一吃重的地方是那条不对称**:兄弟修复漂掉了一条失败的输入,并不代表它的 fix owner 不用干活了。老代码把"输入漂了"当成"这条失败作废",于是一条**写在磁盘上、合法、且没人答复过**的归因被丢掉,然后靠再跑一次那个昂贵的 stage 重新发现一遍。基线里 **96/118 个双缺陷 episode 的每一次额外重跑,都恰好可以追溯到一次这样的结论丢失**。

`_fail_is_fresh` 里除条件 3/4 之外的东西(条件 2 和传递输入闭包检查)整个删掉:上游还没稳,表现为 owner 不可用或非闭包极小,候选过滤器已经说了这件事,说第二遍的代价是丢掉归因。

## 2. 一对字段:`(attribution, fix_owner)`

两条归因通道(信封自述 / diagnosis 事件)收敛成一个函数 `_attribution` 的一对返回值:`attribution` 是原样写下的,`fix_owner` 是它的**可路由投影**(合法 + 对 diagnosis 而言可靠)。后来的分析压过当场的自述。四种升级理由(未指名 / 自指 / 越界 / 归因不可靠)不再是四个分支,而是这对值的四种读法(`_escalation`)。

**这是内聚,不是削减 —— 字段一个都没少。** 实测两版归因路径读到的原始字段:v1 十一个,v2 十二个(多的那个是 v2 自己的内部键)。变的是它们**只在一个函数里被读**,决策逻辑消费的是那对派生值;v1 里同一批字段散在 `_disposition` 的十个分支、`_declared_owner`、`_reliable` 三处各读各的。

同样要说清:`schedule.py` 的 if 分支总数 44 → 42,几乎没动。真正塌掉的是**第二座山** —— `_disposition` 那棵 98 行、10 个 return 的决策树没有了(圈复杂度 19 → 该位置最大 9)。

## 3. 一个候选集

返修与前向是同一件事:**派一个规则,把它欠的申诉一并交给它**。所以 step 1/step 2 合并了:

```
候选 = 有主申诉的 owner ∪ 无主申诉声明的 triage ∪ 前向 work(含重建闭包)
过滤   自身有开着的申诉 → 不派(重验一个没人答复的失败,就是花一轮重新发现已经写下来的东西)
       输入不可用 → 不派
       反链:在途集不得存在闭包关系(两个方向、传递)
       advisory:前驱无效且"真的会来"才压住(自身被挡住的前驱不算会来)
排序   闭包极小 → 先答申诉后建 → task 先于 main-thread → FORWARD_PRIORITY
派发   caused_by = 它拥有的全部开着的申诉;diagnosis_refs 同理
```

四条老机制被这一个集合吃掉:`_disposition` 的 10 个分支、两个各漏一半的合并筛子、`_defer_to_forward`、`_has_inflight_consumer`。`Rule.triage` 让 `schedule.py` 里唯一的规则名字面量(`rule == "simulation"`)消失。

**反链**是新的不变量,也补上了一个之前谁都没守的方向:老代码只有 Option C 挡"消费者在途时别重 promote",而且只看直接消费者;"生产者在途时消费者仍被准入"完全没人管 —— 基线里 **17/17 全部准入**,消费者基于一份即将改变的输入跑完一整轮。

## 4. 实现过程中被基线抓出来的两个 bug

两个都是我自己在 v2 里引入的,靠 135 个 episode 的下界对照抓出来:

1. **`task` 优先把下游 owner 排到了上游前面。** synthesis(task)排在 specification(main-thread)之前 → spec 的修复落地后 synthesis 白跑一轮(+40min × 10 个 episode)。修法:先取**闭包极小**的候选,剩下的必然是反链,在反链上重排才不改变任何本来有序的东西。
2. **advisory 门被一个永远不会说话的前驱卡住。** lint-cdc 无主失败(等人)时,synthesis 被 advisory 压住 —— 而 lint-cdc 已经被"自身有开着的申诉"挡在候选集外,永远不会跑。修法:`coming` 减去这些规则。这正是 `_held_by_advisory` 自己文档里写的前提("不会来的前驱不该压住任何人"),只是 v2 之前没有"被挡住"这种状态。

## 5. 验收

### 5.1 出口判据(135 个 episode,诚实执行器)

| # | 判据 | baseline | v2 |
|---|---|---:|---:|
| E1 | 任务不丢:收敛 | 135 | **135** |
| E2 | 结论不丢:每次失败的信封都送达过 owner 的 `dispatch.json` | 39 | **135** |
| E3 | 形态正确:同 owner 合并一轮,不同 owner 各自一轮 | 121 | **135** |
| E4 | 无额外重跑:每个缺陷只失败一次 | 39 | **135** |
| E6 | 最近注入:失败到交付之间 owner 没白跑过 | 39 | **135** |
| E5 | 无额外轮次:总轮数 == registry 下界 | 37 | **135** |

```
episode_report.py --tag baseline --diff v2
  better=98  same=37  worse=0
  总浪费 12220 min → 0 min
```

**118 个双缺陷 episode 全部跑在 registry 下界上,没有一格变差。**

> **2026-08-05 更新**:episode 集补上 triage 通路后扩到 180 个,并按 §9 的裁决落了最终模型。最终成绩 **E1–E6 全部 180/180**,`--diff` better=33 / same=147 / **worse=0**,总浪费再降 4960min → 0。逐节说明见 [`03-v2-as-built.md`](03-v2-as-built.md) §8。

### 5.2 状态网格(1781 个场景)

| # | 性质 | baseline | v2 |
|---|---|---:|---:|
| A1 | 在途集是闭包上的反链 | 23 | **0** |
| A3 | 同 owner 的两条失败合并为一次 dispatch | 94 | **0** |
| A4 | 不可路由的失败不挡可路由的 | 348 | ~~0~~ ← 此性质已按裁决**退休**,见 §9 第 5 项 |
| A7 | 能并行就要并行派 | 48 | **0** |
| A6 | 修复未答复前不重验该规则 | 0 | **0** |
| A0 | 合法结论被交付 | 718 | 220 |
| A2 | 带合法 owner 的失败被答复 | 624 | 220 |
| A5 | 可靠归因被引用 | 359 | 110 |

A0/A2/A5 的残差**全部**是同一件事,且是正确行为:220/232 是"与本轮已派出的规则有闭包关系,反链把它推到下一回合"—— 交付发生在下一轮,E2=135/135 证明它一定落地。(A0/A2/A4/A5 的适用条件也已收紧成"owner 本轮真的可启动",baseline 数字按同一定义重算过。)

并行方面:

| 场景族 | baseline | v2 |
|---|---|---|
| 前向独立对同回合开两个 | 9/11(2 对 advisory 豁免) | **9/9 + 2 豁免**,墙钟重叠 5 → **8** |
| 在途准入(独立) | 22/22 | 22/22 |
| 在途准入(有闭包关系) | **34 准入 / 0 拦住** ← 越权 | **0 准入 / 34 拦住** |
| 返修两 owner 独立时并行派 | **0/48** | **48/48** |

### 5.3 逐轮对照(真代码,v1 用 `0065bf5` 的独立 worktree 跑)

**同一个 owner 的三种形状** —— 一个回合内 owner 收到了哪几份信封:

| 形状 | v1 收到 | v2 收到 |
|---|---|---|
| A 两条都是信封自述(`lint-cdc` + `synthesis` 都指 `rtl-design`) | `[lint-cdc:2, synthesis:2]` | 同 |
| **B 混合来源**(`lint-cdc` 信封 + `simulation` 的 triage 归因,同指 `rtl-design`) | `[lint-cdc:2]` | `[lint-cdc:2, simulation:2]` + `refs=[diag]` |
| **C 配对有闭包关系**(`rtl-design` 与 `lint-cdc` 都指 `specification`) | `[rtl-design:2]` | `[rtl-design:2, lint-cdc:2]` |

A 是 v1 本来就正确的那一档(基线 33 个同 owner episode 里干净的 19 个)。丢失发生在 B(两个合并筛子各漏一半,38 格)与 C(靠下游那条被 `_fail_is_fresh` 判 stale,根本不进 `fresh` 列表,56 格)。

**两个 owner 有闭包关系**(`lint-cdc → specification`,`simulation → rtl-design`),跑到收口:

```
v1 · 11 轮
  spec:2 ←[lint-cdc:2]   plan:2   rtl-design:2 ←(盲)   lint-cdc:3   simulation:3(白跑,又失败)
  rtl-design:3 ←[simulation:3]    simulation:4   lint-cdc:4   syn:2  timing:2  power:2

v2 · 8 轮
  spec:2 ←[lint-cdc:2]   rtl-design:2 ←[simulation:2]   lint-cdc:3   plan:2   simulation:3
  syn:2  timing:2  power:2
```

v1 的 `rtl-design:2` 是盲重建:sim 的申诉在 spec 修完后被判 stale 丢弃,于是要花一整轮 `simulation`(54min)重新问出来,再补一轮 `rtl-design` 和一轮 `lint-cdc`。v2 里 `rtl-design:2` 这一轮**本来就要跑**(spec 改了),只是顺手挂上了 `simulation:2` 的信封 —— `dispatch.json` 同时带 `scope`(漂掉的 spec 输入)和 `caused_by`(sim 的失败信封)。

**一个先结束怎么办**:`decide` step 0 的 ready 扫描对**任何**在途 run 生效,谁先写出 `result.json` 就先 `REAP` 谁(多个同时就绪按 `FORWARD_PRIORITY` 取最前),收完继续 loop。这一段 v1/v2 逐字相同。差别在于 v1 很少有两个可等 —— 同样的状态(两条失败、两个独立 owner)v1 一个回合只派得出一个,v2 派出两个。

## 6. 执行侧:契约 + 场景测试

`decide` 仍然一次一个动作,并行只来自"`task` 立即返回 + 只有 YIELD/DONE/ESCALATE 结束回合"。这一层是**模型行为**,harness 摸不到,所以配套做了两件事:

1. `design-flow/SKILL.md` 明写不变量:一个回合持有多个在途 run 是常态,后台 dispatch **不是**停止点;`YIELD` 才是"现在开始等"的样子。同时说明 `DISPATCH` 可能带 `escalations[]`(不可路由的失败不再挡住能干的活,但必须在同一回合原样报给用户)。
2. `tests/scenarios/design-flow/scenario-03-keep-looping-after-background-dispatch.md`,按 RED/GREEN 仪式实测:
   - **RED 5×:5 次全违规**(全部选 B——就地收尾),理由高度一致:"lint 可能让 RTL 变,先别起 simulation"——即编排器自行代替 advisory 门做省算力判断。
   - **GREEN 8×:0 次违规**(6 次 A,2 次 REVIEW_NEEDED,后者的 transcript 显示它直接去执行 `decide`、被 `--allowedTools ""` 的权限门挡住,行为上就是 A)。

三个 stage skill(`specification` / `simulation-plan` / `rtl-design`)的 `caused_by` 措辞同步改了:它不再等价于"这是返修轮",而是"有失败的信封在等这个 stage",可以和 `scope`(上游漂移)同时出现 —— 那正是 v2 让级联轮不再盲目的方式。

## 7. 字段审计:哪些是承重的,哪些只做审计

重构时按"每个字段谁读"过了一遍(grep 出读点,不靠记忆)。结论:除一个死字段外,没有可删的;但有六个字段**机器零读点**,它们的价值在人身上。文档必须点名,否则下一个人会试图让它们承重。

| 字段 | 机器读点 | 为什么留着 |
|---|---:|---|
| `dispatch.caused_by` / `.diagnosis_refs`(事件里那份) | 0 | 同一份信息经 `dispatch.json` 到达 stage;事件里这份是给日志读者的因果链 |
| `outcome.reason`(blocked 子类) | 0 | `missing` 与 `schema_violation` 的区别是"执行器死了"还是"stage 写了垃圾" |
| `diagnosis.evidence` | 0 | 分析结论的出处;triage 的由内核合成,human 的由 `--evidence` 必填 |
| `diagnosis.provenance` | 0 | 只在写入时校验非空 —— 谁为这条归因背书 |
| `stage_specific.fail_reason` | 0 | 指名 `fix_owner` 的理由。归因有作者、有账可查,是它相对"一张映射表"的全部优势 |

**唯一删掉的**:`Rule.stage` —— 9 条规则里逐条等于 `name`,全仓库零引用。

一处必须写死的语义:`_answered` 判的是"**owner 被派过**",不是"被 `caused_by` 点名过"。改成后者会把"那个 stage 有没有轮到过"偷换成"有没有被正式点名",于是一次因别的原因重建 owner 的轮次不再关闭申诉,同一个缺陷会被派两遍。

## 8. 兼容性与边界

- **事件 schema 未改**,旧 `events.jsonl` 直接可读;`stage_specific.fix_owner` 的 stage 契约一字未动(只是改由谁来读它的**时机**)。
- `schedule._fail_is_fresh` 删除,`facts.proof_fresh_except_verdict` 拆成 `verdict_trustworthy` + `inputs_unchanged`(前者是新的公开查询)。仓库内 6 个直接调用旧内部函数的测试已按 v2 词汇改写;**没有一个行为断言需要放宽**。
- 未覆盖:三条以上同时失败、blocked/死 run 的路由、多 module 并发、真信封字节。`Rule.triage` 目前没有重试上限(retrospective §7-7,用户已说明不是当前关注点)——加上限现在是一个字段的事。

---

## 9. 设计裁决记录(2026-08-05,与芯片设计师逐项走查)

七项改动逐项过案例,由设计师用真实流程经验判定。**第 5 项被推翻**,其余采纳。

| 项 | 改动 | 裁决 | 依据(设计师原话要点) |
|---|---|---|---|
| 1 | 失败结论不随输入漂移一起丢 | 采纳 | 两条独立的 fail,结论都成立;**两边都应该拿到 fail 信息判断是否要修改** |
| 2 | 同 owner 的多条失败合并成一轮 | 采纳 | 合成一轮给,**获取所有可能的反馈,一起综合解决**;混合来源(信封 + triage 归因)这种形状**常见** |
| 3 | 级联/前向轮也挂 `caused_by` | 采纳 | 都交给 stage —— **stage 自身是它产出的 owner**,需要都给它作为判断依据 |
| 3b | 上下游 owner 的先后 | 上游先改 | **上游都是下游的来源**,就算先解自身,最后还是要回到上游改再自己过一遍;而且**上游改完可能顺带否定掉自己这个问题** |
| 4 | 反链两个方向都从严 | 采纳 | RTL 重写时不起综合/lint(**除非人要求** —— 那属于手工探索,不进内核调度);**消费者在途要等它结束**,结束后如果 fail 再由 decide 重新判 |
| 5 | 不可路由的失败不挡可路由的 | **推翻** | **优先人判**:必须澄清了 fix_owner 之后,再按统一策略决定走哪个阶段,**这样避免分支**。只要触发 escalate 就等人回复 |
| 5b | ESCALATE 一次报几条 | 一次一条 | 说不清的失败只发生在并行阶段,**并行任务返回时机不一致,机制上一次只会发现一个** |
| 6 | 排序(先答申诉 → task 先起) | 采纳 | 符合预期 |
| 6b | 回归要不要等 lint 过 | 并行跑 | **回归和 lint 并行跑** —— 不加 `simulation` 的 advisory 边 |
| 7 | triage 进注册表 | 采纳 | 需要指明消费 sim;triage **只看当次失败的波形和日志**,不需要上一次通过的 run 做对比 |
| 7b | triage 重试上限 | 不设 | **继续让它试,除非人自己介入**,不需要独立上限 |
| 7c | 低置信归因 | 交给人 | 低置信度交给人 |

第 5 项的推翻带来的删除项已并入 [`03-v2-as-built.md`](03-v2-as-built.md) §7:动作上的 `escalations[]`、`_dispatch_action` 的 `unowned` 分支、`_settle` 的顺序讲究、`design-flow/SKILL.md` 里那段上报要求,以及**状态网格 A4 这条性质本身** —— 它是度量阶段发明的判据,与最终策略相反,随之退休。
