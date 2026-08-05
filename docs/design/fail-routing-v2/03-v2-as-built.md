# 最终方案:归因先澄清,再统一调度

> **这是什么**:失败路由的原样说明 —— 先整体,再逐个函数。和 [`02-v1-as-built.md`](02-v1-as-built.md) 对照着读。
> **状态**:**已落地**。七项逐项走查的裁决见 `01-v2-design.md` §9,验收数字见 §5。
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

两条路,都返回 `REAP`:`--wake <rule>:<run>` 命中一个在途 run;或者扫描全部在途 run 的 workdir,谁写出了 `result.json` 就收谁(多个同时就绪按 `FORWARD_PRIORITY` 取最靠前)。

先收口是为了让后面三步都基于最新日志。`--wake` 有一件扫描做不到的事:**执行器死了、没写 `result.json`**,扫描看不见它,只有 `--wake` 能把它收成 `blocked` 把日志解开。

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

### 3.2 `_owner(...)` —— 一个否决 + 三个信息源

调度器读"为什么失败"的唯一入口。返回 `attribution`(原样写下的指名)/ `owner`(它的可路由投影)/ `diagnoses`(支撑这个 owner 的可靠归因,给 `--diagnosis-refs`)/ `unreliable`(给 ESCALATE 的候选)/ `since`(§3.4)。

**一个否决,加三个信息源,按权威性排序,第一个开口的说了算:**

```python
# 否决:判这条失败的 oracle 被 reopen 了 —— 判决本身不作数
if _oracle_retracted(...):        return 没有 owner

# 源 1:有人分析过这条失败吗?分析过,就以分析为准
diags = _active_diagnoses(...)
if diags:
    latest = diags[-1]
    if _reliable(latest):         return owner = latest["fix_owner"]
    return 没有 owner              # ← 分析过但说不准,到此为止,不再往下问

# 源 2:失败的 stage 自己的信封怎么写的
named = _declared_owner(...)
if named:                         return owner = named if _legal(...) else 没有

# 源 3:注册表说这个 stage 背后有分析器吗
if rules.RULES[rule].triage:      return owner = rules.RULES[rule].triage

return 没有 owner
```

| | 谁在说话 | 为什么排这个位置 |
|---|---|---|
| 否决 | 人(reopen 了 oracle) | 判决的权威被撤回,不能拿它去指使上游改东西 |
| 源 1 | 事后分析(triage / 人的 diagnose) | **后来的分析压过当场的自述** |
| 源 2 | 失败的 stage 自己 | 它是唯一读过原始工具输出的人 |
| 源 3 | 注册表(`Rule.triage`) | 前两个都没答案 → 派分析器去查 |

四点说明:

**① 判决被撤回 = 归因失效,不是"当没发生过"。** reopen 一个 oracle 的意思是"我不再为这个 judge 背书",那就**不能拿它的判决去指使上游改东西** —— 正确后果是交给人。(仓库里有 `test_re_reap_does_not_dispatch_upstream_rework` 守着这个危害。)`facts.verdict_trustworthy` 的条件 4(自身产物漂了)边际价值太低,直接删。

**源 1 是终止分支,不是穿透。** 一旦有人分析过这条失败,分析结果说了算 —— 包括"说不准"(低置信 → owner=None → 交给人)。于是"已经分析过"这个守卫**自动消失**:分析过且低置信的失败,owner 已经是 None,永远走不到 ④。

**源 2 在源 3 之前,就是"triage 是后备通道"这件事的表达。** simulation 有 UVM 参考模型作自己的 oracle,大多数失败它自己就能指名(功能/时延不符 → `rtl-design`,测试点缺失 → `simulation-plan`,规格缺陷 → `specification`);`simulation/SKILL.md` 明写"读了日志和参考模型仍然定位不了才省略 `--fix-owner`,**省略在这里是一个答案,不是耸肩**"。所以源 3 只在源 2 拿不到东西时才轮到。

**owner 是每次重新求值的,不是记下来的。** triage 带回可靠归因后,同一条失败的 owner 从 `simulation-triage` 变成 `rtl-design`,"派过没有"这个问题的主语跟着换,于是申诉自动重新开着 —— 不需要任何"重置"逻辑。

| 事件 | owner | 结果 |
|---|---|---|
| sim 失败,信封没指名 | `simulation-triage`(源 3) | 欠着 → 派 triage |
| triage 在途 | 同上 | 已答复(在途算派过);sim 不会趁机重跑,因为反链挡着(见 §4.3) |
| triage reap 成 `blocked` | 同上 | 重新欠着 → **再派一次**。不设上限,由人自己介入 |
| triage 带回高置信归因 | 变成归因的 `fix_owner`(源 1) | 欠着 → 路由 |
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

### 3.4 `_answered(events, since, owner) -> bool`

判"**owner 被派过**",不是"被 `caused_by` 点名过" —— 问题是"该动手的那个 stage 有没有轮到过",一次因别的原因重建 owner 的轮次同样给过它机会。在途算派过;reap 成 `blocked` 不算(什么都没落成)。

走过 3.3 的早退之后,**这是唯一的关闭条件**:

```
欠着(f) = ¬ _answered(f.since, f.owner)
```

**`since` 是"这个指名何时被知道",不是"失败何时发生"。** 两者在一种情况下不同:分析指出的 owner **早就因为别的原因被派过**。那一轮不可能针对一个当时还不存在的结论做任何事,把它算成"轮到过"就会让这条失败在没人被告知的情况下关闭。所以由 diagnosis 决定的指名,`since` 取那条 diagnosis 的事件位置;信封或分析器决定的,取失败自己的 outcome 位置。

这条是实现时被 episode 下界抓出来的:漏掉它,triage 报回归因后 owner 恰好是先前修另一条失败的那个 stage,于是回归白跑一轮、triage 再跑一轮。

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
    closure = rules.input_closure(rule_name)
    running = {f["rule"] for f in inflight}
    if any(r in closure for r in running):
        return False        # ① 生产者在途:它正在改写我要读的东西(物理危险)
    if rules.RULES[rule_name].proof and any(
        p != rule_name and p in closure for p in pending - running
    ):
        return False        # ② 生产者也在本轮候选里:我的产出会被它作废(逻辑陈旧)
    return not any(rule_name in rules.input_closure(r) for r in running)   # ③ 消费者在途:撕裂读
```

三个子句,不对称之处都是设计:

- **①** 对每条规则都成立 —— 边写边读是物理危险。
- **② 只约束产出 proof 的规则。** 无 proof 的规则(分析器)分析的是**一个冻结的历史 run**,落下的 diagnosis 绑定在那次 run 上,上游怎么重建都作废不了它。压住它的代价是实打实的:它本该指出的 owner 一直不为人知,于是修另一条失败的那一轮无法顺带把这条也修了 —— 实现时这一条让整条流水线多重建一遍。
- **③ 只对在途生效**,绝不对同批候选生效:对同批也生效的话,有上下游关系的两个候选会互相挡住而死锁。对同批候选,正确处理是"生产者先走、消费者等下一轮",那正是 ②。

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

## 7. 与上一版的差异一览

| | 上一版 | 现在 |
|---|---|---|
| 失败开着的判据 | 三问四支(判决算数 / 有主-派过 / 无主-输入没漂) | **一条子句**:owner 没被派过 |
| 归因说不清时 | 挂 `escalations[]` 随派发上报,流程继续 | **整轮停下等人**(step 1 早退) |
| `facts.verdict_trustworthy` | `complaints` 调用 | 条件 3 → `_oracle_retracted`(否决档);条件 4 删 |
| `facts.inputs_unchanged` | `complaints` 调用 | **删** |
| 归因求值 | 两条通道 + 守卫 | **一个否决 + 三个信息源** |
| `unreliable` 守卫 | `_group` 里一条 | **自动消失**(源 1 是终止分支) |
| triage | 第三个桶 + 专用分支 | **源 3**,普通 owner |
| 闭包冲突 | `_antichain_ok` + 闭包极小筛 | **一个 `_unblocked`**,三个子句 |
| `escalations[]` 动作字段 | 有 | **删** |
| 注册表 | — | `simulation-triage` 声明消费 `simulation` |
| 概念词 | 申诉 / 有主 / 无主 / 判决算数 / 可靠 / 反链 / 闭包极小 | **失败 / owner / 派过没有 / 反链** |
| `schedule.py` 最大圈复杂度 | 9 | **9**(函数 25 个,if 40 处) |

## 8. 验收(实测)

180 个 episode(含新补的 45 个 triage 通路),六项判据:

| # | 判据 | 上一版 | 现在 |
|---|---|---:|---:|
| E1 | 任务不丢 | 180 | **180** |
| E2 | 结论不丢 | 147 | **180** |
| E3 | 合并/分轮形态正确 | 169 | **180** |
| E4 | 无额外重跑 | 147 | **180** |
| E6 | 最近注入 | 147 | **180** |
| E5 | 无额外轮次(== registry 下界) | 147 | **180** |

```
episode_report.py --tag v2 --diff v3
  better=33  same=147  worse=0
  总浪费 4960 min → 0 min
```

**180 个 episode 全部跑在 registry 下界上。** 之前 45 个 triage 通路 episode 里有 33 个丢结论,现在 0 个。

状态网格 1781 格里变化 **704 格**,全部落在两类:

| 类别 | 格数 | 说明 |
|---|---:|---|
| 首动作 DISPATCH → ESCALATE | 675 | Δ3:归因说不清就停下等人(裁决第 5 项) |
| 派发目标变化 | 29 | triage 提前(便宜的 `task` 先起),且它现在也拿到失败信封 |

性质表:A1(反链)、A3(同 owner 合并)、A6(不重验未答复的失败)、A7(能并行必并行)**全部 0**;A4 按裁决退休。

## 9. 实现时被基线抓出来的两处

两处都是我在这一版里引入的,靠 180 个 episode 的下界对照发现:

1. **`_answered` 的起点错了**(§3.4)。分析报回的 owner 若早已因别的原因被派过,会被当成"轮到过",于是失败在没人被告知的情况下关闭 —— 回归白跑一轮、triage 再跑一轮。修法:起点取"这个指名何时被知道"。
2. **无 proof 的规则被"生产者也在候选里"挡住**(§4.3)。分析器读的是冻结的历史 run,产出不会被上游作废;压住它导致它本该指出的 owner 一直不为人知,整条流水线多重建一遍。修法:② 只约束产出 proof 的规则。

没有这套下界对照,两处都会静默留下。
