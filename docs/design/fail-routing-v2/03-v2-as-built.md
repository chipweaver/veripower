# v2 原样:现在 VeriPower 在 flow 上是怎么处理的

> **这是什么**:重构后失败路由与并行调度的完整说明,和 [`02-v1-as-built.md`](02-v1-as-built.md) 一一对照着读。
> **为什么**:`01-v2-design.md` 讲"改了什么、为什么、验收多少";这份讲"现在到底怎么跑",给要改代码或要 debug 一次真实回合的人。
> **范围**:`schedule.py` 全部 + `facts.py` / `rules.py` 里被它读到的部分。日志格式、内核动词、stage 信封契约与 v1 相同,不重复。

---

## 1. 地基没变

事件日志仍是唯一的持久状态,`kernel.py` 仍是唯一写者,`decide` 仍是 (磁盘, 日志, 参数) 的纯函数、一次返回一个动作。五个脚本的分工与 `02-v1-as-built.md` §1–§2 逐条相同,唯一的注册表变化:

| | v1 | v2 |
|---|---|---|
| `Rule.stage` | 有(9 条里逐条 == `name`,零读者) | **删了** |
| `Rule.triage` | 无(`schedule.py` 里硬编码 `rule == "simulation"`) | **有** —— 哪个 stage 背后有分析器是注册表事实 |

## 2. 一个概念:申诉(complaint)

**一条 proof 的最新 outcome 是 fail,就是一条申诉。** 它**开着**,当且仅当"还有一件具体的事没做":

```
complaints(module, events) —— 按 FORWARD_PRIORITY 顺序,逐条 proof 问三个问题

  ① 判决还算数吗?          facts.verdict_trustworthy = §4.4 的条件 3、4
                             条件3 判它的 oracle 没有在这一轮 dispatch 之后被 reopen(且未重新 pin)
                             条件4 这一轮自己的产物指纹 == 磁盘
        不算数 → 关闭(oracle 被撤回,这条判决不再是证据)

  ② 谁必须动手?            _attribution() → (attribution, owner, diagnoses, unreliable)

  ③ 那件事做了吗?
        有主 → _answered:这次失败之后,owner 被派过吗?
                  派过(在途或已 reap 非 blocked) → 关闭
                  没派过                          → 开着 ●
        无主 → facts.inputs_unchanged:它记录的输入还和磁盘一致吗?
                  一致 → 开着 ●(证据还在,triage 或人可以看)
                  漂了 → 关闭(能看的证据变了,交给前向重验)
```

**唯一吃重的地方是有主/无主那条不对称**:

- **有主**的关闭条件是"owner 被派过",**与输入是否漂移无关**。兄弟修复漂掉了这条失败的输入,不代表它的 fix owner 不用干活了。v1 把"输入漂了"当成"这条失败作废",于是一条写在磁盘上、合法、且没人答复过的归因被丢掉,再靠重跑那个昂贵的 stage 重新发现一遍。
- **无主**反过来由输入漂移关闭:能做的事只剩 triage 或找人,而漂移已经让他们要看的证据变了;此时重验是最便宜的、语义明确的动作。

`_answered` 判的是"**被派过**",不是"被 `caused_by` 点名过"。因为问题是"那个必须动手的 stage 有没有轮到过"——一次因别的原因重建 owner 的轮次同样给过它机会,再问一次就是同一个缺陷派两遍。唯一的例外是 reap 成 `blocked`:什么都没落成,申诉重新打开(而不是被一个死掉的执行器悄悄吃掉)。

## 3. 一对字段:`(attribution, fix_owner)`

```python
_attribution(module, events, rule, outcome) -> {
    "attribution": …,   # 原样写下来的指名(可能非法、可能是 None)
    "owner":       …,   # 它的可路由投影:合法 且(对 diagnosis)可靠,否则 None
    "diagnoses":   [],  # 支撑这个 owner 的可靠归因,给 --diagnosis-refs
    "unreliable":  [],  # 不可靠的归因,给 ESCALATE 的 candidates
}
```

两条通道,一个优先级规则 —— **后来的分析压过当场的自述**:

```
有 active diagnosis?(subject 匹配这次 outcome 的 run、未被 supersede)
  ├ 有:最新那条说了算
  │     _reliable(它)? = 有 fix_owner 且 (source==human 或 confidence==high)
  │        可靠   → owner = 它的 fix_owner;diagnoses = 同 owner 的全部可靠归因
  │        不可靠 → owner = None;unreliable = 全部候选(交给人)
  └ 没有:读失败规则 canonical result.json 的 stage_specific.fix_owner(原样)
            owner = 它,当且仅当 _legal:非空 且 ∈ input_closure(失败的规则)
```

读 canonical 是安全的:申诉只在"这次失败仍是该规则**最新** outcome"期间存在,而 fail 会 promote,所以 canonical 里就是这一轮的信封。(`blocked` 不 promote,也不产生申诉。)

**四种升级理由是这对值的四种读法**(`_escalation`),不是四个分支:

| `attribution` | `owner` | 理由 |
|---|---|---|
| 有 unreliable 归因 | None | `unreliable diagnosis for <rule>` + `candidates[]` |
| `None` | None | `<rule>: envelope named no fix_owner` |
| == 失败的规则自己 | None | `<rule>: fix_owner is itself, in-stage remedy exhausted` |
| 闭包外的某个规则 | None | `<rule>: fix_owner '<x>' is outside its input closure` |

**这不是字段削减**:两版归因路径读到的原始字段一样多(v1 十一个,v2 十二个)。变的是它们只在这一个函数里被读。

## 4. `decide`:四步,四个函数

```python
def decide(module, *, wake=None, closing=False):
    events   = facts.read_events(module)
    inflight = facts.in_flight(events)

    reap = _ready_to_reap(module, events, inflight, wake)        # step 0
    if reap: return reap

    open_ = complaints(module, events)                          # step 1
    repair, triage, unowned = _group(open_)

    required   = required_proofs(events)
    complained = {c["rule"] for c in open_}
    candidates = _candidates(module, events, inflight, repair, triage,
                             complained, _forward_work(module, events, required))
    if candidates:                                              # step 2
        return _dispatch_action(module, candidates[0], repair, triage, unowned)

    return _settle(module, events, inflight, required, unowned, closing)  # step 3
```

四步各一个具名函数,优先级顺序就是全部控制流。最大圈复杂度 9(v1 是 34)。

### step 0 `_ready_to_reap` —— 先收口

和 v1 逐字相同:`--wake <rule>:<run>` 命中在途 → `REAP`;否则扫描所有在途 run 的 workdir,谁写出了 `result.json` 就收谁(多个同时就绪按 `FORWARD_PRIORITY` 取最前)。

`--wake` 唯一不可替代的用途:执行器死了、没写 `result.json`,扫描看不见它,只有 `--wake` 能把它收成 `blocked` 解开日志。

### step 1 `_group` —— 按"谁必须动手"分组

```
repair  : {owner → [它欠的申诉…]}      ← groupby,不是"合并规则"
triage  : {Rule.triage → [无主且没人分析过的申诉…]}
unowned : [无主的申诉…]                ← 挂到动作的 escalations 上
```

**"同 owner 的多条失败合并成一次 dispatch"是分组的直接结果**,没有一条可以只实现一半的规则。v1 是两个各漏一半的筛子(信封分支跳过带 diagnosis 的兄弟,diagnosis 分支只收有可靠归因的兄弟)。

无主申诉进 `triage` 的条件多一条:**这条失败还没人分析过**(`not c["unreliable"]`)。分析回来说不可靠,那是人的事;拿同一份证据再跑一遍同一个分析器只会复现它。

### step 2 `_candidates` + `_dispatch_action` —— 一个候选集

**返修和前向是同一件事**:派一个规则,把它欠的申诉一并交给它。所以只有一个集合、一次排序:

```
候选池 = repair.keys ∪ triage.keys ∪ work        work = 目标集里 proof 无效的 + 重建闭包
       − complained                              ← 过滤①

过滤② facts.rule_available            输入不可用不派
过滤③ _antichain_ok(r, inflight)      在途集必须是输入闭包上的反链
过滤④ _held_by_advisory(r, coming, …) 前驱无效且"真的会来"才压住
过滤⑤ 闭包极小                         生产者也在候选里的,让生产者先走

排序  (0 if r ∈ repair|triage else 1,           先答申诉,后建东西
       0 if execution == "task" else 1,          异步先起,才谈得上重叠
       FORWARD_PRIORITY.index(r))

派发  caused_by      = 它欠的全部申诉的 (rule, run)
      diagnosis_refs = 那些申诉的可靠归因 id
      params         = triage 的 {"sim_run": N}
      escalations    = 本轮全部无主申诉的理由
```

五个过滤器,每一个都有一句话的理由:

| | 为什么 |
|---|---|
| ① **自身有开着的申诉 → 不派** | 重验一个没人答复的失败,是花一轮重新发现已经写下来的东西;重建一个自身失败还没归因的规则,什么也答不了 |
| ② 输入不可用 | 生产者的 proof 无效时,消费者拿不到可用输入 |
| ③ **反链** | 下游方向 = Option C 的撕裂读(重 promote 落在消费者的 canonical 读之下);上游方向 = 基于即将改变的输入白跑一轮。**一个谓词,两个方向,传递**——v1 的两个半闸各覆盖一个方向,且只看一跳 |
| ④ advisory | 便宜的探测器先说话,免得昂贵的 stage 跑在即将作废的输入上。`coming` 减掉被①挡住的规则 —— 一个自己被卡住的前驱不会来,压住别人就是永远等 |
| ⑤ 闭包极小 | 候选之间也有上下游。不加这条,`task` 优先会把下游 owner(synthesis)排到上游(specification)前面,那一轮直接作废 |

排序三档同理:**先答申诉**(反正要重验,修完再验只花一次)→ **task 先于 main-thread**(后台立即返回,同步的会堵住整个回合;只在反链上重排,不动任何本来有序的东西)→ **FORWARD_PRIORITY** 兜底。

### step 3 `_settle` —— 什么都派不出去

```
有在途        → YIELD(带 in_flight[])
有无主申诉    → ESCALATE(最靠前那条的理由 + candidates)
required 全 valid → DONE(--closing 时先过 signoff_gate,不清则 ESCALATE)
否则          → ESCALATE "no eligible rule, none in-flight, not done"
```

`unowned` 排在"全 valid"之前、却排在 `YIELD` 之后:**能干的活先干完**(这就是"不可路由不挡可路由"),但一有无主申诉就不能宣称完成。同一批无主申诉在本轮如果**有**东西可派,会以 `escalations[]` 挂在 `DISPATCH` 上当场报给人 —— 不必等板子清空。

## 5. 字段的一生(与 v1 的差异只在两处)

```
① 失败的 stage 写 result.json                     ← 契约未变
   { "status":"fail",
     "stage_specific": { "fix_owner":"rtl-design", "fail_reason":"…" } }
        ▼ reap 时 promote 进 canonical
② schedule._attribution 读它 / 或读更晚的 diagnosis  ← ★ 收进一个函数,产出 (attribution, owner)
        ▼
③ decide 返回动作 + 完整 argv(dispatch_args)
   新增 escalations[](本轮无主申诉的理由)            ← ★ 唯一新增的动作字段
        ▼
④ kernel.py cmd_dispatch:caused_by → per-run 信封路径;diag_refs → scope/reasons
        ▼
⑤ <workdir>/dispatch.json:inputs / scope / caused_by / reasons  ← 四个键未变
   但 caused_by 现在也会出现在"前向轮"上 —— 一轮既按新上游重建、又答复它欠的失败
        ▼
⑥ stage 读 dispatch.json
```

第 ⑤ 处的语义变化是三个 stage skill 措辞同步改动的原因:`caused_by` 不再等价于"这是返修轮",而是"**有失败的信封在等这个 stage**",可以和 `scope`(上游漂移)同时出现。

**六个机器零读点的审计字段**见 `01-v2-design.md` §7 —— 它们不承重,但不能删。

## 6. 同样四个并行场景,现在怎么走(实测)

| 场景 | v1 第一回合 | v2 第一回合 |
|---|---|---|
| **A** 同 owner,两条都是信封 | `DISPATCH rtl-design 交付[lint-cdc:2, synthesis:2]` | 同 |
| **B** 同 owner,信封 + triage 归因 | `交付[lint-cdc:2]` ❌ | `交付[lint-cdc:2, simulation:2]` + `refs` |
| **C** 同 owner,配对有闭包关系 | `交付[rtl-design:2]` ❌ | `交付[rtl-design:2, lint-cdc:2]` |
| **D** 不同 owner,有闭包关系 | `DISPATCH spec 交付[lint-cdc:2]` → YIELD;共 11 轮 | 同,但共 **8 轮**(下一轮的 rtl 重建带着 sim 的信封) |
| **乙** 不同 owner,独立 | 一个回合只开一个 | **同回合两个都派**,各带各的信封 |

## 7. 结构性后果(对照 `02-v1-as-built.md` §8)

| v1 的后果 | v2 出自哪里 |
|---|---|
| 返修永不并行 | 一个候选集 + 反链:独立的 owner 同回合都派 |
| 级联轮是盲的 | `_dispatch_action` 对返修轮和前向轮一视同仁地挂 `caused_by` |
| 归因随输入漂移一起丢 | 有主申诉的关闭条件是"owner 被派过",与输入无关 |
| 靠前的不可路由挡住靠后的可路由 | 无主申诉不进候选集、只进 `escalations`,`ESCALATE` 退到 step 3 |
| 生产者在途时消费者仍被准入 | `_antichain_ok` 的上游方向 |

验收数字在 `01-v2-design.md` §5;`00-scenario-space.md` 是判据与场景空间的推导。
