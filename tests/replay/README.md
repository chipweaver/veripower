# `tests/replay/` — 真实日志重放

拿一次**真跑完的 veripower 运行**的事件日志,逐前缀还原成模块树,在每个决策点问一次 `decide`,与当时真实发生的下一步并排。

不是 pytest 断言集,是**度量装置**:输出是"与真实编排者一致多少个决策点",要人读。`tests/README.md` 的三个桶按"回答哪一个问题"分类,这个目录回答的是**在一条真轨迹上,调度器会不会做出和人不同的动作**,所以单独放。

## 为什么需要它

合成度量的盲区是它自己造的:状态网格取**一个状态的一个动作**且从不 reap,收敛回放集数的是**轮数**而不是重叠。于是"什么时候开跑"这一类改动在两者上都是零变化,而它正是墙钟成本所在。2026-08-05 那批改动(目标集不再收窄、一条失败可以有多个 owner)在网格上 0 格变化、在回放集上逐条 `same`,在这里是 **49/60 → 56/60**。

## 跑

**日志不在库里**,由 `--log` 传入:它是某一次运行的记录,不是插件的产物。任何一份 veripower 的 `events.jsonl` 都能重放;本文的数字取自 `Coral-NPU/submissions/cc-opus5-t1-v3-vp/events.jsonl`(CoreMiniAxi,8 个 child,75 个事件,2026-07-29 → 08-02,该仓唯一走完 `signoff` 的一轮)。

```bash
cd tests/replay
LOG=<某次真跑的 events.jsonl>
python3 replay.py --scripts ../../framework/scripts --tag v4 --log $LOG      # 当前调度器
git archive main framework/scripts | tar -x -C /tmp --one-top-level=vp-v1
python3 replay.py --scripts /tmp/vp-v1/framework/scripts --tag v1 --log $LOG # 对照组
python3 summarize.py                                                         # -> out/replay.txt
python3 probe.py --scripts ../../framework/scripts --log $LOG -k 19          # 某个决策点为什么是那个动作
```

输出落 `out/`,中间树落 `$VP_SCRATCH/vp-real-log-replay/`(默认 `/tmp`)。`summarize.py` 的 `TAGS` 决定对照哪两个 tag。`.gitignore` 挡掉 `out/` 与就地放的 `*.events.jsonl`。

| 文件 | 角色 |
|---|---|
| `replay.py` | 重放器 |
| `probe.py` | 单点诊断:某个 `k` 上每条规则的 `proof_valid` / `rule_available` / `stale_inputs` / 缺失选择器 |
| `summarize.py` | 两个 tag 的分歧集与逐点差异 |

## 保真度

| 成分 | 是真的吗 |
|---|---|
| `schedule` / `facts` / `rules` | 被测版本的代码,无打桩 |
| 事件日志 | **逐字真实**(上面那一份:30 dispatch / 30 outcome / 5 diagnosis / 3 escalation / 6 pin / 1 signoff,含真时间戳) |
| 树的指纹结构 | 每个前缀按 promote 语义还原(一个 stage 的 canonical 就是它最新一次非 blocked outcome 的产物集) |
| 文件字节 | **代理** |
| `<stage>/result.json` | 真 verdict + 真 `fix_owner` |
| stage 执行 | **不模拟**。一个决策点是一个状态,量的是 `decide` 从它出发做什么 |

**代理字节不是打桩。** `decide` 只从磁盘读两件事:路径在不在,指纹等不等于日志里记的某个指纹。它从不读内容。所以把每个指纹经一个双射重贴标签、写下哈希到新标签的字节,调度器能问的每个问题都被保留。标签不靠复刻 `facts.fingerprint` 的公式:每个代理对象先落一次探针目录,再用 `facts.fingerprint` **读回来**。

两条例外是处理掉而不是代理掉的:`<workdir_root>/result.json`(`_declared_owner` 真会读它取 `fix_owner`)写成带真 verdict 与真 `fix_owner` 的信封;`runs/<n>/result.json`(`_ready_to_reap` 扫它是否存在)只在日志的下一个事件正是那个 run 的 outcome 时落盘。

**注册表漂移。** 这一轮比今天的注册表早约一周,18 个今天声明、当时没产出的选择器(`clocks.json` / `check-hints/*` / `tb-scaffold.json` / `conformance-review.md` …)按**每个产出 run** 合成一个文件,带 run 号戳,并注入到每个匹配它的消费者的已记录输入里。不补的话每个下游都 `input_available=False`,重放退化成满屏 ESCALATE。

## 够不到什么

- **一次 `cmd_reap` 都没调用**:promote / `carry_self` / `blocked` 不 promote / 每 stage schema 校验,四条路径零覆盖。
- **不做反事实**:每个决策点都从真实发生过的前缀出发,分歧之后仍按真轨迹继续。
- **closing / signoff 没走**:pin 的 `content_fingerprint` 是对 oracle 选择器取的,双射带不过去。
- **只有一条轨迹、一个设计**。

## 改的时候注意

- **别把它当合成 harness 的替代品**。那套是面,这套是点;它的价值在于那 60 个点是真的,包括合成场景生不出来的形状:一条 `fix_locus` 指向 A、`fix_owner` 指向 B 的归因,一个跑了 1 分钟的 rtl 轮次,一段 50 小时的人类空档。
- **`FIX_OWNER` 里 `power-analysis:1 -> simulation` 是推断的**,不是读出来的(那份信封没进提交快照)。改它就改了 k=62..66 的结论,依据见 `replay.py` 的模块 docstring。
- **`missing_selectors` 是按 run 而不是按 rule 算的**。这一轮跨了插件的一次改版(`rtl-design:1` 产出 `rtl-files.json`,`runs 2-4` 改成 `filelist.txt`),按 rule 取并集会把当时真实存在的缺口抹掉。
- **录成目录的产物(`merkle:`)下面不要再塞填充文件**,否则那个目录的指纹与日志里记的对不上,此后每个前缀的 `proof_valid` 都会静默为假。`missing_selectors` 里有一条守着这个。
