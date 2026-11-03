# DiskJoin Gate 3 报告 — 正确性验证与论文–源码一致性审计

- 日期：2026-11-02
- 项目根：`/home/qch/DiskJoin/diskjoin_repro_pack`
- 参考 upstream：`https://github.com/iidyc/DiskJoin`
- 参考提交（固定）：`aa86151f97527b1dcf9a032d523c1d67d892454a`（2025-06-08，`git status --short` 全程为空）
- 论文版本：arXiv `2508.18494v2`（15 页，文本抽取于 `workspace/paper_text/`）；PACMMOD 正式版（27 页，DOI `10.1145/3769780`）PDF 仍缺失 → 与正式版的逐条一致性记 `UNVERIFIED`
- 上轮状态：Gate 2 `PASS_SMOKE_ONLY`
- **Gate 3 判定（两个独立结论，勿混同）：**
  - **A. Audit Completion = `PASS`**
  - **B. Algorithm Correctness = `PASS_WITHIN_TESTED_SCOPE`**

证据标签约定（全文适用）：

- `[论文]`：论文文字主张；
- `[源码已检查]`：本轮直接读取固定 SHA 的源码行；
- `[实验观察]`：本轮实际命令/程序的输出（原始日志见 `workspace/gate3/`）；
- `[独立计算]`：不依赖参考 C++ join 的独立实现结果；
- `[推断]`：基于观察的解释，尚未单独验证。

本轮遵守：不改 `reference/DiskJoin`；不跑 Gate 2 无必要实验；不进入 Gate 4 消融；不下载 10M/100M；不 sudo/安装；`OMP_NUM_THREADS=4`、单次 `timeout 300`；不覆盖既有结果（Gate 3 使用全新隔离副本与数据目录）。

---

## 1. Executive Summary

在 Gate 2 端到端 smoke 的基础上，本轮建立了**独立于作者 C++ join 的正确性验证体系**，并对论文 §3–§5 与源码逐条对照。

核心结论（均为实际执行证据）：

1. **独立 Oracle 全对**：用纯 stdlib Python 实现的暴力 Oracle（naive O(n²) + 精确窗口加速）在 12k toy 上得到 GT=**3,594,000**，ID 0 的 ε 邻域=**599**（与 Gate 2 的 `gt=599` 一致）[独立计算]。naive 与窗口法在规模上交叉验证一致（前 3000 点 naive GT=223,500 == 12k 窗口 GT 限制到 id<3000 的子集，逐对 `diff` 相同）[独立计算]。
2. **全量 Pairwise Recall = 1.0，Precision = 1.0**：隔离副本中以环境变量开启 pair 输出（不改任何算法决策），12k 输出 **3,594,000** 对，与 GT 完全一致：TP=3,594,000、FP=0、FN=0、重复=0、非法=0；3k 同样完全一致（223,500/223,500）[实验观察 + 独立计算]。
3. **执行不变量成立**：`target_tasks[0]==target_cluster`、任务非空、Gorder 后映射保持、上三角任务、`bucket_sum=n` 在 3k/12k 上全部成立（`head_mismatch=0`、`self_missing=0`、`upper_triangle_ok=1`）[实验观察]。
4. **Cache 正确性独立确认**：包含未修改 `Cache.h` 的确定性 harness 与**独立 DP 最优**在 300 组随机序列（容量 1..n+1）上逐一致；数据完整性（槽位映射、拷贝长度、无残留字节）通过；ASan/UBSan 干净 [独立计算 + 实验观察]。Gate 2 从未触发的淘汰路径在本轮被实际覆盖。
5. **论文–源码发现 1 处已核实 MISMATCH、1 处指标 MISMATCH、若干 Bug/Risk**（见 §7、§11）：
   - `add2choice` 使用 **2-choice 负载均衡**分配桶，而论文明确写“assigns each vector to its nearest center” [论文 + 源码已检查]；
   - 代码用 `id%100000` **采样计数/gt** 作为 recall 输出，而论文 recall 定义为**全量** `|R∩R'|/|R|` [论文 + 源码已检查]；
   - `aligned_alloc` 配 `delete[]`（UB，ASan 已复现）、O_DIRECT `read/lseek` 返回值未检查、空任务 `exit(0)` 等 [源码已检查 + 实验观察]。
6. **近似行为可控**：正常参数下 recall=1；仅在极端（非法）参数 `error_bound=100` 强制剪枝时出现 FN（precision 仍=1.0，FP=0），说明该近似只会漏、不会错 [实验观察]。

**边界**：`PASS_WITHIN_TESTED_SCOPE` 仅覆盖“120/3000–12000 点、20 类、类间强分离、ε=0.25”的合成数据；本轮所有 candidate 比较都命中真对（`dist_comp == GT`），是**偏容易的范围**。这不等于论文级正确性/性能，也不覆盖正式版差异。

---

## 2. 研究资料与版本

| 项 | 值 | 证据 |
|---|---|---|
| 参考仓库 | `iidyc/DiskJoin` @ `aa86151f97527b1dcf9a032d523c1d67d892454a` | [实验观察] |
| `git rev-parse HEAD` | `aa86151f97527b1dcf9a032d523c1d67d892454a` | [实验观察] |
| `git status --short` | 空（本轮结束复核仍为空） | [实验观察] |
| 论文（可用） | arXiv `2508.18494v2`，15 页；文本 `workspace/paper_text/DiskJoin_arXiv_2508.18494v2.txt` | [实验观察] |
| 论文（缺失） | PACMMOD 正式版 PDF（27 页，DOI `10.1145/3769780`） | [实验观察] |
| 版本对齐 | arXiv v2 与正式版是否逐条一致 → `UNVERIFIED`（不声称已读正式版） | — |

本轮完整阅读：`AGENTS.md`、`AGENT_START_HERE.md`、`README.md`、`docs/{CORE_IDEA,IMPLEMENTATION_AUDIT,EXPERIMENT_PROTOCOL}.md`、`scripts/make_toy.py`、`workspace/{GATE2_REPORT,HANDOFF,REPORT}.md`、`workspace/patches/gate2_instr.patch`、`workspace/runs/*` 原始日志。

源码逐行审计：`lib/DiskJoin.h`（全 158 行）、`lib/Kmeans.h`、`lib/ClusterIO.h`、`lib/Cache.h`、`lib/Gorder.h`、`lib/Unitheap.h`、`utils/{heap,utils,dist_func,dist_header}.h`、`lib/hnswlib/{hnswlib,hnswalg,space_l2}.h`、`expr/main.cpp`。

论文对照位置：Def.1 SSJ 与 recall 定义（文本 78–102 行）、§3 overview（240–285）、§4.2 Algorithm 1（400–431）、§4.3 Algorithm 2（483–527）、§5.1/§5.2 + Algorithm 3（528–620）。

---

## 3. Gate 2 证据复核

复核对象为 `workspace/runs/` 下的原始日志，未重跑 Gate 2（无必要）。

`workspace/runs/gate2-instr-run1/stdout.log`（原文）：

```
[instr] bucketization: cluster_num=120 nonempty_buckets=120 max_bucket_size=309 total_vectors=12000
[0.0580773 s] Build done
[instr] bucket_graph: cluster_num=120 task_num=459 max_task_num=10 empty_tasks=0
[instr] gorder: permutation_ok=1 cluster_num=120 order_first8=6,10,29,42,46,54,76,84
[instr] cache: init capacity_slots=5429 bucket_length_floats=4944 mem_bytes=107363904 budget_bytes=107374184
[instr] cache: accesses=459 hits=339 misses=120 filled_slots=120 capacity_slots=5429
[instr] io: reads=120 buckets_processed=120 candidate_pairs=459
[instr] io_bytes: aligned=1.25338e+06 effective=768000
[instr] compute: dist_comp=3.594e+06 sampled_matches=599
recall = 1
[0.0875891 s] Join done
```

复核判定：

- 这些数字确实来自实际程序输出，文件位于 `workspace/runs/gate2-instr-run1/`，`time.log` 记录 `Exit status: 0`、`Maximum resident set size: 9508 KB` [实验观察]。
- `sampled_matches=599`、`gt=599`、`recall=1` 与 `toy_metadata.json` 的 `sample_ids=[0]` 一致 [实验观察]。
- **修正一处 Gate 2 报告的历史表述**：Gate 2 曾把“代码未显式执行论文 Eq.(1) 三角不等式”记为不一致。经本轮源码核对，**这属正确行为**：论文 §5.2 明确说用 Eq.(1) 会产生过多候选，因此改用 HNSW + Algorithm 3 概率剪枝；代码正是 HNSW 候选 + Algorithm 3 剪枝。Eq.(1) 只是论文叙述的“朴素基线”，非目标算法。Gate 3 据此更正，不作为 mismatch（见 §6.B）。

---

## 4. Gate 3A — 执行不变量与数据流审计

### A. Bucket Task 不变量

运行期断言（`GATE3_INVARIANTS=1`，只读，不改变行为），在 12k/3k 上输出：

```
[gate3-inv] perm_ok=1 empty_tasks=0 head_mismatch=0 self_missing=0 upper_triangle_ok=1 task_total=459 bucket_sum=12000 n=12000   (12k)
[gate3-inv] perm_ok=1 empty_tasks=0 head_mismatch=0 self_missing=0 upper_triangle_ok=1 task_total=470 bucket_sum=3000  n=3000    (3k)
```

| 检查 | 结果 | 证据 |
|---|---|---|
| 每个目标 Bucket 任务列表非空 | 成立（`empty_tasks=0`） | [实验观察] |
| `target_tasks[0]==target_cluster` | 全部成立（`head_mismatch=0`，且 self 必在列表内 `self_missing=0`） | [实验观察] |
| Gorder 重排后该性质保持 | 成立（上述检查在 `reordered_tasks`/`order` 上执行） | [实验观察] |
| `order` 为有效置换 | 成立（`perm_ok=1`） | [实验观察] |
| 任务仅含上三角（`nc>=order[i]`） | 成立（`upper_triangle_ok=1`） | [实验观察] |
| 实际输入是否可能违反 | 本轮 toy 未违反；见下述分析 | [源码已检查 + 推断] |

映射方向核对（`lib/DiskJoin.h:87-103`）[源码已检查]：

- `Gorder::order_gorder` 返回 `rank`，满足 `rank[order[i]]=i`（`lib/Gorder.h:97-102`）。
- `DiskJoin` 用 `reordered_tasks[perm[i]]=shuffled_tasks[i]`、`order[perm[i]]=i`，因此位置 `q` 处理的原 bucket 为 `order[q]`，其任务列表为 `tasks[order[q]]`。运行期 `head_mismatch=0` 实证该链一致。
- 由于 `tasks[i]` 在构造时先对候选取上三角（`if (i <= neighbor)`，`lib/DiskJoin.h:64-68`）并按升序排序，且 self 必在候选内（HNSW 以自身 center 为起点、距离 0，`knnSearchBaseLayer` 永不淘汰最小者），故 `tasks[i][0]==i` 恒成立（`self_missing=0`）。

**违反不变量的后果**（为何该不变量关键）[源码已检查 + 推断]：self-join 用 slot 0 的数据（`data + j*d`）配 `assignment[target_cluster]` 的 id；cross-join 用 slot k 配 `assignment[target_tasks[k]]`。若 `target_tasks[0]!=target_cluster`，则 slot 0 与 id 归属错配 → 距离对象错误 → 产生错误 Pair。本轮实测该错配未发生。

### B. Bucket 数据对应关系（独立解析）

用独立 Python 解析 metadata/cluster/fbin（`workspace/gate3/oracle/audit_metadata.py`），结果 `runs/metadata_audit_12k.json`：

| 检查 | 结果 |
|---|---|
| header `n/d/cluster_num/max_points` | 12000 / 16 / 120 / 309，与 fbin 一致 |
| `sum(bucket_sizes)==n` | 成立（12000） |
| assignment 为 `0..n-1` 的置换 | 成立（dup=0, oob=0, missing=0） |
| cluster 文件布局（offset=`cumu*d*4`，逐桶连续） | 逐向量 bit 级一致，`vector_mismatch=0`（12000 全查） |
| `radii[b]==sqrt(max‖x−centroid_b‖²)` | 成立，`radius_mismatch=0` |
| centroid 为数据向量 | 成立，`centroid_not_a_data_vector=0` |
| centroid 属于自身桶 | **不成立：120/120 均不在自身桶**（见 §6.A / G3-01） |

**Self-Join 无重复无序对**：self-join 内层 `if (id2>=id1) continue;`（`lib/DiskJoin.h:130`）保证每对无序向量只比一次 [源码已检查]。**Cross-Bucket**：任务取上三角，unordered bucket pair `{t,n}` 只在 target=t 时处理一次；桶间 id 互斥，故同一向量对不会被跨桶重复 [源码已检查 + 实验观察：`found_duplicates=0`]。**距离口径**：`epsilon=sqrt(config.radius)`，比较 `dist < epsilon*epsilon`，其中 `dist_l2=utils::L2Sqr` 为**平方** L2（`lib/ClusterIO.h:15`，`utils/dist_func.h` AVX 路径）→ 有效阈值 = `config.radius`（toy=0.0625=ε²）[源码已检查]。

### C. Cache 数据完整性

见 §5.D / §7。结论：`Cache::init/find/push` 的地址表↔槽位映射、拷贝长度、未来访问 `iters/ptr`、Belady 淘汰条件均被独立 harness 确认正确（`PASS`），且 Gate 2 未触发的淘汰分支在本轮被覆盖。

---

## 5. Gate 3B — 独立 Oracle 与 Pairwise Recall

### A. 独立 Oracle（不依赖参考 C++ join）

源码：`workspace/gate3/oracle/oracle_pairs.py`（纯 stdlib，无 NumPy/无安装）。

- `gt_naive`：穷举 O(n²)，`GT={(i,j)|j<i, squared_L2(x_i,x_j) < radius}`；严格排除 `(i,i)`、按无序去重、用**严格 `<`**、`radius` 作为**平方 L2** 阈值。
- `gt_windowed`：按坐标 0 排序 + 必要条 `|x_i[0]-x_j[0]|<sqrt(radius)` 滑窗，**结果集与 naive 完全相同**，仅加速。
- `selftest`：手工构造（相同向量、距离恰等于阈值、恰小于阈值、重复向量）+ 4 组随机 200 点 naive↔windowed↔id0 交叉验证，全部 `PASS`（`logs/oracle_selftest.log`）[独立计算]。

边界规则确认：`==radius` 判为**不相似**（严格 `<`）；重复向量按无序对计一次。注意论文 Def.1 用 `≤ ε`（`[论文]` 78–81 行），代码用平方距离严格 `< ε²`——仅在“恰好落在阈值上”的边界不同（toy 无此情形），列为 G3-06。

### B. 获取真实 Pair 输出（隔离插桩）

- 全新隔离副本：`workspace/gate3/instrumented/DiskJoin`（由 `git archive HEAD` 展开，非 Gate 2 副本）；补丁 `workspace/gate3/patches/gate3_instr.patch`（**仅改 `lib/DiskJoin.h`**）。
- 插桩：环境变量 `GATE3_PAIR_OUT` 开启，**每线程独立 buffer**（`omp_get_thread_num()`），并行区后串行落盘，规避 OpenMP 竞争；仅复用既有命中条件 `dist<ε²`，**不触碰**候选生成/Gorder/Cache/剪枝/距离逻辑；`GATE3_INVARIANTS` 另开只读断言。行为影响仅为命中分支追加 push（不影响任何数值）。
- 构建（out-of-tree）：`workspace/gate3/build`（cmake+g++，`-O3`，`-mavx2 -mfma -march=native`）。
- 数据：`workspace/gate3/data/`（12k 与 3k 前缀；**不覆盖** Gate 2 的 `workspace/toy/`）。

### C. 正确性指标（found vs GT）

12k（`runs/compare_12k.txt`）：

```json
{"gt_pairs": 3594000, "found_pairs": 3594000, "found_duplicates": 0,
 "found_illegal_lines": 0, "TP": 3594000, "FP": 0, "FN": 0,
 "recall": 1.0, "precision": 1.0}
```

3k（`runs/compare_3k.txt`）：`gt=found=TP=223500`，FP=FN=0，recall=precision=1.0，重复=0，非法=0。

补充：`dist_comp`（候选比较次数）12k=**3,594,000**、3k=**223,500**，均**等于 GT**——即本轮所有候选比较都命中真对，无浪费比较、无漏。这说明该 toy 的候选生成在此配置下恰好精确覆盖所有相似对。

**最小失败案例**：正常参数下无 FP/FN 样例可给（没有失败）。为刻画近似边界，另做一次诊断（**非 Gate 4 消融**）`error_bound=100`（对应非法 λ<−9）：任务数降为 120（仅 self-join），输出 797,349 对，FN=**2,796,651**、FP=**0**、precision=1.0、recall=0.2219（`runs/compare_12k_eb100.txt`），采样样例见下。结论：剪枝是**只漏不错**的可控近似 [实验观察 + 独立计算]。

```
sample FN (in GT, not in output):
  (0,20) sq_l2=0.01308749 < radius=0.06250000
  (0,40) sq_l2=0.01945522 < radius=0.06250000
  ...
```

另做 `error_bound=0.9` 诊断：结果与 0.1 **完全相同**（459 任务、3,594,000 对）。原因：`arcos` 对 `x>1` 截断为 0，远端候选角度≈0，故 `0.1` 与 `0.9` 在**同一 ptr** 触发 break [实验观察 + 源码已检查]（见 G3-10）。

### D. 独立审查原有采样 Recall

- **ID 0 精确 ε 邻域 = 599**（`runs/oracle_id0.json`，独立暴力枚举），与 Gate 2 `gt=599` 一致 [独立计算]。ID 0 属“类 0”，类 0 共 600 个点（ID 0,20,…,11980），故邻域=599。
- 全量 GT = 20 × C(600,2) = 3,594,000（类间强分离，无跨类相似对）。
- `%100000` 计数逻辑（`lib/DiskJoin.h:135-136,149-150`）：

  | 情形 | 行为 |
  |---|---|
  | `n<100000` | 只有 ID 0 命中采样 → count=与 0 相似的对数；toy=599 |
  | `n≥100000` | ID 0、100000、200000… 均为采样；**当一对两端点都 ≡0 mod 100000 时，同一对被 `if(id1)count++` 与 `if(id2)count++` 各计一次 → 双计** |
  | 论文口径 | `r=|R∩R'|/|R|`，R 为**全部**距离<ε 的对（`[论文]` 99–102 行）|

  **明确结论**：打印的 `recall=count/config.gt` 是**采样口径的估计**，不是全量 Pairwise Recall；在 `n≥100000` 时既有双计、又与 `make_toy` 的“仅 ID 0”GT 口径不一致 → 不能用作论文 recall。**采样 Recall 与全量 Pairwise Recall 已严格分开报告**（本节 D 为采样，C 为全量）。

### E. 可复现性

同二进制、同输入连续两次运行，pair 集合**逐对一致**（`DETERMINISTIC_PAIRSET_OK`，`runs/pairs_12k.txt` vs `runs/pairs_12k_run2.txt`）[实验观察]。注意 HNSW center 构建为 `#pragma omp parallel for`，跨机器/线程数的绝对可复现性未穷尽验证（见 G3-14）。

---

## 6. Gate 3C — 论文–源码一致性审计

### A. Bucketization（§5.1）

| 论文描述 | 源码 | 判定 |
|---|---|---|
| 随机采样向量作中心（§5.1） | `srand(283)`+`random_shuffle`+取前 cluster_num（`lib/Kmeans.h:172-191`） | 结构一致（固定种子） |
| 每个向量分配到**最近中心**（277/512/606 行） | `add2choice`：取最近两个中心，若最近桶更空且 `dist0<1.2·dist1` 则入最近，否则入次近（`lib/Kmeans.h:127-146`） | **MISMATCH（G3-01）** |
| 桶记录半径=成员到中心最大距离（277–278 行） | `radii=max sqrt(sq_l2)`（`lib/ClusterIO.h:76-77,97`） | 一致（G3-13：中心未必是成员） |
| K-means 迭代“不适用”（§5.1） | `Kmeans::train` **从未被调用**；`one_level_kmeans` 只用采样中心 + HNSW 分配 | 一致（`train/add/assign` 为死代码，G3-12） |
| 2‰ 内存 HNSW + 顺序 I/O 写桶 | HNSW on centers；`ClusterWriter` 顺序写（`ClusterIO.h:43-99`） | 一致 |

### B. Bucket Graph / Pruning（§5.2、Algorithm 3）

| 论文 | 源码 | 判定 |
|---|---|---|
| §5.2：Eq.(1) 三角不等式会产生过多候选 | 源码确有 Eq.(1) 风格过滤 `prune(d,r1,r2,ε): d≥r1+r2+ε ‖ d/2≥r1+ε`，但只在 `rangeSearchBaseLayer` 中，**该方法从未被调用（死代码）** | 一致（澄清：Gate 2“未执行 Eq.(1)”不是缺陷；G3-08） |
| 用 center 作查询检索 HNSW 得最近中心集 B_c | `knnSearchBaseLayer(i,K)`，查询为桶 i 的 center，返回 sqrt 距离（`hnswalg.h:454-518`） | 一致 |
| Algorithm 3：按距离降序累积 `arccos(min{x,1})` 到 `1−λ` 为止，剪掉远端 | `lib/DiskJoin.h:56-76`：升序排序后从最远端回退累加，`sum>=error_bound` 时 break，保留近端前缀 | **结构一致**；但 x 的取法 `((dist)/2)/ε`、`x>1→1`、`x<0` 未处理、501 项查表 → 实现细节可能与论文公式不同（G3-10，Potential） |
| K 控制候选完整性 | 候选只取 top-K 中心；真邻居桶不在 top-K 则漏 | 一致（K 太小会漏；POTENTIAL recall 限制） |

### C. Gorder（§4.3、Algorithm 2）

| 论文 | 源码 | 判定 |
|---|---|---|
| 选最大出度节点开始（line 1） | `UnitHeap` key=出度，`ReConstruct` 降序，取 `top`（`Gorder.h:71-83`） | 一致 |
| 每步选与窗口 w 内重叠最大者（lines 3-6） | `ExtractMax` + `move_window` 的 lazy 增量 | 结构一致 |
| 增量只更新受入/出窗口影响的 k_v；复杂度 O(Σ d⁺(u)²)（514-520 行） | `move_window` 用**兄弟**（共享父的节点）`lazyIncrement`；父节点自身的 `lazyIncrement` 被注释（`Gorder.h:15,44,50,53`） | 与 O(Σd⁺²) 相符 [推断]；注释行是刻意保留的优化 |
| 窗口 w = C/d_avg | 代码 `w = budget/4/length/K*2 = 2C/K` | 系数为 2 的实现差异；且 toy 上 **w≈452 > cluster_num=120**，`order.size()>window` 永不成立 → **窗口移除分支从未触发**，Gorder 退化为“初始度数 + 每步给兄弟 +1”（G3-11） |
| 输出排列方向与执行顺序一致 | `rank[node]=pos`；`order[perm[i]]=i`；运行期映射检查通过 | 一致 |

### D. Belady Cache（§4.2、Algorithm 1）

| 论文 | 源码 | 判定 |
|---|---|---|
| 预记录每个桶的未来访问序列 P[·] | `Cache::init` 展平 `iters[id]` 并追加哨兵 max（`Cache.h:30-42`） | 一致 |
| 命中则更新堆，缺失则加载/淘汰最远下次使用 | `find`/`push`（`Cache.h:44-67`） | 一致 |
| 满时淘汰 next-use 最大者 | `priority.top()`（`std::greater` → top 为最大）；仅当 `top.second > iters[id][ptr[id]]` 才淘汰并载入，否则不驻留（`Cache.h:60-66`） | 一致且**最优**（独立 DP 验证） |
| never-used-again | `iters` 末尾哨兵 `max` | 一致 |
| 访问粒度 | 论文 S 长 `2|E|`（每条边列两端）；代码为任务展平（每任务列一个桶，target 桶作为 self 出现一次），长度=`|tasks|=|V|+|E_无序|`（Gate 2=459） | 粒度建模差异，内部自洽；列 G3-10/§7（Low） |
| 等大小块假设 | 槽位固定 `length=max_points*d`，桶大小不一但拷贝仅 `bucket_length`（`Cache.h:50,57,61`） | 一致；数据完整性已验；槽位按最大桶计，容量保守（G3-10，Low） |

**独立验证**（`workspace/gate3/oracle/cache_test.cpp`，include 未修改的 `Cache.h`）：

```
deterministic: opt=7 belady=7 ref=7 OK
random cases=300 fails=0
data-integrity: copy/padding errors=0 OK
no-eviction: ref_miss=50 expected=50 OK
CACHE_HARNESS PASS (fails=0)
```

- “opt”为独立 **DP 最优**（对缓存集合状态做最短路），在 300 组随机序列×容量上 `ref==opt`；确定性 JR 例中 DP=Belady=ref=7。
- `data-integrity` 验证槽位映射与**精确拷贝长度**（`find` 只写 `bucket_length` 个 float，不越写），淘汰后重载返回正确字节、无残留。
- ASan+UBSan 运行 harness **干净**（构建错误修复后）[实验观察]。

### E. 其他实现风险

| 项 | 源码 | 判定 |
|---|---|---|
| `aligned_alloc` vs `delete[]` | `ClusterIO.h:183` 用 `aligned_alloc`，`:207` 用 `delete[]`；ASan 复现 `alloc-dealloc-mismatch` | **Bug（UB，G3-03）** |
| `read/lseek` 未检查返回值 | `ClusterIO.h:198-199`；短读/失败会留旧数据 → 错距离 | Risk（G3-04） |
| 空任务 `exit(0)` | `DiskJoin.h:70-76`；触发则**静默成功退出** | Risk（G3-05；分析为实际不可达） |
| 缓冲区边界 | `data(max_task_num*length)`，索引上界 `(max_task_num-1)*length+length-d < 容量`；ASan 未报越界 | 安全（G3-06 之外无 OOB） |
| 文件格式/对齐/短读 | fbin/metadata 布局经独立 Python bit 级校验；O_DIRECT 读大小页对齐 | 一致 |
| `dist_l2(vec1, centroid)` 未使用 | `DiskJoin.h:142`（死计算，且不计入 `dist_comp`） | Risk（G3-07，Low） |
| `Cache::init` 的 id 契约 | `iters[id]` 需 `id<tasks.size()`；DiskJoin 中 id=桶 id<cluster_num，恒满足 | Risk（G3-09，API 契约，未触发） |
| `ConfigReader` 固定顺序、无校验 | `ConfigReader.h:22-35` | Risk（G3-15，Low） |

---

## 7. Gate 3D — Bug / Risk / Mismatch 清单

| Issue ID | 类型 | 严重程度 | 证据 | 影响范围 | 最小复现 | 结论 | 建议处理 |
|---|---|---|---|---|---|---|---|
| G3-01 | Mismatch | Medium | 论文 277/512/606“nearest center”；源码 `Kmeans.h:127-146` add2choice；`runs/metadata_audit_12k.json` 显示 120/120 中心不在自身桶 | Recall / Reproducibility（近似模型） | 构建后查 metadata（`audit_metadata.py --metadata data/toy12k.metadata ...`） | Confirmed | 消融前记录；若要贴合论文需 `add`（最近中心）变体并对照 |
| G3-02 | Mismatch | High（评估口径，非 join 正确性） | 论文 99–102 `r=|R∩R'|/|R|`；源码 `DiskJoin.h:135-136,149-150` `%100000` 计数 ÷ `gt` | Recall / Reproducibility | 任意规模运行，观察 `recall=` 为采样值 | Confirmed | 禁用采样输出、改用本报告 Oracle 全量口径评价 |
| G3-03 | Bug (UB) | Low–Medium | `ClusterIO.h:183` aligned_alloc 与 `:207` delete[]；ASan `alloc-dealloc-mismatch` | Correctness（潜在） | ASan 运行 3k（`runs/stderr_3k_asan.log`） | Confirmed | 改 `free(buffer)`（隔离副本），参考仓库不改 |
| G3-04 | Risk | Medium | `ClusterIO.h:198-199` 未检查 `lseek/read` | Correctness（潜在） | 代码审查；O_DIRECT 短读场景 | Potential | 校验返回值与短读 |
| G3-05 | Risk | Low | `DiskJoin.h:70-76` `exit(0)` | Reproducibility（静默失败） | 分析：需 self 非候选且 `dis[0]!=0`（实测 head/self 全 OK → 不可达） | Potential | 以报错替代静默退出 |
| G3-06 | Mismatch（minor） | Low | 论文 `≤ε` vs 代码 `dist<ε²` | Correctness（仅阈值边界） | 构造 sq_l2==radius 的向量对 | Confirmed | 明确并在评估中记录 |
| G3-07 | Risk | Low | `DiskJoin.h:142` 死计算 | Performance | 代码审查 | Confirmed | 删除（不影响结果） |
| G3-08 | Mismatch/Note | Low | `hnswalg.h:384-450` `rangeSearchBaseLayer`/`prune` 无调用者 | Reproducibility | `grep -rn rangeSearchBaseLayer` | Confirmed | 记录：Eq.(1) 过滤未用于主路径 |
| G3-09 | Risk (API) | Low | `Cache.h:34,38` `iters[id]` 需 id<tasks.size() | Correctness（潜在） | harness 初期参数不当即触发越界 | Confirmed | 记录契约；使用方保证 id<桶数 |
| G3-10 | Potential | Low | 剪枝 x=`(dist/2)/ε`、`x>1→1`（`DiskJoin.h:35-45,60`）；窗口 w=2C/K；Cache 访问粒度 | Recall / Performance | `error_bound=0.9` 与 `0.1` 结果相同 | Potential | Gate 4 用真实数据/参数评估剪枝与窗口敏感性 |
| G3-11 | Risk/Limitation | Medium（对 Gate 4） | w=452>120，窗口移除分支未触发 | Reproducibility（消融公平） | 12k 上 `order.size()>window` 恒假 | Confirmed | Gate 4 调大 n 或显式设 w<n 以激活窗口逻辑 |
| G3-12 | Note | Low | `Kmeans.h:25-90` train/add/assign 未被调用 | Reproducibility | `grep -n 'train(' lib` | Confirmed | 记录为死代码（与论文“不做 K-means”一致） |
| G3-13 | Note | Low | 中心非成员（G3-01 后果），半径覆盖非成员中心 | Recall（分析） | metadata 审计 | Confirmed | 记录 |
| G3-14 | Risk | Low | center 构建 `#pragma omp parallel for`（`Kmeans.h:197-200`） | Reproducibility | 本机两次运行 pair 一致；跨机未测 | Potential | Gate 4 固定线程数并记录 |
| G3-15 | Risk | Low | `ConfigReader.h` 固定顺序无校验 | Reproducibility | 提供带注释/乱序 config | Potential | 使用脚本生成 config |

---

## 8. 实验命令与资源

- 隔离副本/构建：`git -C reference/DiskJoin archive HEAD | tar -x -C workspace/gate3/instrumented/DiskJoin`；`cmake -S ... -B workspace/gate3/build`；`cmake --build build -j4`。
- Oracle 自检：`python3 oracle/oracle_pairs.py --selftest`。
- 12k GT：`python3 oracle/oracle_pairs.py --fbin ../toy/toy.fbin --radius 0.0625 --method windowed --out runs/gt_toy_12k.txt`（≈21 s）。
- 3k naive GT：`... --method naive --max-n 3000 ...`（≈8 s）。
- 运行插桩：`GATE3_PAIR_OUT=... GATE3_INVARIANTS=1 OMP_NUM_THREADS=4 timeout 300 ./build/main data/toy12k.config`。
- Pair 比较：`python3 oracle/compare_pairs.py --gt runs/gt_toy_12k.txt --found runs/pairs_12k.txt --n 12000 --radius 0.0625 --fbin data/toy12k.fbin`。
- 元数据审计：`python3 oracle/audit_metadata.py --metadata data/toy12k.metadata --clusters data/toy12k.clusters --fbin data/toy12k.fbin`。
- Cache harness：`g++ -std=c++11 -O2 -I reference/DiskJoin oracle/cache_test.cpp -o build/cache_test && ./build/cache_test`（另有 `-fsanitize=address,undefined` 版本）。
- 内存错误探针：`g++ ... -fsanitize=address,undefined ... expr/main.cpp -o build/main_asan`；`ASAN_OPTIONS=halt_on_error=0:detect_leaks=0`.

资源纪律：全部 `OMP_NUM_THREADS=4`；所有运行 `timeout 300`（实际 0.01–21 s，未触发）；无 GPU、无 sudo、无安装、无外部下载；磁盘仅新增 JSON/日志/小数据前缀（< 4 MB）。原始日志：`workspace/gate3/{runs,logs}/`。

---

## 9. 补丁与工作副本状态

| 对象 | 路径 | 说明 |
|---|---|---|
| 参考仓库 | `reference/DiskJoin` | **未修改**：`git rev-parse HEAD`=`aa8615…454a`，`git status --short` 空（复核） |
| Gate 3 隔离副本 | `workspace/gate3/instrumented/DiskJoin` | 由 pinned SHA `git archive` 展开；`diff -r --exclude=.git reference/DiskJoin ...` 在插桩前为 **IDENTICAL** |
| Gate 3 插桩补丁 | `workspace/gate3/patches/gate3_instr.patch` | 115 行，**仅 `lib/DiskJoin.h`**；新增 `GATE3_PAIR_OUT`（pair 输出，每线程缓冲）与 `GATE3_INVARIANTS`（只读断言/统计） |
| Gate 3 构建 | `workspace/gate3/build/`（`main`、`main_asan`、`cache_test`、`cache_test_asan`） | out-of-tree |
| Gate 3 数据 | `workspace/gate3/data/`（`toy12k.*`、`toy3k.*`、`*_eb09/_eb100.config`） | 不覆盖 `workspace/toy/` |
| Gate 2 补丁 | `workspace/patches/gate2_instr.patch` | 保留未动 |
| git 操作 | — | 全程无 `reset/clean/commit/push/checkout` |

---

## 10. 尚未验证的内容

1. **PACMMOD 正式版一致性**：正式 PDF 缺失，arXiv v2 ↔ 正式版逐条差异 `UNVERIFIED`。
2. **范围外正确性**：仅在 3k/12k、20 类强分离、ε=0.25、K=24、error_bound=0.1 上验证；未验证高维真实数据、类重叠、ε 密集（每向量~100 邻居）、超大 n。
3. **剪枝在实际目标 recall 下的漏检**：正常参数 recall=1；只有极端非法参数才出 FN。真实 λ=0.9 场景下 pruning 的 FN 分布未测。
4. **Gorder 窗口逻辑**：toy 上窗口从不滑动，`move_window` 的窗口移除分支与注释行未被执行；其正确性/收益未验证。
5. **Gorder vs 原始顺序的收益**：属 Gate 4 消融，本轮未做。
6. **跨机/跨线程绝对可复现**：center 并行构建的确定性只在本机两次运行验证。
7. **O_DIRECT 短读/错误路径**：未人为制造 I/O 错误。
8. **`Cache` 的 LRUCache/`simulate_cache` 辅助实现**：非主路径，未逐一验证（主路径 `Cache` 已验证）。
9. **`rangeSearchBaseLayer`（Eq.(1) 过滤）**：死代码，未运行。

---

## 11. Gate 3 最终判定

> A 与 B 独立，audit PASS ≠ correctness PASS。

**A. Audit Completion = `PASS`**
全部必需审计任务完成且证据充分：交接与版本复核、Gate 2 证据复核、Gate 3A 不变量 + 独立元数据/数据流审计、Gate 3B 独立 Oracle + 全量 Pairwise Recall + 采样口径分析、Gate 3C 逐项论文—源码对照、Gate 3D 问题清单。原始日志、补丁、测试配置、Oracle 源码、TP/FP/FN 统计、失败案例、mismatch 清单均已落盘于 `workspace/gate3/`。

**B. Algorithm Correctness = `PASS_WITHIN_TESTED_SCOPE`**
在被测范围内（12k 与 3k 合成数据，正常参数）：DiskJoin 输出与独立 Oracle **逐对一致**（recall=precision=1.0，FP=FN=重复=非法=0）；`target_tasks[0]==target_cluster` 等执行不变量成立；Cache 替换最优性与数据完整性经独立实现确认。同时已确认近似剪枝“只漏不错”，并在极端参数下展示可解释的 FN。
**范围限定**：该结论不代表论文级正确性/性能，也不覆盖正式版差异；toy 的候选比较全部命中真对，是偏容易的范围。

---

## 12. Gate 4 前置条件与建议（只提方案，不执行）

前置条件（现状）：

| 条件 | 状态 |
|---|---|
| 独立 Oracle 可用 | ✅ `oracle_pairs.py`（已交叉验证） |
| Pair 输出工具可用 | ✅ `GATE3_PAIR_OUT` 插桩（补丁保留） |
| 缓存正确性已验证 | ✅ DP 最优 + ASan |
| Gorder 执行语义明确 | ✅ 映射/方向已确认；⚠ 窗口逻辑在 toy 上未激活（G3-11） |
| Pruning 的 Recall 影响可独立评估 | ✅ pair dump + Oracle 可算 FN/Recall |
| 会影响消融公平性的改动已记录 | ✅ 仅 `lib/DiskJoin.h`；G3-01/02/03 需在消融基线中固定处理 |

建议的 Gate 4 小步计划（预估成本，均为受控小规模）：

1. **固定评测口径**：所有消融统一用本报告的全量 GT/found 对比（弃用 `%100000` 采样；G3-02）。
2. **激活 Gorder 窗口**：将 n 增至使 `2C/K < n`（或显式设 w），使窗口移除分支真正执行；用固定线程数与重复次数评估顺序收益（H1）。
3. **Belady vs LRU**：在固定 access sequence 上比较 miss（H2）；注意等大小槽模型与访问粒度（§6.D/G3-10）。
4. **Pruning 开关**：`error_bound` 扫描（合法 λ 范围）下测 Recall 与 `dist_comp`/I/O（H3），并用 pair dump 给 FN 样例。
5. **公平性**：每个变体单独 patch 并记录；同一数据/ε/K/线程数/内存预算；多次重复取稳定方向。
6. **风险处理**：消融前先决定是否在隔离副本修 G3-03（改 `free`）以消除 UB 噪声；参考仓库保持只读。

---

## 附：产物清单

- Oracle/测试源码：`workspace/gate3/oracle/{oracle_pairs.py, compare_pairs.py, audit_metadata.py, cache_test.cpp}`
- 插桩补丁：`workspace/gate3/patches/gate3_instr.patch`
- 测试配置：`workspace/gate3/data/{toy12k.config, toy3k.config, toy12k_eb09.config, toy12k_eb100.config}`
- TP/FP/FN 统计：`workspace/gate3/runs/{compare_12k.txt, compare_3k.txt, compare_12k_eb100.txt, metadata_audit_12k.json, oracle_id0.json, oracle_gt_12k_summary.json, oracle_gt_3000_naive.json}`
- Pair 输出：`workspace/gate3/runs/pairs_*.txt`
- 原始日志：`workspace/gate3/runs/std{out,err}_*.log`、`workspace/gate3/logs/*.log`
- GT：`workspace/gate3/runs/{gt_toy_12k.txt, gt_toy_3000_naive.txt, gt_toy_12k_prefix3000.txt}`
