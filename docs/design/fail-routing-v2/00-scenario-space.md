# 失败路由重构 · 场景空间与基线

> **这是什么**:重构动手前的第 0 步。把"现有流程中所有可能的并行 stage 组合 × 两者的对错组合 × fix_owner 组合"完整推导出来,在**当前 `main` 代码**上全部跑一遍,拿到基线。重构后跑同一套,出 diff。
> **完备性怎么保证**:场景不是手写清单,是从 `framework/scripts/rules.py` 推导的(`space.py`)。registry 一改,场景集自动跟着改。
> **被测代码**:`main @ 0065bf5`。**测量日期**:2026-08-04。
> **它不是什么**:不是重构方案(见 [`01-v2-design.md`](01-v2-design.md)),不评价 EDA 工具耗时。
> **结果**:v2 已落地并按本文判据验收 —— E1–E6 全部 135/135,A1/A3/A4/A7 全部归零,浪费 12220min → 0。详见 `01-v2-design.md` §5。

```bash
cd harness
python3 space.py                       # 打印场景空间与完备性统计
python3 run_grid.py --tag baseline     # 1781 个状态 → out/grid-baseline.jsonl   (~75s)
python3 report.py  --tag baseline      # 表格 + 6 条性质的违反统计
python3 report.py  --anomaly A1        # 某条性质的全部反例
python3 episode.py --tag baseline      # 135 个 episode 跑到收敛 → 机时账      (~75s)
python3 episode_report.py --tag baseline
```

无外部依赖(2026-07 那套依赖的 `/home/mhc/backup/{asic,eval}` 已不存在,整个夹具改为从 registry 合成)。

---

## 1. 场景空间(推导,非枚举清单)

### 1.1 并行组合:8 个 stage 两两 28 对

判据是**输入闭包偏序**(`rules.input_closure`),不是"有没有直接 artifact 边":

| 关系 | 对数 | 含义 |
|---|---:|---|
| `upstream` / `downstream` | **17** | 一个(传递地)生产另一个消费的东西 → 同时在途是错的 |
| `independent` | **11** | 闭包上的反链 → 唯一合法的并行 |

11 个合法并行对:`plan+rtl`、`plan+lint`、`plan+syn`、`plan+timing`、`lint+syn`、`lint+timing`、`lint+sim`、`lint+power`、`syn+sim`、`timing+sim`、`timing+power`。
其中执行器允许真正墙钟重叠(至少一个 `task`)的更少 —— 见 §2。

### 1.2 对错组合:每对 4 种

`(pass,pass)` / `(只有 A 失败)` / `(只有 B 失败)` / `(两者都失败)`。单失败与配对无关(另一方 pass = 全绿基线),所以按**规则**枚举一次而不是按对枚举。

### 1.3 fix_owner 组合:每个失败规则的全部归因形状

一条失败的归因只可能是下面之一,**这个列表是封闭的**:

```
none | self | outside                      三种非法/缺失形状
env:<O>    ∀ O ∈ input_closure(R)          信封指名一个合法 owner
diag:<O>   ∀ O ∈ input_closure(R)          一条可靠归因指名(sim=triage/high,其余=human)
diaglow:<O>, diagnone                      仅 simulation(只有它背后有 triage)
```

**为什么 `input_closure(R)` 就是全部合法 owner**:两个写入方各自强制这一条 —— `kernel.cmd_diagnose` 拒绝闭包外的 `fix_owner`,`schedule._disposition` 对闭包外的信封指名 ESCALATE。所以对闭包的枚举是**穷举**,不是抽样。`diaglow`/`diagnone` 限定在 simulation:`confidence` 只存在于 triage 归因上,而 `simulation-triage` 是唯一被调度的诊断器。

每规则的形状数:

| 规则 | 闭包大小 | 形状数 |
|---|---:|---:|
| specification | 0 | 3 |
| simulation-plan / rtl-design | 1 | 5 |
| lint-cdc / synthesis | 2 | 7 |
| timing-analysis | 3 | 9 |
| simulation | 3 | 13 |
| power-analysis | 5 | 13 |

`specification` 的闭包为空 —— **它的失败永远无法自动路由**,这是 registry 的结构事实,不是缺陷。

### 1.4 合计 1781 个场景

| 类别 | 数量 | 构造 |
|---|---:|---|
| `all-valid` | 1 | 八个 proof 全 valid(参照态,必须 `DONE`) |
| `forward-pair` | 28 | 两个 proof 因自身产物漂移而 stale(未失败)→ 前向并行能力 |
| `inflight` | 56 | 一个规则在途且 proof 仍 valid(返修派发留下的形状),另一个 stale → 准入 |
| `single-fail` | 62 | 每规则 × 每种归因形状 |
| `both-fail` | **1634** | 28 对 × 形状 × 形状 |

`forward-pair` / `inflight` 用"漂掉一个**没有任何消费者**的产物"来制造 stale(`space.PRIVATE_OUTPUT`),所以只有那一个 proof 失效,不污染其余。

---

## 2. 基线:并行

### 2.1 前向(28 对)

| 关系 | 同回合开两个 | 其中真正墙钟重叠 |
|---|---|---|
| `independent`(11) | 9 | **5** |
| `upstream`(17) | **3** ← 越权 | — |

真重叠的 5 对:`lint+timing`、`lint+sim`、`lint+power`、`syn+sim`、`timing+sim`。
`plan+rtl` 两个都是 `main-thread`,开两个但不重叠;`lint+syn`、`timing+power` 被 advisory 正确压住。

### 2.2 在途准入(56 格)

| 在途者相对另一方 | 准入 | 拦住 |
|---|---:|---:|
| `upstream`(生产者在途) | **17** | 0 |
| `downstream`(消费者在途) | 3 | 14 |
| `independent` | 22 | 0 |

**生产者在途时,消费者 17/17 全部准入。** 因为 `input_available` 读的是生产者 proof 的**当前**有效性,而在途的那一轮要到 reap 才落新指纹 —— 于是消费者基于一份即将改变的输入跑完一整轮。Option C 只覆盖反方向,而且用的是直接消费者(`input_producers`),所以 `timing 在途 → rtl 准入`、`power 在途 → rtl 准入`、`power 在途 → plan 准入` 这三格也漏了。

合计 **23 格违反反链**(3 前向 + 20 准入)。全表:`out/anomalies-baseline.txt` 的 A1 段。

---

## 3. 基线:单失败(62 格)

全表在 `out/report-baseline.txt`。结论只有三条:

- 归因合法(`env:` / `diag:`)→ 一律 `DISPATCH owner`,`caused_by` 一条,`diag` 另带 `diagnosis_refs`。**41 格全部正确。**
- 归因非法(`none`/`self`/`outside`)→ `ESCALATE`,理由分三种。**20 格全部正确**,其中 `simulation(none)` 正确地派 `simulation-triage`。
- `diaglow:*` / `diagnone`(4 格)→ `ESCALATE: unreliable diagnosis`,把候选交给人。正确。

**单失败路径没有缺陷。** 对应地,17 个单缺陷 episode 的浪费全部为 0(§5)。问题全部出在两条失败同时存在时。

---

## 4. 基线:双失败(1634 格)

### 4.1 两条都可路由(472 格)

| 配对关系 | 两个 owner 都被派 | 只派了一个 |
|---|---:|---:|
| `independent` | 76 | **180** |
| `upstream` | 56 | **160** |

**340/472(72%)只答复了一条。** 另一条的合法归因在这一回合被丢弃。

### 4.2 同 owner 的合并(132 格)

| 配对关系 | 合并 | 未合并 |
|---|---:|---:|
| `independent` | 38 | **38** —— 两条来源不同(一条信封 + 一条 diagnosis)时不合并 |
| `upstream` | 0 | **56** —— 一律不合并 |

两个筛子各漏一半(`schedule.py:216` / `148-154`)导致前 38 格;后 56 格是另一个机制:配对里靠下游那条失败,其输入闭包含一个正在失败的 proof,于是 `_fail_is_fresh` 判它 **stale**,它根本不进 `fresh` 列表 —— **归因还在,信封还在,但这一轮没人读**。

> 这 56 格是 2026-07 那份 retrospective **没有测到**的类别(它只测了 independent 对)。它也是机时账里最贵的一类(§5)。

### 4.3 一条可路由 + 一条不可路由(826 格)

540 格整轮 `ESCALATE`。**全部 540 格的不可路由那条都排在 FORWARD_PRIORITY 更靠前的位置** —— 靠前的无主失败垄断了回合,靠后那条合法归因不被使用(retrospective 的 3.6,这里给出了完整边界)。

---

## 5. 基线:机时账(135 个 episode)

`episode.py` 用**诚实执行器模型**跑到收敛:*一轮修复只修 `dispatch.json.caused_by` 点名的那些缺陷,别的什么都不修*。这是与契约一致的最弱假设 —— 一轮什么都没被告知,就什么都不会修。(2026-07 那次的"免费顺手修好"是模型造成的假象,retrospective §8 已撤回。)

**下界**(floor)按 registry 算:每个 owner 派一轮(带上它全部的申诉)+ 每个被这些 owner 产物打掉的 proof 重验一轮。

| 配对 | owner 关系 | n | 零浪费 | 中位 +run | 中位 +min | 合计 +min |
|---|---|---:|---:|---:|---:|---:|
| independent | same-owner | 19 | **19** | 0 | 0 | 0 |
| independent | diff/independent | 8 | 1 | 1 | 54 | 358 |
| independent | diff/upstream | 26 | 0 | 1 | 51 | 1293 |
| independent | diff/downstream | 11 | 2 | 2 | 65 | 709 |
| upstream | diff/upstream | 32 | 0 | 1 | 22 | 1459 |
| upstream | diff/independent | 4 | 0 | 2 | 76 | 250 |
| upstream | diff/downstream | 4 | 0 | 3 | 116 | 359 |
| **upstream** | **same-owner** | **14** | **0** | **4** | **205** | **2870** |

- 单缺陷 17 个 episode:**浪费全为 0**。
- 双缺陷 118 个:**96 个(81%)至少多跑一轮**;合计 **7298 分钟**浪费 / 37084 分钟下界 ≈ **+20%**。
- 全部 135 个都收敛到 `DONE`,无死锁、无 livelock。

最贵的一格,`simulation-plan 失败(指 spec)+ power-analysis 失败(指 spec)`,**+267 分钟 / +6 轮**:

```
spec:2 → plan:3 rtl:2 syn:2 sim:2 power:3(又失败) → spec:4 → plan:5 rtl:4 syn:4 sim:4 power:5 → lint:2 timing:2
        └────────── 整条流水线重建了两遍 ──────────┘
```

两条申诉指向**同一个** owner,信封都在磁盘上,却因为 §4.2 那条 staleness 规则只送达了一条,于是全流程重建两遍。

---

## 6. 出口判据

判据的单位是**结论有没有送到 stage**,不是"派了几个 run"。这两件事在当前实现里并不等价:一轮可以被派给正确的 owner 却什么都没被告知(级联重建的 `dispatch.json` 没有 `caused_by`),那个 stage 就无从判断该不该改。所以"交付"一律以 **`dispatch.json.caused_by` 里出现那次失败自己的 per-run 信封**为准,从磁盘读回,而不是看动作里写了什么。

### 6.1 episode 级(验收门)

| # | 判据 | 当前 |
|---|---|---:|
| **E1** | **任务不丢**:每个缺陷最终被修复,回合收敛 | **135**/135 |
| **E2** | **结论不丢**:每一次失败的信封都送达过它 owner 的 `dispatch.json` | **39**/135 |
| **E3** | **形态正确**:同 owner 的多条合并为一轮;不同 owner 各自一轮(没有哪个 owner 为同一批缺陷被派两次) | **121**/135 |
| **E4** | **无额外重跑**:每个缺陷只失败一次 | **39**/135 |
| **E6** | **最近注入**:一条失败落地到它被交付之间,它的 owner 不得白跑过一轮 | **39**/135 |
| **E5** | **无额外轮次**:总轮数 == registry 下界 | **39**/135 |
| **E7** | **能并行就要并行派**:两个独立且都可启动的规则必须同回合派出 | 见 §6.2 A7 |

分类明细:

| 类别 | n | E1 | E2 | E3 | E4 | E6 | E5 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 单 fail | 17 | 17 | **17** | 17 | **17** | **17** | **17** |
| 双 fail · same-owner | 33 | 33 | 19 | 19 | 19 | 19 | 19 |
| 双 fail · diff-owner/independent | 12 | 12 | 1 | 12 | 1 | 1 | 1 |
| 双 fail · diff-owner/upstream | 58 | 58 | **0** | 58 | **0** | **0** | **0** |
| 双 fail · diff-owner/downstream | 15 | 15 | 2 | 15 | 2 | 2 | 2 |

E6 今天与 E2 恰好同集合(结论从未送达 ⇒ owner 后来跑过的每一轮都是白跑)。它**不冗余**:重构后可能出现"送到了,但送的是 owner 的第二轮",E2 会放过而 E6 抓得住。

**单 fail 已经完全达标** —— 点对点修复、无任务丢失、无结论丢失、零额外重跑。全部 62 种归因形状在状态网格上也一致:34 个有合法 owner 的**全部交付**,28 个无合法 owner 的正确 ESCALATE / 派 triage。

**E2、E4、E5 是同一个集合(逐格相同的 39 个)**,而且逐个 episode 看:

```
丢 0 条结论 → 多 0 次失败 → 多 0 轮     39 个
丢 1 条结论 → 多 1 次失败 → 多 1 轮     42 个
丢 1 条结论 → 多 1 次失败 → 多 2 轮     26 个
丢 1 条结论 → 多 1 次失败 → 多 3 轮     14 个
丢 1 条结论 → 多 1 次失败 → 多 4 轮     10 个
丢 1 条结论 → 多 1 次失败 → 多 6 轮      4 个
```

**每一次额外重跑都恰好可以追溯到一次结论丢失**,放大系数 1~6 轮。这就是文档里 W1/W2 那些账的统一根因:不是"并行开得不够多",是**结论没送到**,于是系统必须靠再跑一次昂贵的 stage 把它重新发现一遍。

### 6.2 状态网格级(定位用)

出口判据说"哪里没达标",这六条说"在状态空间的哪个位置丢的":

| # | 性质 | 当前违反 |
|---|---|---:|
| A0 | 合法结论被**交付**(信封进了 owner 的 `dispatch.json`) | **434**/1781 |
| A1 | 同时在途的两个 run 不得有输入闭包关系 | **23**/1781 |
| A2 | 每条带合法 owner 的失败被某次 dispatch 答复 | **890**/1781 |
| A3 | 指向同一 owner 的两条失败合并为一次 dispatch | **94**/1781 |
| A4 | 不可路由的失败不得挡住可路由的失败 | **540**/1781 |
| A5 | 可靠归因必须被它引发的 dispatch 引用 | **492**/1781 |
| A7 | 能并行就要并行派(两个独立且都可启动的规则同回合派出) | **48**/1781 |

两条都可路由的 472 格里,**434 格一回合只交付 1 条**,交付 2 条的只有 38 格(同 owner 且两条来源相同)。

A7 的适用范围分得很开:

| 场景族 | 成绩 |
|---|---|
| `forward-pair` independent | **9/9 达标**(另 2 对被 advisory 边正当串行,豁免) |
| `inflight` independent | **22/22 达标**(一个在跑,另一个照常准入) |
| `both-fail` 两个 owner 独立 | **0/48** —— 返修路径从不并行 |

**前向已经会并行,返修从来不会。** 因为 step 1 每回合只 disposition 最早那条 fresh 失败,它的 owner 一旦派出,这一回合就结束了。

---

## 7. 这套基线没有覆盖的

- **真产物 / 真信封**:全部合成。调度器只读 `status` 与 `fix_owner`,但别把这里的数字当成某个电路的数据。
- **episode 不走 `kernel.cmd_reap`**:reap 会拿每个 stage 自己的 `result.schema.json` 校验信封,那会把这套实验变成"八个合成信封的生成器"。dispatch 走**真** `cmd_dispatch`(caused_by 解析、scope、dispatch.json 都是落地代码)。
- **`diag:` 类不进 episode**:human 归因绑定单次 outcome_run,重新失败后需要人再判一次,那不是调度器性质。simulation 的 triage 环路**有**覆盖(`none` → 派 triage → 执行器落一条 high 归因)。
- **执行侧的并发是涌现的,不是声明的,而且这里测不到。** `decide` 每次只返回一个动作;`design-flow/SKILL.md` 的循环只有 `YIELD/DONE/ESCALATE` 结束回合,所以 DISPATCH 之后会继续 `decide` —— 并行**只**来自 `task` 的 `Task(run_in_background=True)` 立即返回这一个副作用。整份 Orchestrator 契约里没有一句话提到"一个回合可以有多个 run 在途"。因此本文所有 `n_open` / `started_together` 是**上界**:"照着 loop 走会开几个",不是模型实际会开几个。一个模型在后台 Task 之后结束回合读起来完全自然,而今天没有任何测试会发现。要补:SKILL 明写该不变量 + `tests/scenarios/design-flow/` 加一个"回合结束时 in_flight 有两条"的用例。
- **墙钟重叠是语义推导**(`started_together`),不是实测。
- **三条以上同时失败**:未枚举。两条已经暴露了全部已知机制,但三条的合并/反链行为未测。
- **blocked / 死 run**、多 module 并发:未覆盖。

---

## 8. 下一步

重构完成的定义,就是 §6.1 那张表:

```
E1  135/135      任务不丢                  (已达标,不得回退)
E2   39 → 135    结论不丢
E3  121 → 135    合并/分轮形态正确
E4   39 → 135    无额外重跑
E6   39 → 135    最近注入(owner 不白跑)
E5   39 → 135    无额外轮次
A7   48 → 0      能并行就要并行派(返修路径)
A1   23 → 0      在途集是闭包上的反链
A4  540 → 0      不可路由不挡可路由

外加一条代码测不到、必须靠契约与场景测试守的:
Orchestrator 在后台 dispatch 之后必须继续 loop —— SKILL 明写 + tests/scenarios/design-flow 用例
```

流程:

1. 新调度器接进同一夹具,跑 `run_grid.py --tag v2` 与 `episode.py --tag v2`;
2. `episode_report.py --tag baseline --diff v2` 逐格对照,**任何一格 worse 都要有解释**;
3. 两份 grid 的 1781 行逐行 diff,预期只在 §2/§4 指出的类别上变化;
4. A2 的分母要重新界定:一次 `decide` 只出一个动作,所以它在状态网格上永远达不到 0 —— 它的真正判据是 episode 级的 E2。
