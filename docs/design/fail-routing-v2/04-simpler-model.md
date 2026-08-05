# 更简化的模型:一条子句

> **这是什么**:在 [`03-v2-as-built.md`](03-v2-as-built.md) 落地版之上再削一层的设计。结构与 03 相同(先整体、再子函数),便于逐节对照。
> **状态**:**未实现。** 落地后本文取代 03。
> **要削掉什么**:`有主/无主` 两条关闭规则、`verdict_trustworthy`、`unreliable` 守卫、triage 这个独立的桶、两个闭包过滤器中的一个。
> **削掉之后剩下什么**:失败、owner、派过没有、反链。

---

## 1. 整体

调用序列与 03 完全一样,四步四函数:

```python
def decide(module, *, wake=None, closing=False):
    events   = facts.read_events(module)
    inflight = facts.in_flight(events)

    reap = _ready_to_reap(module, events, inflight, wake)              # step 0 收口
    if reap:
        return reap

    open_ = complaints(module, events)                                # step 1 谁欠谁
    repair, unowned = _group(open_)                                   #    ← 两个桶,不是三个

    required   = required_proofs(events)
    complained = {c["rule"] for c in open_}
    candidates = _candidates(module, events, inflight, repair,
                             complained, _forward_work(module, events, required))
    if candidates:                                                    # step 2 派一个
        return _dispatch_action(module, candidates[0], repair, unowned)

    return _settle(module, events, inflight, required, unowned, closing)   # step 3 收尾
```

变的是 step 1 和 step 2 的内部。step 0 与 step 3 一字不动。

---

## 2. step 0 · 收口

`_ready_to_reap` 不变,见 [`03-v2-as-built.md` §2](03-v2-as-built.md)。

---

## 3. step 1 · 谁欠谁

### 3.1 `complaints(module, events) -> list[dict]`

```python
for rule in rules.FORWARD_PRIORITY:
    hit = _latest_fail(events, rule)
    if hit is None:
        continue
    idx, outcome = hit
    c = _owner(module, events, rule, idx, outcome)
    if c["owner"] and _answered(events, idx, c["owner"]):
        continue
    out.append({"rule": rule, "run": outcome["run"], **c})
```

**一条子句:**

```
open(c) = ¬( owner 存在 ∧ owner 自这次失败之后被派过 )
```

三种情形是它的三个取值,不是三条规则:

| owner | 派过了 | 结果 |
|---|---|---|
| 有 | 是 | **关闭** —— 该动手的已经轮到过,这条规则可以重验了 |
| 有 | 否 | **开着** —— 冻结这条规则 + 把失败交给 owner |
| **无** | (空真为假) | **开着** —— 冻结 + 升级。没有 owner ⇒ "owner 派过了"永远为假 |

第三行不是特例,是前两行的退化:**没人可派,所以永远没人派过**。`有主/无主`这个词消失,`facts.inputs_unchanged` 这个子句消失。

人介入 = `kernel.py diagnose` 落一条归因 = owner 出现 = 自动回到前两行。这也是无人可派时唯一的解冻路径 —— 而那本来就是应该有人看一眼的时刻。

> **代价,写在明处**:一条没人能归因的失败会把那个 stage 冻到有人 `diagnose` 为止,不再因为"输入漂了"自动解冻。可接受的依据是:闭包非空的 7 个 stage 契约上都要求 fail 时指名(`skills/*/SKILL.md`,如 power-analysis 的"`--fix-owner` on every failure, tool and license failures included"),`simulation` 有 triage 兜底,而 `specification` 的输入闭包为空 —— 它的失败**结构上**永远无法自动路由,新老方案都只能停下来叫人。

### 3.2 `_owner(module, events, rule, idx, outcome) -> dict`

调度器读"为什么失败"的唯一入口。返回的键与 03 相同(`attribution` / `owner` / `diagnoses` / `unreliable`),但内部从两条通道 + 守卫,变成**一条 or 链**:

```
owner =
  ① None                              判它的 oracle 已被 reopen 且未重新 pin
  ② 有 active diagnosis → 由它说了算     可靠 → 它的 fix_owner;不可靠 → None(终止,不再往下)
  ③ 信封里合法的 fix_owner              _declared_owner + _legal
  ④ 该规则声明的 Rule.triage            没人指名时,该动手的就是分析器
  ⑤ None                              没人可派
```

三处变化:

**① 判决被撤回 → 归因失效,而不是申诉关闭。** 03 里这是 `facts.verdict_trustworthy` 的条件 3,后果是"当没发生过"→ 前向重验。新的落法是:reopen 一个 oracle 的意思是"我不再为这个 judge 背书",那么**不能拿它的判决去指使上游改东西** —— 正确后果是交给人,不是当没发生。危害仍被挡住(仓库里有 `test_re_reap_does_not_dispatch_upstream_rework` 守着),而 `complaints` 少了一个调用。

条件 4(这一轮自己的产物漂了)**直接删**:边际价值极低(有人手改了失败报告),而它是 `complaints` 里唯一还需要读磁盘产物指纹的地方。

**② 是终止分支,不是穿透。** 一旦有人分析过这条失败,分析结果说了算 —— 包括"说不出"(不可靠 → owner=None → 升级)。所以 03 里 `_group` 那个 `not c["unreliable"]` 守卫**自动消失**:分析过且不可靠的失败,`owner` 已经是 None,永远走不到 ④。

**④ triage 是 or 链里的一档,不是第三个桶。** 它就是"没人指名时该动手的那个",于是:

| 事件 | owner 变成 | open? |
|---|---|---|
| sim 失败,信封没指名 | `simulation-triage` | 开着 → 派 triage |
| triage 在途 | 同上 | **关闭**(在途算派过)—— 但反链挡住 sim 重跑,见下 |
| triage reap 成 `blocked` | 同上 | 重新开着 → 再派一次 triage(与今天一致) |
| triage 带回可靠归因 | **变成** 归因的 `fix_owner` | owner 变了 ⇒ "rtl-design 派过吗?没有" ⇒ 开着 → 路由 |
| triage 带回不可靠归因 | `None` | 开着(永远)→ 升级 |

第四行是这个设计成立的关键:**owner 是每次重新求值的,不是记下来的**,所以 owner 一换,"派过没有"这个问题的主语就跟着换。

> **必须配套的注册表一行**:把 `simulation` 声明为 `simulation-triage` 的输入。
> 原因是第二行 —— triage 一被派,申诉就关闭,冻结解除,`simulation` 会趁 triage 分析时重跑一遍(54min)。声明之后 `simulation ∈ input_closure(simulation-triage)`,反链就会挡住它。
> 这行声明本来就该有:**triage 确实要读那次失败的 simulation run**(今天靠 `sim_run` 参数拿路径,注册表却说它不消费 simulation)。而且安全:triage 的 `proof=None`,`facts.rule_available` 对无 proof 的规则直接短路返回 True,所以声明输入**不影响可派性**,只影响闭包。

### 3.3 `_answered(events, idx, owner) -> bool`

不变。判"owner 被派过",不是"被 `caused_by` 点名过";在途算派过;reap 成 `blocked` 不算。

在新模型里它承担得更多 —— 它是**唯一**的关闭条件。

### 3.4 `_group(open_) -> (repair, unowned)`

```
repair  : {owner → [它欠的申诉…]}      ← triage 也在这里,它就是一个普通 owner
unowned : [没人可派的申诉…]
```

三个桶变两个。合并仍然是 `groupby(owner)` 的直接结果。

### 3.5 `_escalation(c) -> dict`

四种理由不变,加一种:

| `attribution` / 状态 | 理由 |
|---|---|
| **oracle 已被 reopen** | `<rule>: the oracle that judged this failure was reopened` ← 新增 |
| 有 unreliable 归因 | `unreliable diagnosis for <rule>` + `candidates[]` |
| `None` | `<rule>: envelope named no fix_owner` |
| == 失败的规则自己 | `<rule>: fix_owner is itself, in-stage remedy exhausted` |
| 闭包外的规则 | `<rule>: fix_owner '<x>' is outside its input closure` |

---

## 4. step 2 · 派一个

### 4.1 `required_proofs` + `_forward_work`

不变。目标集收窄仍然兼任"修完切回来验证"的机制:失败的 proof 一直留在 `work` 里,被冻结过滤器挡着,闸门一开就重验。

### 4.2 `_candidates(...)` —— 三个过滤器 + 一个选择

```
候选池 = (work ∪ repair.keys) − complained          ← triage 已在 repair.keys 里
```

| 过滤 | 判据 | 为什么 |
|---|---|---|
| ① 冻结 | `− complained` | 重验一个没人答复的失败 = 花一轮重新发现已经写下来的东西 |
| ② 可用 | `facts.rule_available` | 生产者的 proof 无效时拿不到可用输入 |
| ③ **无冲突** | `_unblocked(r, pending, inflight)` | 见 §4.3 —— 反链与"闭包极小"合成一个 |
| ④ advisory | `_held_by_advisory` | 便宜的探测器先说话 |

排序三档不变:`先答申诉 → task 先于 main-thread → FORWARD_PRIORITY`。

### 4.3 `_unblocked(rule_name, pending, inflight) -> bool`

03 里这是两个东西:`_antichain_ok`(对在途)和一个单独的"闭包极小"筛(对同批候选)。它们说的是同一件事 —— **别在会被改动的输入上开工** —— 只是一个看在途、一个看同批。合成一个:

```python
def _unblocked(rule_name, pending, inflight):
    """pending = 在途 ∪ 本轮其它候选。"""
    if any(p != rule_name and p in rules.input_closure(rule_name) for p in pending):
        return False          # 生产者在途 或 也在本轮候选里 → 等它
    if any(rule_name in rules.input_closure(f["rule"]) for f in inflight):
        return False          # 消费者在途 → 撕裂读
    return True
```

两个子句方向不同,而且**第二句只对在途生效**:如果对同批候选也生效,两个有上下游关系的候选会互相挡住而死锁 —— 生产者被"消费者也在候选里"挡住,消费者被"生产者也在候选里"挡住。对同批候选,正确处理是"生产者先走、消费者等下一轮",这正是第一句。

### 4.4 `_dispatch_action(module, rule, repair, unowned) -> action`

少一个参数(没有 `triage` 桶了),少一支分支。`params={"sim_run": N}` 的判断改成:被派的规则声明了 `params` 就填 —— 从 `repair[rule]` 里那条申诉取 run 号。

---

## 5. step 3 · 收尾

`_settle` 不变,见 [`03-v2-as-built.md` §5](03-v2-as-built.md)。

---

## 6. 与落地版的差异一览

| | 03 落地版 | 本文 |
|---|---|---|
| 申诉开着的判据 | 三问四支(判决算数 / 有主-派过 / 无主-输入没漂) | **一条子句** |
| `facts.verdict_trustworthy` | `complaints` 调用它 | 条件 3 变成 owner 求值的第一档;条件 4 删 |
| `facts.inputs_unchanged` | `complaints` 调用它 | **删** |
| 归因求值 | 两条通道 + 守卫 | **一条 or 链**,五档 |
| `unreliable` 守卫 | `_group` 里一条 | **自动消失**(② 是终止分支) |
| triage | 第三个桶 + 专用分支 | **or 链里的一档**,普通 owner |
| 闭包冲突 | `_antichain_ok` + 闭包极小筛 | **一个 `_unblocked`,两个子句** |
| 注册表 | — | `simulation` 声明为 `simulation-triage` 的输入 |
| 概念词 | 申诉 / 有主 / 无主 / 判决算数 / 可靠 / 反链 | **失败 / owner / 派过没有 / 反链** |

## 7. 预期的行为变化(必须实测)

变化应当**只落在三类格子**上,其余 1781 状态 + 135 episode 逐格不变:

| # | 情形 | 03 | 本文 | 判断 |
|---|---|---|---|---|
| Δ1 | 无人可派的失败 + 输入漂了 | 关闭 → 前向重验 | 一直开着 → 冻结 + 升级 | 更诚实:没人知道它为什么挂,就该有人看。代价是需要一条 `diagnose` 解冻 |
| Δ2 | 判它的 oracle 被 reopen | 关闭 → 前向重验 | 归因失效 → 升级 | 更严:不拿被撤回的 judge 去指使上游 |
| Δ3 | sim 失败没人指名、且上游刚改过 | 前向重验 sim(54min) | 先派 triage(便宜的 `task`) | 大概率更省,但**没有实测**——见下 |

**Δ3 是必须先补测量的**:现在 135 个 episode 里 `simulation-triage` 跑了 **0 次**(episode 集只生成 `env:` 类缺陷),triage 通路从没被端到端量过。上这个模型之前要先把 triage 通路加进 episode 集,否则 Δ3 是一个没有数字支撑的判断。

## 8. 落地顺序

1. episode 集补上 `none` 类缺陷,覆盖 triage 通路;顺带修正 `00-scenario-space.md` §7 里"triage 环路有覆盖"那句错话
2. 注册表加一行(`simulation` → `simulation-triage` 的输入),验证 1781 + 135 逐格不变(反链新增的那条边只在 triage 在途时生效)
3. 上本文的 step 1 / step 2,再逐格对照 —— 变化必须只出现在 Δ1 / Δ2 / Δ3 三类
4. 本文取代 `03-v2-as-built.md`
