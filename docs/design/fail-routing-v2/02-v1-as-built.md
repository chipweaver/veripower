# v1 原样:改之前 VeriPower 在 flow 上是怎么处理的

> **这是什么**:重构前(`0065bf5`,即本分支之前 main 上的样子)失败路由与并行调度的完整说明 —— decide 怎么走、返修怎么路由、脚本怎么分工、字段怎么流动。
> **为什么留着**:`01-v2-design.md` 讲的是"改成了什么",review 的人需要一份"改之前长什么样"才能判断改动是否对症。这份不评价,只描述。
> **数据来源**:`0065bf5` 的独立 git worktree,实跑对照,不是读代码推的。

---

## 1. 一切围绕一个 append-only 日志

```
                       ┌──────────────────────────────────────┐
   人 / Orchestrator ──▶│  kernel.py  (events.jsonl 的唯一写者) │
                       └───────┬──────────────────────────────┘
                               │ 9 个动词
        decide ─────────────┐  │  dispatch / reap / diagnose / pin / reopen / signoff / status / consequences
                            ▼  ▼
      ┌─────────────────────────────────────────────────────────┐
      │  events.jsonl   6 种事件:dispatch outcome diagnosis     │
      │                          pin reopen signoff             │
      └─────────────────────────────────────────────────────────┘
                               ▲                    ▲
                    磁盘指纹    │                    │  stage 写的 result.json
                    (facts)    │                    │  (reap 时 promote 进 canonical)
                               │                    │
      ┌────────────────────────┴───────┐   ┌────────┴─────────────────────┐
      │ Design/… Verification/… 的产物  │   │ <stage>/runs/<N>/result.json │
      └────────────────────────────────┘   └──────────────────────────────┘
```

**没有任何状态字段。**"这个 proof 还有效吗""哪些在途""该干什么"全部是 (日志 + 磁盘指纹) 的纯函数,每次 `decide` 重算。这一条 v1/v2 一致,是整个架构的地基。

## 2. 五个脚本的分工

| 脚本 | 拥有什么 | 谁调它 |
|---|---|---|
| `rules.py` | **规则注册表 SSoT**:8 个 stage + triage,每条的 `inputs`/`outputs` 选择器、`execution`、`workdir_root`、`oracle`。依赖图**不是**单独维护的,而是从选择器推导(`producer_of` / `input_producers` / `input_closure`) | 所有人 |
| `facts.py` | 日志 I/O、内容指纹、新鲜度查询:`proof_valid` / `input_available` / `rule_available` / `stale_inputs` / `projection`,以及最严的 `signoff_gate` | schedule、kernel |
| `schedule.py` | **`decide()` → 恰好一个动作**。目标集、返修判定、no-overtake 门 | kernel |
| `store.py` | 文件系统生命周期:dispatch 时 `write_dispatch` + `carry_self`;reap 时 `promote` | kernel(从不直接调) |
| `kernel.py` | CLI,**`events.jsonl` 的唯一写者**;`cmd_dispatch` 在写入瞬间复检可派性,`cmd_reap` 从 `result.json` 推导 verdict | Orchestrator / 人 |

## 3. v1 的 `decide`:四步,返回第一个命中的动作

```
  decide(module, --wake?, --closing?)
    │
    ├─ step 0 ── 有没有可以收的 run? ────────────────────────────────
    │     --wake <rule>:<run> 命中在途        → REAP
    │     任何在途 run 的 workdir 有 result.json → REAP(多个按 FORWARD_PRIORITY 取最前)
    │
    ├─ step 1 ── 有没有 "fresh" 的失败? ────────────────────────────
    │     fresh = [每条最新 outcome 是 fail 且 _fail_is_fresh 的规则]
    │     if fresh:
    │         rule = min(fresh, key=FORWARD_PRIORITY)      ← ★1 只取最早那一条
    │         disp = _disposition(rule, …)                 ← ★2 十个分支
    │           ├ _defer_to_forward → 落到 step 2
    │           ├ DISPATCH → 目标在途? 或 有在途消费者(Option C)? → YIELD
    │           │             否则 → 返回 DISPATCH(带 caused_by / diagnosis_refs)
    │           └ ESCALATE / YIELD → 直接返回                ← ★3 整轮结束
    │
    ├─ step 2 ── 前向:把该建的建起来 ─────────────────────────────
    │     required = failing_proofs 或(没有失败时)全部八条  ← 目标集收窄
    │     work     = required 里 proof 无效的
    │     work    += 重建闭包(不可用输入的生产者,递归)
    │     候选过滤: 在途 / 输入不可用 / 有在途消费者 / 被 advisory 压住
    │     if 候选: 取 FORWARD_PRIORITY 最小 → DISPATCH(**没有 caused_by**) ← ★4
    │
    └─ step 3 ── 收口 ────────────────────────────────────────────
          有在途 → YIELD(带 in_flight[])
          required 全 valid → DONE(--closing 时先过 signoff_gate,不清则 ESCALATE)
          否则 → ESCALATE "no eligible rule, none in-flight, not done"
```

四个 ★ 是 §8 全部后果的根。

## 4. 并行:三个来源,三道闸

`decide` 一次只返回一个动作,所以并行不是调度器决定的,是执行器语义 + 循环的副产物:

```
Orchestrator 的回合:
  loop:
     a = decide
     execute(a)
     if a ∈ {YIELD, DONE, ESCALATE}: 结束回合
```

| execution | 执行器 | 对回合的影响 |
|---|---|---|
| `task` | `Task(run_in_background=True)` | **立即返回** → loop 继续 → 下一个 decide 可能再派一个 → 真重叠 |
| `main-thread` | `Skill(veripower:<skill>)` | **同步跑完** → 后面的 decide 都在它结束之后 → 不重叠 |

所以同回合开两个,**只可能发生在 step 2 连续两次给出候选**。step 1 一旦 `DISPATCH` 就 return,下一次 decide 又从头取 `min(fresh)` —— 返修路径结构上只能开一个。

三道闸限制并行:

| 闸 | 位置 | 判据 | 覆盖 |
|---|---|---|---|
| 目标在途 | step1 + step2 | `rule ∈ in_flight` | 防重复派同一个 |
| **Option C** `_has_inflight_consumer` | step1 + step2 | `rule ∈ input_producers(某在途 rule)` | 只防**直接**消费者方向的撕裂读 |
| **advisory** `_held_by_advisory` | 仅 step2 | `ADVISORY_ORDER[rule]` 的前驱无效且"会来" | lint 未过不跑 synthesis;timing 未过不跑 power |

`ADVISORY_ORDER` 是**非数据依赖**的排序边,契约上写死:只被这一个函数读,绝不进入新鲜度、可用性、失败归因。

## 5. 返修:`_fail_is_fresh` + `_disposition` 的十个分支

### 5.1 一条失败要 "fresh" 才会被路由

```
_fail_is_fresh(rule) =
     facts.proof_fresh_except_verdict            ← 除 verdict 外和 pass 路径同样的三条
        条件2  该 proof 记录的每个输入指纹 == 磁盘
        条件3  判它的 oracle 没有在这一轮 dispatch 之后被 reopen(且未重新 pin)
        条件4  该 run 自己的产物指纹 == 磁盘
  AND  input_closure(rule) 里每条 proof 当前都 valid    ← 上游还在传播就算 stale
```

**不 fresh 就完全不路由**,落到 step 2 当作普通的前向重验。

### 5.2 `_disposition` 决策表(只作用于 `min(fresh)` 那一条)

| # | 条件 | 动作 |
|---|---|---|
| 1 | 有 active diagnosis,最新那条 **reliable**,但 `fix_owner` 输入不可用 | `_defer_to_forward` |
| 2 | 有 active diagnosis,最新 reliable,输入可用 | `DISPATCH fix_owner`;合并**所有 fresh 失败中"有 reliable diagnosis 且 fix_owner 相同"的** → `caused_by[]` + `diagnosis_refs[]` |
| 3 | 有 active diagnosis,最新**不可靠** | `ESCALATE "unreliable diagnosis"` + `candidates[]` |
| 4–6 | 无 diagnosis,信封没指名,且 **`rule == "simulation"`** | triage 在途 → `YIELD`;否则 `DISPATCH simulation-triage --params '{"sim_run":N}'` |
| 7 | 无 diagnosis,信封没指名,非 simulation | `ESCALATE "envelope named no fix_owner"` |
| 8 | 信封指了**自己** | `ESCALATE "fix_owner is itself, in-stage remedy exhausted"` |
| 9 | 信封指了**输入闭包外**的规则 | `ESCALATE "outside its input closure"` |
| 10 | 信封指名合法但那个 owner 输入不可用 | `_defer_to_forward` |
| — | 信封指名合法且可用 | `DISPATCH owner`;合并**所有 fresh 失败中"没有 diagnosis 且信封指名相同"的** → `caused_by[]` |

**两个合并筛子各漏一半**:第 2 行只收"有 reliable diagnosis"的兄弟(漏掉信封自述的);最后一行 `continue` 掉"有 active diagnosis"的兄弟(漏掉 triage 归因的)。于是"一条信封自述 + 一条 triage 归因、指向同一个 owner"两边都不收。

`rule == "simulation"` 是 `schedule.py` 里**唯一的规则名字面量** —— 哪个 stage 背后有分析器,本该是注册表的事实。

## 6. 字段的一生

```
① 失败的 stage 自己写 result.json
   { "status": "fail",
     "stage_specific": { "fix_owner": "rtl-design",            ← 谁必须动手
                         "fail_reason": "clock crossing …" } }  ← 为什么这么指(审计)
        │  reap 时 promote 进 canonical <stage>/result.json
        ▼
② schedule._declared_owner 读 canonical 的 stage_specific.fix_owner
        │  合法性检查:非空 / 非自己 / ∈ input_closure(失败的规则)
        ▼
③ decide 返回 action,并把完整 argv 一起给出:
   { "action":"DISPATCH", "rule":"rtl-design", "execution":"main-thread",
     "caused_by":[["lint-cdc",2]],
     "dispatch_args":["dispatch","--module","M","--rule","rtl-design",
                      "--caused-by","lint-cdc:2"] }          ← 不让人手抄,抄就会漏
        ▼
④ kernel.py cmd_dispatch —— 写入瞬间复检 + 解析两个返修通道
     caused_by  "lint-cdc:2" → Design/lint-cdc/runs/2/result.json(不存在就拒绝)
     diag_refs  → scope += diagnosis.fix_locus;reasons += human 的 reason 原文
     scope 起始 = facts.stale_inputs(哪些记录过的输入漂了)
     然后 store.carry_self(把自己上一轮产物拷进新 workdir)
          store.write_dispatch(写 dispatch.json)
        ▼
⑤ <workdir>/dispatch.json —— 内核告诉这一轮的唯一渠道(4 个键,有内容才写)
   { "inputs":   {key: 生产者的 canonical stage 根(绝对路径)},  ← 永远有
     "scope":    ["Design/specification/design.md", "a.v:42"],  ← 这一轮该动哪儿
     "caused_by":["Design/lint-cdc/runs/2/result.json"],        ← 要答复哪些失败(per-run,不可变)
     "reasons":  ["人的判断原文"] }
        ▼
⑥ stage 读 dispatch.json 自行决定改什么
```

**Orchestrator 不写任何内容**:它传坐标(`--caused-by` / `--diagnosis-refs`),内核解析成路径。转述一份机器写的信封只会丢失或扭曲它。

三种归因来源:

| source | 谁写 | 必填 | `_reliable` 判定 |
|---|---|---|---|
| `triage` | `kernel._derive_triage`(triage reap 时自动) | `confidence` | 有 `fix_owner` **且** `confidence == high` |
| `human` | `kernel.py diagnose`(ask-gated) | `provenance` + `reason` | 有 `fix_owner`(human 即终审) |
| 信封自述 | 失败的 stage 自己 | — | **不过这个门** —— 无条件信任,只查合法性 |

最后一行是 v1 的一处不对称:信封自述不受 `confidence` 约束(它没有这个字段),diagnosis 受。两条通道语义不同,是 `_disposition` 必须分两支的根本原因。

## 7. 四个并行场景在 v1 里的实际走法(实测)

| 场景 | v1 第一回合 | 结构原因 |
|---|---|---|
| **A** 同 owner,两条都是信封 | `DISPATCH rtl-design 交付[lint-cdc:2, synthesis:2]` ✅ | 信封分支的合并筛子正好覆盖这一种 |
| **B** 同 owner,信封 + triage 归因 | `DISPATCH rtl-design 交付[lint-cdc:2]` ❌ | 两个筛子各漏一半 |
| **C** 同 owner,配对有闭包关系 | `DISPATCH specification 交付[rtl-design:2]` ❌ | 靠下游那条被 `_fail_is_fresh` 的闭包条件判 stale,没进 `fresh` |
| **D** 不同 owner(spec / rtl,有闭包关系) | `DISPATCH specification 交付[lint-cdc:2]`,然后 `YIELD` | step 1 `min(fresh)` 只处理一条,派完就 return |
| **乙** 不同 owner(rtl / plan,独立) | 同上,一个回合只开一个 | 与"能不能并行"无关 —— 是根本没到第二条 |

D 跑到收口的完整序列(实测 11 轮,v2 是 8 轮):

```
spec:2 ←[lint-cdc:2]          答复 lint 的申诉
plan:2                         前向:spec 改了,plan 要重建
rtl-design:2 ←(什么都没告诉它)  ★ 盲重建:step 2 的 dispatch 不带 caused_by
lint-cdc:3                     重验,过
simulation:3                   ★ 白跑 54min —— sim 的申诉早被判 stale 丢了
rtl-design:3 ←[simulation:3]   重新失败后才路由回去
simulation:4 / lint-cdc:4      再验一遍
syn:2  timing:2  power:2
```

## 8. 结构性后果

| 后果 | 出自哪个 ★ |
|---|---|
| **返修永不并行** | ★1 step 1 取 `min(fresh)`,派完立即 return |
| **级联轮是盲的** | ★4 step 2 的 `_dispatched()` dict 里根本没有 `caused_by` 这个键 |
| **归因随输入漂移一起丢** | `_fail_is_fresh` 把"判决还算不算数"和"世界变没变"压成一个谓词 |
| **靠前的不可路由挡住靠后的可路由** | ★3 `_disposition` 的 ESCALATE 直接 return,整轮结束 |

外加一个谁都没守的方向:`rule_available` 读的是生产者 proof 的**当前**有效性,而在途那一轮要到 reap 才落新指纹 —— **生产者在途时消费者照常准入**,基于一份即将改变的输入跑完一整轮。Option C 只挡了反方向,而且只看直接消费者。

这五条就是 `01-v2-design.md` 要解决的问题清单。
