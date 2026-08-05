# 最终方案:归因先澄清,再统一调度

> **这是什么**:失败路由的最终形态。结构与 [`03-v2-as-built.md`](03-v2-as-built.md) 相同(先整体、再子函数),便于逐节对照。
> **状态**:**设计已确认,代码未实现。** 七项逐项走查的裁决见 `01-v2-design.md` §9。落地后本文取代 03。
> **一句话**:任何一条失败的归因没澄清,整轮停下等人;走过那一行之后,每条失败都有明确 owner,后面用一套策略调度。

---

## 1. 整体

```python
def decide(module, *, wake=None, closing=False):
    events   = facts.read_events(module)
    inflight = facts.in_flight(events)

    reap = _ready_to_reap(module, events, inflight, wake)      # step 0 收口
    if reap:
        return reap

    fails   = _failures(module, events)                        # step 1 每条最新 fail + 求 owner
    unclear = [f for f in fails if not f["owner"]]
    if unclear:
        return _escalate(unclear[0])                           #    归因没澄清 → 停下等人
    # ↓ 走过这一行,每条失败都有明确 owner
    open_ = [f for f in fails if not _answered(events, f["idx"], f["owner"])]

    repair     = _group(open_)                                 # step 2 一个候选集
    complained = {f["rule"] for f in open_}
    required   = required_proofs(events)
    candidates = _candidates(module, events, inflight, repair,
                             complained, _forward_work(module, events, required))
    if candidates:
        return _dispatch_action(module, candidates[0], repair)

    return _settle(module, events, inflight, required, closing) # step 3 收尾
```

四步的优先级顺序就是全部控制流:

| 步 | 问题 | 产出 |
|---|---|---|
| 0 | 有跑完的要收吗 | `REAP` |
| 1 | 每条失败归因清楚吗、欠谁、还欠着吗 | `ESCALATE`(有说不清的)/ 分好组的待办 |
| 2 | 现在谁能开工 | `DISPATCH`(带上它欠的全部失败) |
| 3 | 都开不了工,说清为什么 | `YIELD` / `DONE` / `ESCALATE` |

step 1 的早退是这版的骨架:**先消除不确定性,再用一套策略调度**。它替掉的是"带着不确定性并行推进"——那会让 step 2 之后的每处都要考虑"万一还有条说不清的"。

---

## 2. step 0 · 收口

`_ready_to_reap` 不变,见 [`03-v2-as-built.md` §2](03-v2-as-built.md)。

---

## 3. step 1 · 归因与欠账

### 3.1 `_failures(module, events) -> list[dict]`

按 `FORWARD_PRIORITY` 扫每条 proof,最新 outcome 是 fail 的都取出来,连同它的 owner:

```python
for rule in rules.FORWARD_PRIORITY:
    hit = _latest_fail(events, rule)
    if hit is None:
        continue
    idx, outcome = hit
    out.append({"rule": rule, "run": outcome["run"], "idx": idx,
                **_owner(module, events, rule, idx, outcome)})
```

不做任何过滤 —— 过滤是调用方的事(先挑出说不清的,再挑出还欠着的)。

### 3.2 `_owner(...)` —— 一条 or 链

调度器读"为什么失败"的唯一入口。返回 `attribution` / `owner` / `diagnoses` / `unreliable` 四个键,owner 由五档 or 链求出:

```
① None                              判它的 oracle 已被 reopen 且未重新 pin
② 有 active diagnosis → 由它说了算    高置信/human → 它的 fix_owner;低置信 → None(终止,不再往下)
③ 信封里合法的 fix_owner              _declared_owner + _legal(∈ input_closure)
④ 该规则声明的 Rule.triage            指不出来时,该动手的是分析器
⑤ None                              没人可派
```

四点说明:

**① 判决被撤回 = 归因失效,不是"当没发生过"。** reopen 一个 oracle 的意思是"我不再为这个 judge 背书",那就**不能拿它的判决去指使上游改东西** —— 正确后果是交给人。(仓库里有 `test_re_reap_does_not_dispatch_upstream_rework` 守着这个危害。)`facts.verdict_trustworthy` 的条件 4(自身产物漂了)边际价值太低,直接删。

**② 是终止分支,不是穿透。** 一旦有人分析过这条失败,分析结果说了算 —— 包括"说不准"(低置信 → owner=None → 交给人)。于是"已经分析过"这个守卫**自动消失**:分析过且低置信的失败,owner 已经是 None,永远走不到 ④。

**③④ 的先后就是"triage 是后备通道"这件事的表达。** simulation 有 UVM 参考模型作自己的 oracle,大多数失败它自己就能指名(功能/时延不符 → `rtl-design`,测试点缺失 → `simulation-plan`,规格缺陷 → `specification`);`simulation/SKILL.md` 明写"读了日志和参考模型仍然定位不了才省略 `--fix-owner`,**省略在这里是一个答案,不是耸肩**"。所以 ④ 只在 ③ 拿不到东西时才轮到。

**owner 是每次重新求值的,不是记下来的。** triage 带回可靠归因后,同一条失败的 owner 从 `simulation-triage` 变成 `rtl-design`,"派过没有"这个问题的主语跟着换,于是申诉自动重新开着 —— 不需要任何"重置"逻辑。

| 事件 | owner | 结果 |
|---|---|---|
| sim 失败,信封没指名 | `simulation-triage` | 欠着 → 派 triage |
| triage 在途 | 同上 | 已答复(在途算派过);sim 不会趁机重跑,因为反链挡着(见 §4.3) |
| triage reap 成 `blocked` | 同上 | 重新欠着 → **再派一次**。不设上限,由人自己介入 |
| triage 带回高置信归因 | 变成归因的 `fix_owner` | 欠着 → 路由 |
| triage 带回低置信归因 | `None` | → `ESCALATE`,人来判 |

### 3.3 早退:`_escalate(f)`

只要有**一条**失败求不出 owner,整轮停下:

```python
unclear = [f for f in fails if not f["owner"]]
if unclear:
    return _escalate(unclear[0])
```

一次报一条(按 `FORWARD_PRIORITY` 取最靠前)。理由是机制上的:说不清的失败只发生在并行阶段,而并行任务返回时机不一致,**一次只会发现一个**;第二条(如果有)在第一条澄清后自然浮出来。

理由从 `(attribution, owner)` 这对值推出来,不是在发现它的分支里现场抛的:

| 状态 | 理由 |
|---|---|
| oracle 已被 reopen | `<rule>: the oracle that judged this failure was reopened` |
| 有低置信归因 | `unreliable diagnosis for <rule>` + `candidates[]` |
| `attribution` 为 `None` | `<rule>: envelope named no fix_owner` |
| `attribution` == 失败的规则自己 | `<rule>: fix_owner is itself, in-stage remedy exhausted` |
| `attribution` 在闭包外 | `<rule>: fix_owner '<x>' is outside its input closure` |

> **代价,写在明处**:一条没人能归因的失败会把**整条流水线**停到有人 `diagnose` 为止 —— 包括那些跟它毫无关系、本来能自动修的失败。这是刻意的:先澄清 fix_owner,再按统一策略决定走哪个阶段,避免"带着不确定性分头推进"引入的分支。
>
> 依据是这类失败罕见且有结构上的兜底:`simulation` 有 triage(④);闭包非空的其余 stage 契约上都要求 fail 时指名(如 `power-analysis/SKILL.md`:"`--fix-owner` on **every** failure, tool and license failures included");而 `specification` 的输入闭包为空 —— 它的失败**结构上**永远无法自动路由,新老方案都只能停下来叫人。

### 3.4 `_answered(events, idx, owner) -> bool`

不变。判"**owner 被派过**",不是"被 `caused_by` 点名过" —— 问题是"该动手的那个 stage 有没有轮到过",一次因别的原因重建 owner 的轮次同样给过它机会。

在途算派过;reap 成 `blocked` 不算(什么都没落成)。

走过 3.3 的早退之后,**这是唯一的关闭条件**:

```
欠着(f) = ¬ _answered(owner)
```

### 3.5 `_group(open_) -> dict`

```
{owner → [它欠的申诉…]}
```

一个桶。triage 也在里面 —— 它就是一个普通 owner。**"同 owner 的多条失败合成一轮给它"是分组的直接结果**,没有可以只实现一半的规则。

---

## 4. step 2 · 派一个

**返修和前向是同一件事:派一个规则,把它欠的失败一并交给它。**

### 4.1 `required_proofs` + `_forward_work`

不变。目标集收窄兼任"修完切回来验证"的机制:失败的 proof 一直留在 `work` 里,被冻结过滤器挡着,闸门一开就重验。

### 4.2 `_candidates(...)`

```
候选池 = (work ∪ repair.keys) − complained
```

| 过滤 | 判据 | 为什么 |
|---|---|---|
| ① 冻结 | `− complained` | 重验一个还没人答复的失败 = 花一轮重新发现已经写下来的东西 |
| ② 可用 | `facts.rule_available` | 生产者的 proof 无效时拿不到可用输入 |
| ③ 无冲突 | `_unblocked(r, pending, inflight)` | §4.3 |
| ④ advisory | `_held_by_advisory` | 便宜的探测器先说话。`coming` 要减掉被①冻住的规则 —— 自己被卡住的前驱不会来 |

排序三档:

```
(0 if r ∈ repair else 1,                 先答申诉,后建东西
 0 if execution == "task" else 1,         异步先起,才谈得上重叠
 FORWARD_PRIORITY.index(r))               兜底
```

第二档只在**无序的候选之间**重排(③ 已经把有上下游关系的剔掉了),所以不会打乱任何本来有序的东西。

> **advisory 边的现状**:`synthesis ← lint-cdc`、`power-analysis ← timing-analysis`。**`simulation` 没有这条边** —— RTL 交付后回归与 lint **并行开跑**,这是确认过的工作方式,不加。

### 4.3 `_unblocked(rule_name, pending, inflight) -> bool`

03 里这是两个东西(`_antichain_ok` 对在途、"闭包极小"筛对同批候选)。它们说的是同一件事 —— **别在会被改动的输入上开工** —— 合成一个:

```python
def _unblocked(rule_name, pending, inflight):
    """pending = 在途 ∪ 本轮其它候选。"""
    if any(p != rule_name and p in rules.input_closure(rule_name) for p in pending):
        return False          # 生产者在途,或也在本轮候选里 → 等它
    if any(rule_name in rules.input_closure(f["rule"]) for f in inflight):
        return False          # 消费者在途 → 撕裂读
    return True
```

两个子句方向不同,**第二句只对在途生效**:对同批候选也生效的话,两个有上下游关系的候选会互相挡住而死锁 —— 生产者被"消费者也在候选里"挡住,消费者被"生产者也在候选里"挡住。对同批候选,正确处理是"生产者先走、消费者等下一轮",这正是第一句。

两个方向都从严,是确认过的:**RTL 正在重写时不起综合/lint**(人手工要一版 QoR 参考属于探索性动作,不进内核调度);**消费者在途要等它结束**,结束后如果 fail 再由 decide 重新判去哪。

### 4.4 `_dispatch_action(module, rule, repair) -> action`

```
DISPATCH rule
  caused_by      = repair[rule] 里每条失败的 (rule, run)   → 内核解析成 per-run 信封路径
  diagnosis_refs = 那些失败的可靠归因 id                    → 内核展开成 scope 的 fix_locus + reasons
  params         = {"sim_run": N}                          ← 被派的规则声明了 params 才填
```

没有 `escalations` —— 走到这里已经没有说不清的失败了。

---

## 5. step 3 · 收尾

```
有在途            → YIELD(带 in_flight[])
required 全 valid → DONE(--closing 时先过 signoff_gate,不清则 ESCALATE)
否则              → ESCALATE "no eligible rule, none in-flight, not done"
```

比 03 少一支:"有无人可派的申诉"那一档已经在 step 1 早退掉了。

---

## 6. 注册表改动

**`simulation-triage` 声明它消费 `simulation`。**

```python
"simulation-triage": Rule(
    ...
    inputs={
        "design": ("Design/specification/design.md",),
        "rtl":    ("Design/rtl-design/*.v", "Design/rtl-design/rtl-files.json"),
        "plan":   ("Verification/simulation-plan/verification-plan.md",),
        "sim":    ("Verification/simulation/*",),          # ← 新增
    },
```

两个理由:

1. **事实如此**。`simulation/SKILL.md:67` 特意把 `<test_id>.fsdb` 留在 run 目录根部"for `simulation-triage` to open",还有失败用例清单和日志。不声明,注册表就在说假话。
2. **副作用正好需要**:`simulation ∈ input_closure(simulation-triage)` ⇒ 反链挡住 **triage 分析期间 simulation 重跑**(否则那是 54 分钟)。

安全性:triage 的 `proof=None`,`facts.rule_available` 对无 proof 的规则直接短路返回 True,所以声明输入**不影响它能不能被派**,只影响闭包。

triage 只看当次失败的波形和日志,**不需要**上一次通过的 run 做对比,所以不加 `last_pass_run` 之类的参数。

---

## 7. 与落地版(03)的差异一览

| | 03 落地版 | 本文 |
|---|---|---|
| 失败开着的判据 | 三问四支(判决算数 / 有主-派过 / 无主-输入没漂) | **一条子句**:owner 没被派过 |
| 归因说不清时 | 挂 `escalations[]` 随派发上报,流程继续 | **整轮停下等人**(step 1 早退) |
| `facts.verdict_trustworthy` | `complaints` 调用 | 条件 3 → owner 链第 ① 档;条件 4 删 |
| `facts.inputs_unchanged` | `complaints` 调用 | **删** |
| 归因求值 | 两条通道 + 守卫 | **一条 or 链**,五档 |
| `unreliable` 守卫 | `_group` 里一条 | **自动消失**(② 是终止分支) |
| triage | 第三个桶 + 专用分支 | **or 链里的一档**,普通 owner |
| 闭包冲突 | `_antichain_ok` + 闭包极小筛 | **一个 `_unblocked`**,两个子句 |
| `escalations[]` 动作字段 | 有 | **删** |
| `Rule.triage_attempts` | 无 | **不加**(不设上限,由人介入) |
| 注册表 | — | `simulation-triage` 声明消费 `simulation` |
| 概念词 | 申诉 / 有主 / 无主 / 判决算数 / 可靠 / 反链 / 闭包极小 | **失败 / owner / 派过没有 / 反链** |

## 8. 预期行为变化(验收时必须只落在这几类)

| # | 情形 | 03 | 本文 |
|---|---|---|---|
| Δ1 | 无人可派的失败 + 输入漂了 | 关闭 → 前向重验 | 一直 escalate 到人介入 |
| Δ2 | 判它的 oracle 被 reopen | 关闭 → 前向重验 | 归因失效 → 交给人 |
| Δ3 | 有说不清的失败时,其他能自动修的活 | 照常推进(`escalations` 随派发上报) | **停下** |
| Δ4 | sim 说不出 + 上游刚改过 | 前向重验 sim(54min) | 先派 triage(便宜的 `task`) |
| Δ5 | triage 分析期间 | sim 可能被重验 | 反链挡住 |

**已验收的机时账不受影响**:135 个 episode 的缺陷全是"信封指名合法"的,Δ1–Δ4 一个都不触发,E1–E6 应保持 135/135、浪费 0。

Δ3 会让状态网格里 A4 那 348 格回到"整轮 ESCALATE" —— **A4 这条性质随之退休**(它是度量时发明的判据,与最终策略相反)。

## 9. 落地顺序

1. episode 集补 `none` 类缺陷,把 triage 通路端到端量出来(Δ4 唯一缺数字的地方);顺带修正 `00-scenario-space.md` §7 里"triage 环路有覆盖"那句错话
2. 注册表加 triage 的输入声明,逐格验证(只应影响 triage 在途的格子)
3. 上 step 1 / step 2 的最终形态,逐格对照,变化必须只在 Δ1–Δ5
4. 文档:本文取代 `03-v2-as-built.md`;`02-v1-as-built.md` 保留作对照
