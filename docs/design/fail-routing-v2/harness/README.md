# fail-routing harness

`../00-scenario-space.md` 的测量脚本。结论去那份文档,这里只讲怎么跑和怎么改。

```bash
python3 space.py                          # 场景空间 + 完备性统计(不落盘)
python3 run_grid.py --tag baseline        # 1781 个状态,每个一次 decide 循环   ~75s
python3 report.py --tag baseline          # 表格 + 6 条性质
python3 report.py --anomaly A3 --show 20  # 某条性质的反例
python3 episode.py --tag baseline         # 135 个 episode 跑到收敛           ~75s
python3 episode_report.py --tag baseline --diff v2
```

无外部依赖:整棵模块树从 `rules.py` 合成。输出落 `../out/`。中间树落 `$VP_SCRATCH`(默认在会话 scratchpad,跑完即删)。

| 文件 | 角色 |
|---|---|
| `fixture.py` | 模块树 + 事件构造 + `drive`(decide→真 `cmd_dispatch`,不 reap)+ `started_together` |
| `space.py` | **场景空间的 SSoT**,全部从 `rules.py` 推导:闭包关系、归因形状、1781 个场景 |
| `run_grid.py` | 状态网格:一个场景 = 一个状态,记录它引出的动作序列 |
| `report.py` | 网格的表格与 6 条性质(`PROPS`) |
| `episode.py` | 多轮回放 + 诚实执行器(只修 `caused_by` 点名的缺陷)+ 机时账 |
| `episode_report.py` | 相对 registry 下界的浪费,以及两个 tag 的逐格 diff |

## 改的时候注意

- **场景不要手写**。新增一个 rule 或改一条 `inputs` 选择器,`space.py` 会自动改变场景集;手写清单会静默失配。
- `fixture.OUTPUTS` 是唯一的手写映射(每个选择器一个产物)。加了新的 output 选择器要在这里补,否则下游的 `input_available` 会假性不可用。
- `space.PRIVATE_OUTPUT` 必须是**没有任何消费者**的产物:它是"只让这一个 proof 失效"的手段,选错会让 stale 沿边扩散,`forward-pair` / `inflight` 两类就失去意义。
- `fail()` 同时写 canonical 和 `runs/<N>/result.json`。少写后者,带 `--caused-by` 的真 dispatch 会被内核拒绝(它要求那条失败的 per-run 信封存在)。
- episode 的执行器模型是**诚实**的(只修被告知的)。放宽它会凭空造出"顺手修好"的一档 —— 2026-07 那次就是这么得出过一个后来撤回的结论。
