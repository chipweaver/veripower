# v2 原样:现在的 flow 怎么跑

> **这是什么**:重构后调度的完整说明 —— 先整体,再逐个函数。和 [`02-v1-as-built.md`](02-v1-as-built.md) 对照着读。
> **给谁**:要改 `schedule.py`、或者要 debug 一次真实回合的人。
> **不含**:日志格式、内核动词、stage 信封契约 —— 那些与 v1 相同,见 `02-v1-as-built.md` §1/§6。唯一的注册表变化:`Rule.stage` 删了(9 条里逐条 == `name`,零读者),`Rule.triage` 加了(哪个 stage 背后有分析器是注册表事实,不是调度器里的规则名)。
> **注**:本文描述**已落地**的代码。讨论中还有一版更进一步的简化(申诉判据收成一条子句),未实现,不在本文。

---

## 1. 整体

一次 `kernel.py decide` = 一个进程,按 0→1→2→3 顺序走,**在第一个能产生动作的地方 return**,打印一个 JSON 动作后退出。它不执行动作、不写日志(除了纯加速用的指纹缓存)。

```python
def decide(module, *, wake=None, closing=False):
    events   = facts.read_events(module)
    inflight = facts.in_flight(events)

    reap = _ready_to_reap(module, events, inflight, wake)              # step 0 收口
    if reap:
        return reap

    open_ = complaints(module, events)                                # step 1 谁欠谁
    repair, triage, unowned = _group(open_)

    required   = required_proofs(events)
    complained = {c["rule"] for c in open_}
    candidates = _candidates(module, events, inflight, repair, triage,
                             complained, _forward_work(module, events, required))
    if candidates:                                                    # step 2 派一个
        return _dispatch_action(module, candidates[0], repair, triage, unowned)

    return _settle(module, events, inflight, required, unowned, closing)   # step 3 收尾
```

四步的优先级顺序就是全部控制流:

| 步 | 问题 | 产出 |
|---|---|---|
| 0 | 有跑完的要收吗 | `REAP` |
| 1 | 每条失败欠谁、还欠着吗 | 分好组的三个桶(**不产生动作**) |
| 2 | 现在谁能开工 | `DISPATCH`(带上它欠的全部失败) |
| 3 | 都开不了工,说清为什么 | `YIELD` / `ESCALATE` / `DONE` |

一个**回合**由 Orchestrator 循环组成:`decide → 执行 → decide → …`,只有 `YIELD`/`DONE`/`ESCALATE` 结束回合。`decide` 是 (磁盘, 日志, 参数) 的纯函数,回合之间不带任何东西。

与 v1 的结构差别只有一条:**v1 的 step 1 是出口**(`_disposition` 可以直接返回 DISPATCH / ESCALATE / YIELD,整轮就此结束),**v2 的 step 1 只是计算**,把结果交给 step 2。

---

## 2. step 0 · 收口

### `_ready_to_reap(module, events, inflight, wake) -> action | None`

两条路,都返回 `REAP`:

1. `--wake <rule>:<run>` 命中一个在途 run
2. 扫描全部在途 run 的 workdir,谁写出了 `result.json` 就收谁;多个同时就绪,按 `FORWARD_PRIORITY` 取最靠前的

先收口是为了让后面三步都基于最新日志。两条路看似重复,但 `--wake` 有一件扫描做不到的事:**执行器死了、没写 `result.json`**,扫描看不见它,只有 `--wake` 能把它收成 `blocked` 把日志解开。

---

## 3. step 1 · 谁欠谁

这一步不产生动作,只算出一张"谁欠谁"的表交给 step 2。入口是 `complaints()`,底下五个函数。

### 3.1 `complaints(module, events) -> list[dict]`

按 `FORWARD_PRIORITY` 顺序扫每条 proof,逐条问三个问题;答完还"欠着"的进结果:

```python
for rule in rules.FORWARD_PRIORITY:
    hit = _latest_fail(events, rule)                       # ① 它最新的 outcome 是 fail 吗
    if hit is None: continue
    idx, outcome = hit

    if not facts.verdict_trustworthy(...): continue        # ② 这条判决还算数吗

    att = _attribution(module, events, rule, outcome)      # ③ 谁必须动手
    if att["owner"]:
        if _answered(events, idx, att["owner"]): continue  # ④a 他动过了吗
    elif not facts.inputs_unchanged(module, rule, outcome):# ④b 没人可派:世界变了吗
        continue

    out.append({"rule": rule, "run": outcome["run"], **att})
```

| 问题 | 谁答 | 关掉它意味着 |
|---|---|---|
| ① 最新是 fail 吗 | `_latest_fail` | 早已重跑过,没这回事 |
| ② 判决还算数吗 | `facts.verdict_trustworthy` —— §4.4 条件 3、4:判它的 oracle 没被 reopen(且未重新 pin)、这一轮自己的产物没漂 | 判它的 judge 被撤回了,这条判决不再是证据 |
| ④a **有 owner**:他被派过吗 | `_answered` | 该动手的已经轮到过 |
| ④b **没有 owner**:输入变了吗 | `facts.inputs_unchanged` | 能做的只剩 triage 或找人,而他们要看的证据已经变了 |

④ 的两支是这版唯一的不对称,原因是两种情形的"进展"信号不同:一边在等一个具体的人,一边在等世界变化。**注意 ④a 里没有输入指纹**——兄弟修复漂掉一条失败的输入,不代表它的 fix owner 不用干活了;v1 正是在这里把归因连同判决一起丢了,96/118 个双缺陷 episode 的每一次额外重跑都源于此。

### 3.2 `_attribution(module, events, rule, outcome) -> dict`

**调度器读"为什么失败"的唯一入口。** 返回四个键:

```python
{"attribution": …,  # 原样写下来的指名(可能非法、可能是 None)
 "owner":       …,  # 它的可路由投影:合法 且(对 diagnosis)可靠,否则 None
 "diagnoses":   [],  # 支撑这个 owner 的可靠归因 → --diagnosis-refs
 "unreliable":  []}  # 不可靠的归因 → ESCALATE 的 candidates
```

两条通道,一个优先级规则 —— **后来的分析压过当场的自述**:

```
_active_diagnoses(events, rule, outcome)      subject 匹配这次 outcome 的 run、未被 supersede
  ├ 非空:最新那条说了算
  │     _reliable(它)? = 有 fix_owner 且 (source==human 或 confidence==high)
  │        可靠   → owner = 它的 fix_owner;diagnoses = 同 owner 的全部可靠归因
  │        不可靠 → owner = None;unreliable = 全部候选
  └ 空:_declared_owner —— 读失败规则 canonical result.json 的 stage_specific.fix_owner(原样)
        owner = 它,当且仅当 _legal:非空 且 ∈ input_closure(失败的规则)
```

读 canonical 是安全的:申诉只在"这次失败仍是该规则**最新** outcome"期间存在,而 fail 会 promote,所以 canonical 里就是这一轮的信封。(`blocked` 不 promote,也不产生申诉。)

底下三个小函数各管一件事:

| 函数 | 管什么 |
|---|---|
| `_active_diagnoses` | 哪些归因还有效 —— subject 匹配这次 run、且没被 `supersedes` 顶掉 |
| `_reliable` | 这条归因能不能**自动**路由 —— 有 `fix_owner`,且 human 终审或 triage 高置信 |
| `_legal` | 这个名字是不是**合法**目标 —— ∈ `input_closure`。因为图无环,"指自己"自动被这一条挡掉 |

### 3.3 `_answered(events, idx, owner) -> bool`

```python
for i, e in enumerate(events):
    if i <= idx or e["type"] != "dispatch" or e["rule"] != owner: continue
    done = 这个 (owner, run) 的 outcome
    if done is None or done["verdict"] != "blocked": return True
return False
```

判的是"**owner 被派过**",不是"被 `caused_by` 点名过"。因为问题是"该动手的那个 stage 有没有轮到过"——一次因别的原因重建 owner 的轮次同样给过它机会,再问一次就是同一个缺陷派两遍。

两个边界:**在途也算派过**(它正在动手);**reap 成 `blocked` 不算**(什么都没落成,申诉重新打开,而不是被一个死掉的执行器悄悄吃掉)。

### 3.4 `_group(open_) -> (repair, triage, unowned)`

```
repair  : {owner → [它欠的申诉…]}
triage  : {Rule.triage → [没人指名、且还没人分析过的申诉…]}
unowned : [没人可派的申诉…]
```

**"同 owner 的多条失败合并成一次 dispatch"是分组的直接结果**,没有一条可以只实现一半的规则(v1 是两个各漏一半的筛子:信封分支跳过带 diagnosis 的兄弟,diagnosis 分支只收有可靠归因的兄弟)。

进 `triage` 桶多一个条件:**这条失败还没人分析过**(`not c["unreliable"]`)。分析回来说不可靠,那是人的事;拿同一份证据再跑一遍同一个分析器只会复现它。

### 3.5 `_escalation(c) -> dict`

`unowned` 里每一条的理由,**从 `(attribution, owner)` 这对值推出来**,不是在发现它的分支里现场抛的:

| `attribution` | 理由 |
|---|---|
| 有 unreliable 归因 | `unreliable diagnosis for <rule>` + `candidates[]` |
| `None` | `<rule>: envelope named no fix_owner` |
| == 失败的规则自己 | `<rule>: fix_owner is itself, in-stage remedy exhausted` |
| 闭包外的规则 | `<rule>: fix_owner '<x>' is outside its input closure` |

---

## 4. step 2 · 派一个

**返修和前向是同一件事:派一个规则,把它欠的失败一并交给它。** 所以只有一个候选集、一次排序。

### 4.1 `required_proofs(events)` + `_forward_work(module, events, required)` —— 该建什么

```
required = failing_proofs(events) 或(没有失败时)全部八条        ← 目标集收窄
work     = required 里 proof 无效的
work    += 重建闭包:沿着"输入不可用"的规则,把它的生产者递归拉进来
```

目标集收窄有两个作用:修复期间不建下游;同时让失败的那条 proof 一直留在待办里,闸门一开就重验——**"修完怎么切回来验证"不需要专门写,它一直在待办里,只是被过滤器①挡着**。

### 4.2 `_candidates(...) -> list[str]`

```
候选池 = (work ∪ repair.keys ∪ triage.keys) − complained
```

四个过滤器,每个一句话理由:

| 过滤 | 判据 | 为什么 |
|---|---|---|
| ① 冻结 | `− complained`(自身有 open 申诉的规则) | 重验一个没人答复的失败,是花一轮重新发现已经写下来的东西;重建一个自身失败还没归因的规则,什么也答不了 |
| ② 可用 | `facts.rule_available` | 生产者的 proof 无效时,消费者拿不到可用输入 |
| ③ 反链 | `_antichain_ok(r, inflight)` | 在途集必须是输入闭包上的反链(§4.3) |
| ④ advisory | `_held_by_advisory(r, coming, inflight)` | 便宜的探测器先说话,免得昂贵的 stage 跑在即将作废的输入上 |

再加一个**闭包极小**筛(不是过滤器,是选择):候选之间也有上下游,生产者也在候选里的,让生产者先走。不加这条,下面的 `task` 优先会把下游 owner(synthesis)排到上游(specification)前面,那一轮直接作废——这是重构时被 episode 下界抓出来的两个 bug 之一。

排序三档:

```
(0 if r ∈ repair|triage else 1,          先答申诉,后建东西
 0 if execution == "task" else 1,         异步先起,才谈得上重叠
 FORWARD_PRIORITY.index(r))               兜底
```

第二档只在**反链上**重排(闭包极小筛之后剩下的候选彼此无序),所以它不会打乱任何本来有序的东西。

`coming`(喂给 advisory 门的"谁真的会来")等于候选池**减掉被①冻住的规则**:一个自己被卡住的前驱不会来,压住别人就是永远等——这是另一个被抓出来的 bug。

### 4.3 `_antichain_ok(rule_name, inflight) -> bool`

```python
for f in inflight:
    if f["rule"] == rule_name: return False                       # 已在途
    if f["rule"] in rules.input_closure(rule_name): return False  # 生产者在途
    if rule_name in rules.input_closure(f["rule"]): return False  # 消费者在途
return True
```

一个谓词,两个方向,**传递**。

- **消费者在途** = 撕裂读:我重 promote 会落在它的 canonical 读之下
- **生产者在途** = 我会基于一份即将改变的输入跑完一整轮

v1 是两个半闸:`_has_inflight_consumer` 只覆盖消费者方向且只看一跳,生产者方向完全没人守——实测 17/17 全部越权准入。

### 4.4 `_dispatch_action(module, rule, repair, triage, unowned) -> action`

```
DISPATCH rule
  caused_by      = repair[rule] 里每条申诉的 (rule, run)      → 内核解析成 per-run 信封路径
  diagnosis_refs = 那些申诉的可靠归因 id                       → 内核展开成 scope 的 fix_locus + reasons
  params         = {"sim_run": N}                             ← 只有 triage
  escalations    = 本轮全部无人可派的失败的理由                 ← 不挡路,但当场报给人
```

外加 `_dispatched()` 把完整 argv(`dispatch_args`)一并给出,让 Orchestrator 原样执行而不是手抄——手抄会漏 `caused_by`。

---

## 5. step 3 · 收尾

### `_settle(module, events, inflight, required, unowned, closing) -> action`

```
有在途            → YIELD(带 in_flight[])
有无人可派的申诉   → ESCALATE(最靠前那条的理由 + candidates)
required 全 valid → DONE(--closing 时先过 signoff_gate,不清则 ESCALATE)
否则              → ESCALATE "no eligible rule, none in-flight, not done"
```

顺序有讲究:`unowned` 排在"全 valid"之前(有人在等答复就不能宣称完成),却排在 `YIELD` 之后(还有活在跑就先等)。而**本轮如果有东西可派**,这些无人可派的失败会以 `escalations[]` 挂在 `DISPATCH` 上当场报出去——不必等板子清空,这就是"不可路由不挡可路由"。

---

## 6. 字段流向(与 v1 只差两处)

```
① 失败的 stage 写 result.json                     ← 契约未变
   { "status":"fail",
     "stage_specific": { "fix_owner":"rtl-design", "fail_reason":"…" } }
        ▼ reap 时 promote 进 canonical
② _attribution 读它 / 或读更晚的 diagnosis          ← ★ 收进一个函数,产出 (attribution, owner)
        ▼
③ decide 返回动作 + 完整 argv(dispatch_args)
   新增 escalations[]                              ← ★ 唯一新增的动作字段
        ▼
④ kernel.py cmd_dispatch:caused_by → per-run 信封路径;diag_refs → scope/reasons
        ▼
⑤ <workdir>/dispatch.json:inputs / scope / caused_by / reasons   ← 四个键未变
   但 caused_by 现在也会出现在"前向轮"上 —— 一轮既按新上游重建、又答复它欠的失败
        ▼
⑥ stage 读 dispatch.json
```

第 ⑤ 处的语义变化是三个 stage skill 措辞同步改动的原因:`caused_by` 不再等价于"这是返修轮",而是"**有失败的信封在等这个 stage**",可以和 `scope`(上游漂移)同时出现。

**六个机器零读点的审计字段**见 `01-v2-design.md` §7 —— 不承重,但不能删。

---

## 7. 同样四个并行场景(实测)

| 场景 | v1 第一回合 | v2 第一回合 |
|---|---|---|
| **A** 同 owner,两条都是信封 | `DISPATCH rtl-design 交付[lint-cdc:2, synthesis:2]` | 同 |
| **B** 同 owner,信封 + triage 归因 | `交付[lint-cdc:2]` ❌ | `交付[lint-cdc:2, simulation:2]` + `refs` |
| **C** 同 owner,配对有闭包关系 | `交付[rtl-design:2]` ❌ | `交付[rtl-design:2, lint-cdc:2]` |
| **D** 不同 owner,有闭包关系 | 共 11 轮 | 共 **8 轮**(下一轮的 rtl 重建带着 sim 的信封) |
| **乙** 不同 owner,独立 | 一个回合只开一个 | **同回合两个都派**,各带各的信封 |

## 8. 结构性后果(对照 `02-v1-as-built.md` §8)

| v1 的后果 | v2 出自哪里 |
|---|---|
| 返修永不并行 | 一个候选集 + 反链:独立的 owner 同回合都派 |
| 级联轮是盲的 | `_dispatch_action` 对返修轮和前向轮一视同仁地挂 `caused_by` |
| 归因随输入漂移一起丢 | `complaints` 的 ④a 里没有输入指纹 |
| 靠前的不可路由挡住靠后的可路由 | 无人可派的失败不进候选集、只进 `escalations`,`ESCALATE` 退到 step 3 |
| 生产者在途时消费者仍被准入 | `_antichain_ok` 的上游方向 |

验收数字在 `01-v2-design.md` §5;`00-scenario-space.md` 是判据与场景空间的推导。
