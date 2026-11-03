# Gate 4A 报告 — Workload Qualification 与机制激活（2026-11-02）

Gate 4A 范围（按授权）：(1) 构造并资格审定**非 toy** 的受控工作负载（W1 重叠高斯混合、W2 非均匀+边界向量）；(2) 在小内存预算下**激活并验证** Gorder 窗口（G3-11）与 Cache 驱逐（Gate 2 遗留）两个此前从未运行的机制；(3) 在隔离副本修复 G3-03 并回归；(4) 复查 G3-01 的"中心不在自身桶"现象。**不包含**：Gorder-off / Belady-vs-LRU / 剪枝变体的性能消融（这些属于 Gate 4B，本文只给出设计与停止条件，§11）。所有工作位于 `workspace/gate4a/`，参考仓库 `reference/DiskJoin` 只读、保持在 pin SHA、未被修改。

---

## 1. Executive Summary

| 判定项 | 判定 | 关键证据 |
|---|---|---|
| A. WORKLOAD_READY（受控工作负载可用） | **PASS** | 3 个 pilot：P1 PASS（GT 密度 3.72%）、P2 FAIL（29.57% > 20% 上带，如实记录）、P3 PASS（0.85%）；独立种子 holdout 单次通过：W1H PASS（3.68%）、W2H PASS（0.91%）。全部 5 组 precision=1.0（FP=0），recall 63.9%–90.7%（由合法任务剪枝产生 FN，属算法设计语义） |
| B. GORDER_READY（窗口机制激活） | **PASS** | 小预算下 window=4 < cluster_num=120，`window_removals=116`（W0/P1/P3 全部触发）；独立 harness 16/16 PASS；任务多重集（按目标桶键控）跨 window=2026/1294/4 完全相同 → 窗口只改执行顺序，不改任务集合 |
| C. CACHE_READY（驱逐机制激活） | **PASS** | capacity=62 槽 < 120 桶：W0 evict=48/reject=10、P1 evict=92/reject=18、P3 evict=67/reject=35；pair 集合跨预算不变（190,149 / 59,151 / 223,500）；构建产物字节级相同；ASan（修 G3-03 后）干净；离线策略模拟可区分 Belady/LRU（P1: 172/174 vs 301 misses） |
| Gate 4A 总判定 | **PASS** | A∧B∧C 全 PASS。Gate 4B（最小消融矩阵）已具备执行条件，设计见 §11，本轮**未执行** |

关键发现（超出原假设的部分）：

1. **确定性根因**（G3-14 落实）：`one_level_kmeans` 的中心图构建用 `#pragma omp parallel` `addPoint`，OMP>1 时逐次运行不确定；在重叠数据（W1）上经由 `add2choice` 传入分配与 pair 集合（found 190,050/190,171/190,057 三次 OMP=4 运行，recall 波动 0.6386–0.6390，全部 TP）。**OMP=1 完全比特级确定**（metadata/hnsw/pairs 三项逐字节相同）。→ 所有受控对照一律 OMP_NUM_THREADS=1。
2. **G3-01 更正**：gate3 审计脚本 check 6 自身有 bug（桶下标 vs 数据 ID 混淆）；真实行为是 **120/120 中心都在自身桶内**（P1 与 toy12k 双重独立复核）。“2-choice vs 最近中心”的论文-代码不一致仍然成立（§10）。
3. **error_bound 的实际语义**（G3-10 落实）：剪枝从 top-K 候选列表远端按 arcos 表累加角度；eb ≤ 远端首角度（W1 中位 ~0.89 rad）时完全惰性，eb=1.0 才开始剪（W1: 1484→1435 任务，recall 63.89%→63.09%；W2: 1685→1594，86.95%→85.80%）。
4. **mem_budget 的三重身份**：同一参数同时决定 (a) ClusterWriter 写缓冲、(b) Cache 容量、(c) Gorder 窗口；其中只有 (b)(c) 影响搜索阶段，分配/任务/pair 集合与预算无关（OMP=1 下验证）。

---

## 2. 实验范围和资源

**参考仓库状态**（未触碰）：`git -C reference/DiskJoin rev-parse HEAD` = `aa86151f97527b1dcf9a032d523c1d67d892454a`，`git status --short` 空。全部实验基于隔离副本。

**隔离副本** `workspace/gate4a/instrumented/DiskJoin`：由 `git archive` 从 pin SHA 物化，本地 git 管理 6 个 commit（工作树 clean，无未提交改动）：

| commit | 内容 |
|---|---|
| `0cda02a` | reference archive of aa86151 |
| `f8d6f2e` | gate3 插桩（GATE3_PAIR_OUT / GATE3_INVARIANTS，复用 gate3 产物） |
| `f1ba740` | gate4a 插桩：Gorder 窗口滑移计数、Cache admit/evict/reject 计数+访问 trace、config 分解打印、任务图 dump（全部 env 门控、print-only） |
| `eafa7ae` | **G3-03 修复**（`delete[]`→`free`，§9） |
| `47d92b4` | 修复我方插桩打印的 `%zu` varargs UB（仅仪表代码，§12.3） |
| `0a82b10` | GATE4A_KNN_OUT 原始候选 dump（knn 后、剪枝前） |

**插桩原则**：所有计数/打印/dump 由环境变量门控（`GATE4A_STATS`、`GATE4A_TASK_OUT`、`GATE4A_CACHE_TRACE`、`GATE4A_KNN_OUT` + gate3 的 `GATE3_PAIR_OUT`、`GATE3_INVARIANTS`），不改变算法逻辑；G3-03 修复除外（§9，语义等价、ASan 验证）。

**复用 Gate 3 工具**（未重写）：`../gate3/oracle/{oracle_pairs.py, compare_pairs.py, audit_metadata.py}`（oracle GT、pair 对比、metadata 审计；注意 audit check 6 的 bug 见 §10）；Cache 离线 harness 模式沿用 gate3 的 `cache_test.cpp` 思路。

**新增工具**（`workspace/gate4a/oracle/`）：
- `gen_workload.py` — W1/W2 确定性数据生成器（纯 stdlib，float32 逐级舍入，§4）
- `qualify.py` — 资格审定聚合器（GT/found/tasks/metadata/log → 单一 JSON + 工程筛选判据）
- `gorder_test.cpp` — 链接到真实 `order_gorder()` 的确定性窗口行为 harness（§7）
- `g3_01_investigate.py` — G3-01 独立复查（§10）
- `trace_policy_sim.py` — 冻结 trace 的离线 Belady/LRU 模拟（§8、§11）

**构建**（out-of-tree，BUILD_JOBS=4）：`build/{prefix_normal, prefix_asan, postfix_normal, postfix_asan}` — G3-03 修复前后各一对，全部编译通过。

**资源纪律**：CPU ≤4 线程（构建 -j4；非对照 smoke 运行 OMP=4；**受控对照一律 OMP=1**）；单次运行均 <180 s（实测 join ≤2 s，最长的 oracle GT 窗口扫描 ~2 min）；gate4a 新增产物共 ~79 MB（data 3.7M + runs 67M + logs 168K + build 6.3M + instrumented 1.1M），远低于 ~2 GiB 上限；24 核共享服务器未独占；无 GPU/sudo/安装/下载；正确性（pair dump）与计时运行分开。

---

## 3. 原始 Toy 的局限（为什么需要 W1/W2）

Gate 2/3 的 toy（3k/12k，良分离簇）对 Gate 4B 的消融有三个结构性障碍：

| 局限 | toy 上的表现 | 对消融的影响 |
|---|---|---|
| recall 恒为 1.0 | GT=found 全等（3k 223,500/223,500；12k 3,594,000/3,594,000），FN=0 | 剪枝消融（eb 扫描）无可见信号——W0 上 eb∈{0.01..1.0} 任务数恒 470 |
| 类结构单一 | 等大小簇、单一 σ、无跨簇 pair | 无法考察重叠/密度对 recall-FN 结构的影响 |
| 无近邻边界 pair | 无距离 ≈ ε 的向量对 | G3-06（`<` vs `≤`）与边界敏感性不可测 |
| 机制未激活 | Gorder window=1746 ≫ 120（`window_removals=0`）；cache capacity=20971 ≫ 120（evict=0） | Gorder/cache 两个因子各自只有单一取值，无法做对照 |
| 评估口径 | 打印 recall 为 `%100000` 采样（G3-02） | 小数据上只有 ID 0 被采样，信息量≈0 |

W1/W2 的设计目标就是补齐这四点：重叠簇（recall<1、有 FN 结构）、非均匀（桶大小/度分布失衡）、显式 ε 边界向量（G3-06 可测）、以及（配合小 mem_budget）激活窗口与驱逐。W0（toy3k）保留为"已知答案"的正交对照。

---

## 4. W1/W2 数据生成方法

生成器 `oracle/gen_workload.py`（纯 stdlib，种子确定，逐向量、逐坐标过 float32 舍入，`.fbin` = `<n:u32><d:u32>+n×d×float32 LE`；config 按固定 10 字段顺序写绝对路径；`gt` 字段 = ID-0 邻域大小，仅诊断用途——评估一律用全量 oracle）。

**共同参数**：n=4000、d=16（AVX2 要求 8|d）、cluster_num=120、K=24；pilot 种子 283，holdout 种子 1283（一次生成、单次运行、**不迭代**）。

**W1（重叠等大小高斯混合）**：40 个类中心均匀取自 [−box, box]^d，每坐标加 σ 高斯噪声，类大小相等（100）。

**W2（非均匀 + σ 混合 + 边界向量）**：
- 类大小 Zipf 化（`1/i^0.9` 权重，实测 792..29，总和恰 4000）；
- σ 三档 {tight=0.03, mid=0.08, loose=0.13}，与类大小反相关（大类 loose、小类 tight；实测 13/13/14 分布）；
- 20% 向量为**边界向量**：选同类锚点，单位随机方向，置于距离 t·ε（t ∈ {0.90, 0.93, 0.96, 0.99, 1.00, 1.01, 1.04, 1.07, 1.10}），float32 舍入后记录实际距离（`*_meta.json` 的 margin 表）。

**radius 预登记规则**：W1 取类内成对 sq-L2 的 p50（P1: 0.196→0.2；P2: 0.441→0.44）；W2 的 radius 先行冻结为 0.2（边界向量构造需要预先固定的 ε，避免对结果调参）；holdout 的 radius 直接沿用 0.2，不做任何调整。pilot 数量 ≤6 的约束下实际使用 3 个（P1/P2/P3）+2 个 holdout（W1H/W2H）。

**生成即记录**：每次调用写出 `<name>_meta.json`（生成参数、类内/跨类距离分位数、W2 边界 margin 表），距离统计供 radius 预登记用，不回看 join 结果。

各数据集距离分布（类内 vs 跨类 sq-L2 分位数，采样）：

| 数据 | 类内 p50 | 跨类 p01 | 说明 |
|---|---|---|---|
| P1 | 0.196 | 0.170 | 类内/跨类分布重叠（设计目标） |
| P2 | 0.441 | 0.204 | σ 更大、box 更小 → 密度失控（29.6%） |
| P3 | 0.264 | 0.214 | 三档 σ 混合；边界向量另加 |

---

## 5. Workload Qualification 结果

工程筛选判据（预登记，`qualify.py` 内置）：GT>0；GT 密度 ∈ [0.1%, 20%]；dist_comp > TP；无效候选占比 ≥5%；同时存在相似对与不相似对。

| 数据 | 模式 | radius | GT 对数 | GT 密度 | 判定 | 备注 |
|---|---|---|---|---|---|---|
| P1 | W1 | 0.2 | 297,600 | 3.72% | **PASS** | 全 5 项筛选通过 |
| P2 | W1 | 0.44 | 2,365,253 | 29.57% | **FAIL**（密度超上带） | 如实记录为带边界：recall 42.0%、precision 1.0、comps/GT≈0.97（候选不再显著省于全对）；其余 4 项通过 |
| P3 | W2 | 0.2 | 68,029 | 0.85% | **PASS** | 全 5 项通过 |
| W1H（seed 1283） | W1 | 0.2 | 294,556 | 3.68% | **PASS** | 单次运行，无迭代 |
| W2H（seed 1283） | W2 | 0.2 | 72,502 | 0.91% | **PASS** | 单次运行，无迭代 |

桶结构（资格 JSON 中的分布，说明 W2 达成了非均匀目标）：

| 数据 | 桶大小 min/p50/max | 任务出度 p50/max | 任务入度 p50/max | 真邻域度 p50/max |
|---|---|---|---|---|
| P1 | 4 / 36 / 69 | 12 / 24 | 9 / 65 | 118 / 1,072 |
| P3 | 2 / 29 / 108 | 15 / 24 | 7 / 89 | 6 / 385 |
| W1H | — | — | — | —（见 `runs/qualify_w1h.json`） |
| W2H | — | — | — | —（见 `runs/qualify_w2h.json`） |

资格产物：`runs/qualify_{p1,p1_omp1,p2,p3,w1h,w2h}.json`（`qualify_p1` 为 OMP=4 首跑存档，`qualify_p1_omp1` 为 OMP=1 规范值，两者 recall 差 0.0003，见 §6 确定性讨论）。

P2 的处理方式：**保留为否定样本**。它的作用是把密度带的上界画出来——当 29.6% 的向量对是相似对时，DiskJoin 的候选剪枝几乎不再节省计算（comps/GT≈0.97），此时任何 recall 差异都不再可解释为机制差异。Gate 4B 的公平对照只在 P1/P3（及 holdout 复核）上进行。

---

## 6. GT / Recall / Candidate Efficiency

**评估口径**（处置 G3-02）：全量 oracle GT（`../gate3/oracle/oracle_pairs.py`，窗口剪枝枚举，naive 交叉验证过）vs 全量 found（`GATE3_PAIR_OUT` pair dump，按集合语义比较——dump 顺序依赖线程缓冲拼接，故用 sort/set）。作者打印的 recall 一律不作为结论依据（例：W1H 打印 38/69，oracle recall 67.46%）。

| 数据 | dist_comp | comps/GT | 无效候选占比 | TP | FP | FN | recall | precision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P1（OMP=1） | 1,833,576 | 6.16 | 89.6% | 190,149 | 0 | 107,451 | 63.89% | 1.000 |
| P2（OMP=1） | 2,295,930 | 0.97 | 56.7%* | 993,764 | 0 | 1,371,489 | 42.02% | 1.000 |
| P3（OMP=1） | 3,274,616 | 48.1 | 98.2% | 59,151 | 0 | 8,878 | 86.95% | 1.000 |
| W1H（OMP=1） | 1,897,727 | 6.44 | 89.5% | 198,710 | 0 | 95,846 | 67.46% | 1.000 |
| W2H（OMP=1） | 3,329,837 | 45.9 | 98.0% | 65,746 | 0 | 6,756 | 90.68% | 1.000 |

\* P2 的"无效候选占比"按 (dist_comp−TP)/dist_comp 计算；其绝对值仍然很大是因为分母里包含了大量互相距离 > radius 的类内 pair（σ 大）。

**语义解释**（区分观察与解释）：
- **观察**：所有数据集 FP=0、dup=0、illegal=0（oracle 对比器输出）——join 的输出是 GT 的子集，从不超集。
- **解释（代码审查支持）**：FN 全部来源于任务图的合法剪枝——两个向量被分到（或分配候选任务时被限制在）不相交的桶对。这正是论文用 recall 换 I/O 的近似语义；在重叠 W1 上代价 36%、在非均匀 W2 上代价 13%。
- W2 的 comps/GT（48）远高于 W1（6）：大类（792 向量）自连接任务贡献了大量候选比较。这是 Zipf 结构的直接后果，给 Gate 4B 的 I/O 消融提供了有意义的差异空间。

**W2 边界敏感性（G3-06 落实）**：P3 的 785 个边界向量，锚点 pair 命中率按 t 分档：

| t | 锚点 pair ∈ GT | 其中被 found |
|---|---:|---:|
| 0.90–0.99（舍入后必在 ε 内） | 362 | 278（76.8%） |
| 1.00（float32 舍入后 38 在内 / 43 在外） | 38 | **0** |
| 1.01–1.10（舍入后必在 ε 外） | 0 | — |

t=1.00 内侧 38 对全灭是**观察记录**（成因未定：可能恰落在被剪任务上或桶边界距离处，样本量小，不过度解读）。t<1 的 76.8% 命中率与整体 recall 一致，无额外边界退化。

**error_bound 扫描（G3-10 落实，修正后的真值）**：⚠ 本轮曾因 sed 空格数错误（5 vs 6 空格，config 是 `"%-16s %s"` 格式）得到"eb 惰性"的假结论，已纠正重跑。真值（OMP=1，全量对比）：

| 数据 | eb=0.01 | eb=0.1 | eb=0.5 | eb=1.0 |
|---|---|---|---|---|
| P1（W1）任务数 / recall | 1484 / 63.89% | 1484 / 63.89% | 1484 / 63.89% | **1435 / 63.09%** |
| P3（W2）任务数 / recall | — | 1685 / 86.95% | — | **1594 / 85.80%** |
| W0（toy3k）任务数 | 470 | 470 | 470 | 470（惰性） |

机制（`GATE4A_KNN_OUT` dump + arcos 表逐位复算）：剪枝自 top-K 候选列表**远端**累加 `arcos(x)`，x=(dist/2)/ε 截断 [−1,1]（501 项表）；当 eb ≤ 远端首角度时循环第一步即 break（keep-all）。W1 的 120 桶远端首角度 min/med/max = 0.732/0.892/1.033 rad，仅 5/120 ≥1.0 → eb=1.0 才有个别桶剪枝。**Gate 4B 的 eb 因子取 {0.1, 1.0} 两档**（0.1 为论文默认惰性档，1.0 为实际剪枝档）。

**确定性（OMP 线程数效应，G3-14 落实）**：

| 线程 | found（3 次运行） | recall | 备注 |
|---|---|---|---|
| OMP=4 | 190,050 / 190,171 / 190,057 | 0.6386 / 0.6390 / 0.6386 | 全部 TP（FP=0），集合逐对差异 ~100 对 |
| OMP=1 | 190,149（逐字节相同 ×2） | 0.6389 | metadata/hnsw/pairs 三者 run-to-run 全同 |

根因：中心图 `addPoint` 在并行段执行，插入顺序不定 → 中心 kNN 图非确定 → `add2choice` 分配在重叠数据上翻转。W0（良分离）上即使 OMP=4，任务图/pair 仍逐次相同（mask 了该问题）——这解释了 Gate 3 为何未发现。**受控对照规程固定 OMP=1**（这也是 §11 停止条件之一）。

---

## 7. Gorder 窗口激活验证（处置 G3-11）

**问题**：toy 上 window = 2·(capacity/K) = 2·(20971/24) ≈ 1746 ≫ cluster_num=120，`order.size() > window` 永假 → 窗口滑移（`move_window` 的 old_node ≠ new_node 路径）从未执行。G3-11 判 Confirmed。

**激活方式**（不改代码，只调 `mem_budget`）：window = 2·⌊capacity/K⌋，capacity = budget_bytes/(4·length)，length = max_points·d。选 budget 使 capacity ∈ (K, cluster_num)：W0 用 0.0003、P1 用 0.000255、P3 用 0.0004（float32 舍入后精算 capacity=62、window=4，写缓冲 42/36/56 向量 ≥1，全部满足安全下界）。

**真实运行证据**（`GATE4A_STATS` 的 `[gate4a-gorder]` 行）：

| 数据 | window | insertions | **window_removals** | perm_ok |
|---|---:|---:|---:|---|
| W0（0.0003） | 4 | 120 | **116** | 1 |
| P1（0.000255） | 4 | 120 | **116** | 1 |
| P3（0.0004） | 4 | 120 | **116** | 1 |

（对照：大预算下 W0/P1/P3 的 window 分别为 1746/2026/1294，removals=0——即窗口分支确由预算控制开/关。）

**确定性 harness**（`oracle/gorder_test.cpp`，链接**真实** `order_gorder()`，16 用例全 PASS，`logs/gorder_test.log`）：chain/blocks8/star/random-dag/single/all-self × window ∈ {0,1,2,3,4,5,7,8,10,16,20,30,79,100}。每用例校验：rank 是置换；order 是逆置换（DiskJoin 用法 `order[perm[i]]=i`）；**任务表逐字保留**（slot i 持有 order[i] 的表，head==order[i]，上三角邻居不变，总边数不变）；重复调用输出相同（确定性）。经验式 `window_removals = n − min(window, n)` 在全部用例精确成立（如 n=60,w=30 → 30；w=100 → 0；w=0 → 59）。

**窗口只改顺序、不改任务集合**（关键公平性前提）：不同 window（2026/1294 vs 4）下 Gorder 的 slot 排列不同，但**按目标桶键控的任务多重集完全相同**（P1: 120 桶/1484 边全等；P3: 120/1685 全等）。推论：Gate 4B 中 order 因子（identity/random/Gorder）在同一 bucketization 上比较时，join 的候选任务集合恒定，只有访问顺序与 cache 命中变化。

---

## 8. Cache Eviction 激活验证（处置 Gate 2 遗留）

**问题**：toy 大预算下 capacity=20971 ≫ 120 桶，`filled<size` 永真 → evict/reject 分支从未执行（Gate 2 观察 evict=0）。

**激活**（同 §7 的小预算）+ `[gate4a-cache]` 计数（admit=冷装入，evict=真驱逐，reject=满且新桶下次使用晚于受害者→拒收）：

| 数据 | capacity | total | hit | miss | admit | **evict** | **reject** |
|---|---:|---:|---:|---:|---:|---:|---:|
| W0 | 62 | 470 | 350 | 120 | 62 | **48** | **10** |
| P1 | 62 | 1484 | 1312 | 172 | 62 | **92** | **18** |
| P3 | 62 | 1685 | 1521 | 164 | 62 | **67** | **35** |

（对照：各自大预算下 evict=reject=0，hit=total−120。）

**正确性/不变量检查（全部 OMP=1）**：

1. **pair 集合跨预算不变**：W0 223,500、P1 190,149、P3 59,151 对——小预算与大预算排序后 `cmp` 全等。机制开关（窗口+驱逐同时激活）**不改变输出集合**。
2. **构建产物字节级相同**：clusters/metadata/hnsw 三文件在 budget 0.1 vs 小预算间逐字节相同（P1、P3 验证）。注意对比基线必须同为 OMP=1（OMP=4 的构建产物与 OMP=1 不同，见 §6；曾因基线混用得到假差异，已纠正）。
3. **metadata 审计 PASS**（复用 gate3 `audit_metadata.py`，小预算构建产物）：assignment 是置换、vector_mismatch=0、radius_mismatch=0、centroid 全为数据向量。（该脚本 check 6 打印 `centroid_not_in_own_bucket=120` 是其自身 bug，见 §10；不影响其余检查。）
4. **ASan 干净**（G3-03 修复后，驱逐激活态）：P1/P3 小预算 ASan 运行 0 报错、exit 0。
5. **trace 完整性**（`GATE4A_CACHE_TRACE`）：A 行 seq 严格递增（无并发写乱序，find/push 只在串行段调用）；P 行动作计数 admit/evict/reject 与汇总一致；受害者 ID ∈ [0,120)。

**三重预算效应的隔离**（`[gate4a-config]`/`[gate4a-writer]` 打印 + 公式核对）：

| 量 | 公式 | P1 大→小预算 | 影响 |
|---|---|---|---|
| (a) 写缓冲 | `div_round_up(budget/cn, d·4)·d·4` | 894,784 B（13,981 向量）→ 2,304 B（36 向量） | 仅构建期 I/O 批大小；clusters 字节级相同 |
| (b) cache 容量 | `budget/(4·length)` | 24,314 → 62 槽 | 搜索期驻留桶数（本节） |
| (c) Gorder 窗口 | `2·⌊(b)/(K)⌋` | 2026 → 4 | 重排质量（§7） |

**离线策略可区分性**（`trace_policy_sim.py`，Gate 4B 可行性检查，**非**性能消融）：

| trace（访问序列，容量 62） | C++ Belady miss | 离线 OPT miss | 离线 LRU miss |
|---|---:|---:|---:|
| P1（1484 次访问） | 172 | 174 | 301 |
| P3（1685 次访问） | 164 | 165 | 273 |

结论：真实 trace 上策略间存在 ~1.75× miss 差距 → Gate 4B 的 Belady-vs-LRU 对照在现有 trace 上有区分度。C++ "Belady" 比教科书 OPT 少 1–2 次 miss，源于其拒收分支（新桶下次使用**晚于**受害者时不装入，槽位留给更近的使用者）——这是实现语义差异，非 bug，报告如实记录（§12.4）。

---

## 9. 已知 Bug 的隔离修复与回归（处置 G3-03）

**Bug**（Gate 3 确认，ASan）：`ClusterReader::readMetaData()` 用 `aligned_alloc`（经 `posix_memalign` 家族）分配读缓冲，`~ClusterReader()` 用 `delete[]` 释放 → alloc-dealloc-mismatch（UB）。

**修复（隔离副本内，独立 commit `eafa7ae`，patch `patches/g3_03_fix.patch`，16 行）**：`delete[] buffer` → `free(buffer)`。选择 `free()` 而非改 `aligned_alloc`→`new[]`：释放路径只改一行、不动读路径，且与分配家族匹配。参考仓库不改。

**回归证据**：

| 检查 | 修复前（prefix_asan） | 修复后（postfix_asan） |
|---|---|---|
| ASan 报告（W0） | `alloc-dealloc-mismatch (malloc vs operator delete[])`，栈：`aligned_alloc` @ `readMetaData` vs `operator delete[]` @ `~ClusterReader`，region 294,912 B | **0 报错**，exit 0，recall=1 |
| ASan（驱逐激活态，P1/P3 小预算） | —（修复前未跑） | **0 报错**，exit 0 |
| pair 输出（W0，排序后 `cmp`） | 223,500 对 | **223,500 对，逐字节相同**（修复不改语义） |

日志：`logs/w0_prefix_asan_run.txt`（含完整 ASan 栈，作为修复前证据保留）、`logs/w0_postfix_asan_run.txt`、`logs/p1_small_asan.txt`、`logs/p3_small_asan.txt`。

---

## 10. G3-01 补充调查（更正 gate3 审计脚本的 bug）

**Gate 3 的原结论**：'所有 120 个中心都不在自身桶内'（`centroid_not_in_own_bucket=120`）。

**Gate 4A 发现：该结论是 gate3 审计脚本自身的 bug 所致，予以更正（retract）**。`../gate3/oracle/audit_metadata.py` check 6 的 `elif b not in ids` 把**桶下标 b** 与**数据向量 ID**（与中心逐位相同的数据向量 ID 列表）比较——两个 ID 空间混淆，几乎必然误报。

**独立复查**（`oracle/g3_01_investigate.py`，纯 stdlib，不依赖 C++ 读路径；对 metadata 逐位解析、中心按 float32 字节与源数据向量精确匹配）：

| 检查 | P1（W1） | toy12k（W0） |
|---|---|---|
| 中心匹配到唯一数据向量 | 120/120 | 120/120 |
| **中心的数据 ID ∈ 自身桶 assignment** | **120/120** | **120/120** |
| 重复中心 | 0 | 0 |
| 抽样向量的分配 ∈ {最近中心, 次近中心} | 420 中 356 最近 / 64 次近 / **0 其他** | 420 中 352 / 68 / **0** |
| 全部 120 个中心分配至最近（自身，距离 0） | 120/120 | 120/120 |

结论：(1) "中心不在自身桶"**撤销**——真实行为是全部中心都在自身桶内；(2) Gate 3 的原始发现中仍然成立的部分：分配**不总是最近中心**——抽样中 15.2%（P1）/16.2%（toy12k）的向量被 `add2choice` 放到次近中心，与论文 §5.1 "nearest center" 的表述**不一致**（G3-01 的代码-论文 mismatch 部分维持 Confirmed，只是幅度是"约 1/6 向量偏离最近中心"而非"全部中心不在自身桶"）。§11 的消融不受影响（bucketization 在所有对照中固定）。

已将本更正作为 §10（Gate 3 章）的勘误记入 `HANDOFF.md`（不删除原文）。

---

## 11. Gate 4B 公平对照设计（只设计，不执行）

前置约束（AGENTS.md 硬约束 6 的落实）：数据集、ε(radius)、bucketization（复用冻结的 OMP=1 构建产物 .clusters/.metadata/.hnsw——注意构建阶段不进入对照因子）、候选任务集合、CPU 亲和（同机同线程数）、内存预算、测量窗口、Recall 协议（全量 oracle）全部固定；**线程数一律 OMP=1**（§6 确定性根因）；正确性（pair dump）与计时分开跑；每变体独立 patch + 审计后才比较。

### 11.1 最小矩阵（3 因子，~30–40 次运行，预计分钟级）

| 因子 | 取值 | 实现方式 | 度量（全计数优先） |
|---|---|---|---|
| F1 任务顺序 | identity（slot=桶序，跳过 Gorder）/ random（固定种子 20260101 的 std::mt19937 置换）/ Gorder（现状） | 隔离副本 env 门控的顺序覆盖 patch（任务多重集不变——§7 已证） | cache hit/miss/evict/reject、读盘字节数（≈ miss×桶大小）、dist_comp、join 时延（次要） |
| F2 缓存策略 | C++ Belady（现状）/ LRU | (a) 现有冻结 trace 上离线模拟（已备，P1/P3 trace）；(b) 二进制内 Cache.h 替换 patch + ASan + pair 集合恒等校验 | 同上 + trace 逐事件比对 |
| F3 error_bound | 0.1（惰性档）/ 1.0（剪枝档） | 现有 config 字段（无需 patch） | 任务数、dist_comp、oracle TP/FN/recall、pair 集合 diff |

载体：P1、P3 为主（如需泛化再各加 1 次 holdout W1H/W2H 复核，不做参数迭代）。因子间正交：F1×F2 在 eb=0.1 上做全 3×2；F3 单独扫；共 3×2×2 数据集 + F3 扫描 ≈ 30–40 次 join，单次 <2 s。

### 11.2 停止条件（触发即停并报告）

1. **确定性破坏**：OMP=1 下同一 config 的 hnsw/metadata/pairs 出现 run-to-run 差异；
2. **无因之果**：recall 变化而任务图未变（说明存在未控变量）；
3. **正确性破坏**：任一变体 FP>0（对比 oracle）或 ASan 报错；
4. F1 变体的 pair 集合与基线不恒等（顺序不应改输出，§7 前提被推翻）。

### 11.3 明确不做（本轮授权外）

Gorder-off 的论文级收益结论、10M/100M 数据、真实数据集、多机、任何把 toy 数字外推为 SIGMOD 2026 加速比的表述。

---

## 12. 实际命令、配置、日志、Patch、未验证事项

### 12.1 命令模板（全部实际执行过；exit=0 除非另注）

```bash
# 数据生成（pilot P1 示例；P2/P3/W1H/W2H 同式改参数）
python3 oracle/gen_workload.py --mode W1 --name p1 --n 4000 --d 16 --classes 40 \
  --cluster-num 120 --K 24 --box 0.15 --sigma 0.08 --radius 0.2 --seed 283
# 全量 oracle GT（复用 gate3 工具）
python3 ../gate3/oracle/oracle_pairs.py --fbin data/p1.fbin --radius 0.2 \
  --method windowed --out runs/gt_p1.txt --progress > runs/gt_p1_summary.json
# 规范受控运行（OMP=1；GATE3_PAIR_OUT dump 用于正确性）
OMP_NUM_THREADS=1 GATE3_PAIR_OUT=runs/pairs_p1_t1_r1.txt GATE3_INVARIANTS=1 \
  GATE4A_STATS=1 GATE4A_TASK_OUT=runs/tasks_p1_run1.txt \
  timeout 180 build/postfix_normal/main data/p1.config > logs/p1_run1.txt 2>&1
# 对比 + 资格审定
python3 ../gate3/oracle/compare_pairs.py --gt runs/gt_p1.txt --found runs/pairs_p1_t1_r1.txt \
  --n 4000 --radius 0.2 --fbin data/p1.fbin
python3 oracle/qualify.py --name p1_omp1 --fbin data/p1.fbin --radius 0.2 \
  --gt runs/gt_p1.txt --found runs/pairs_p1_t1_r1.txt --tasks runs/tasks_p1_small.txt \
  --metadata data/p1.metadata --log logs/p1_small_run2.txt --out runs/qualify_p1_omp1.json
# 小预算机制激活（预算精算见正文；eb 扫描 sed 模板）
sed 's/error_bound.*/error_bound      1.0/' data/p1.config > data/p1_eb1.0.config
# Gorder harness；ASan；离线策略模拟
g++ -std=c++11 -O2 -I instrumented/DiskJoin/lib oracle/gorder_test.cpp -o build/gorder_test && OMP_NUM_THREADS=1 ./build/gorder_test
OMP_NUM_THREADS=1 ASAN_OPTIONS=halt_on_error=0:detect_leaks=0 timeout 180 build/postfix_asan/main data/p1_small.config
python3 oracle/trace_policy_sim.py --trace runs/p1_small_cachetrace.txt --capacity 62
```

### 12.2 配置文件（`data/`）

`w0_toy3k{,_smallbudget,_eb0.01,_eb1.0}.config`、`p1{,_small,_eb0.01,_eb0.1,_eb0.5,_eb1.0}.config`、`p2.config`、`p3{,_small,_eb0.1,_eb1.0}.config`、`w1h.config`、`w2h.config`——半径/预算/eb 差异即全部实验变量；n=4000、d=16、cluster_num=120、K=24 恒定。⚠ config 值列有 **6 个空格**前缀（`"%-16s %s"`），sed 改值必须 `s/error_bound.*/error_bound      $eb/`（本轮曾在此踩坑，见 §6）。

### 12.3 我方失误与修复（如实记录）

1. **并行启动数据生成与二进制运行** → 二进制读到半写的 fbin，23.5 GB RSS 孤儿进程（timeout 180 终止）。教训固化为规程：数据集内部步骤严格串行，只跨独立数据集并行。
2. **插桩打印把 float 表达式传给 `%zu`**（varargs UB，输出错位）→ commit `47d92b4` 修复（仅仪表代码）。
3. **sed 少打一个空格**（5 vs 6）→ eb 假惰性结论，已纠正并重跑 §6 真值。

### 12.4 关键日志/产物索引（`workspace/gate4a/`）

| 类别 | 路径 |
|---|---|
| 资格 JSON | `runs/qualify_{p1,p1_omp1,p2,p3,w1h,w2h}.json` |
| GT / found / 对比 | `runs/gt_*.txt|json`、`runs/pairs_*.txt`、`runs/compare_*.json` |
| 任务图 / knn dump / cache trace | `runs/tasks_*.txt`、`runs/p1_knn.txt`、`runs/*_cachetrace.txt` |
| 运行日志 | `logs/`（`*_run*.txt`、`w0_prefix_asan_run.txt`（G3-03 修复前证据）、`p{1,3}_small_asan.txt`、`gorder_test.log`、`*_eb*_run.txt`） |
| Patch | `patches/gate4a_instr.patch`（263 行，f8d6f2e..HEAD，**含** G3-03 修复）、`patches/g3_03_fix.patch`（16 行，单独隔离）、`patches/gate3_instr_reapplied.patch`（116 行，0cda02a..f8d6f2e） |
| 元数据 JSON / 生成器 | `data/*_meta.json`（含 W2 边界 margin 表）、`oracle/` 全部脚本 |

### 12.5 未验证事项 / 局限

1. **PACMMOD 正式 PDF（DOI 10.1145/3769780）仍缺失** → arXiv v2 ↔ 正式版一致性维持 UNVERIFIED（非阻塞）。
2. **knn 近似 ≠ 暴力**：`knnSearchBaseLayer` 返回的 top-K 与按中心暴力最近 24 不同（P1 任务边 1484 vs 1425）→ 任务图依赖近似图；4B 中以冻结 .hnsw 控制之，不声称其为精确 kNN。
3. C++ "Belady" 的拒收分支使其 miss 比"总是装入"的教科书 OPT 少 1–2 次（172 vs 174；164 vs 165）——按实现语义报告，不重贴 OPT 标签。
4. O_DIRECT `read/lseek` 未检查（G3-04）、`%100000` 采样口径（G3-02）、`<` vs `≤`（G3-06）等 Gate 3 遗留风险状态不变；W2 t=1.00 内侧 38 对全灭仅作观察记录。
5. 数字均为单机（Xeon Silver 4310）小数据（n=4k）结果，不构成论文级性能结论。

---

## 13. 最终 Gate 判定

| 判定 | 结果 | 依据 |
|---|---|---|
| A. WORKLOAD_READY | **PASS** | P1/P3 + 双 holdout 通过全部筛选（§5）；全量 oracle 评估口径落地（§6） |
| B. GORDER_READY | **PASS** | 窗口滑移 116 次真实执行（§7）；harness 16/16；任务多重集跨窗口不变 |
| C. CACHE_READY | **PASS** | 驱逐/拒收分支激活且计数（§8）；pair/构建产物跨预算不变；ASan 干净；trace 可区分策略 |

**Gate 4A = PASS**（A∧B∧C）。按本轮授权边界，此处**停止**：不执行 Gate 4B 的任何消融运行。Gate 4B 的最小矩阵、度量与停止条件见 §11；执行前需明确授权。
