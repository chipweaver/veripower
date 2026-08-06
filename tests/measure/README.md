# `tests/measure/` — 调度器度量装置

三台装置，一个目的：**改动 `decide` 之后，它的行为动了多少。** 都不是断言集——没有一条会
fail，输出是数字，由人读。所以它们不在 `tests/README.md` 的三个桶里。

| 装置 | 规模 | 问什么 | 看不到什么 |
|---|---|---|---|
| `scheduler/run_grid.py` | 1781 个状态 | 从这个状态出发，`decide` 做什么 | 一个状态只取**一个动作**，且从不 reap |
| `scheduler/episode.py` | 180 个 episode | 跑到收敛要多少机时，相对注册表下界浪费多少 | 数的是**轮数**，不是重叠 |
| `replay/replay.py` | 60 个决策点 | 在一条**真**轨迹上，是否与真实编排者动作相同 | 只有一条轨迹、一个设计，且不做反事实 |

前两台的场景从 `rules.py` 推导，是面；第三台的每个点都真实发生过，是点。合成的盲区正是「什么
时候开跑」这类改动——它在网格和 episode 上都可以是零变化，而它恰恰是墙钟成本所在。三台一起看，
才有覆盖。

```bash
cd tests/measure/scheduler && python3 run_grid.py --tag <t> && python3 report.py --tag <t>
cd tests/measure/scheduler && python3 episode.py --tag <t> && python3 episode_report.py --tag <t> --diff <base>
cd tests/measure/replay   && python3 replay.py --scripts ../../../framework/scripts --tag <t> --log <events.jsonl>
```

每台的细节、保真度和改它时的注意事项，在各自的 `README.md` 里。输出落各自的 `out/`，不进版本库。
