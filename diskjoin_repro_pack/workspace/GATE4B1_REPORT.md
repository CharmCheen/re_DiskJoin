# DiskJoin Gate 4B-1 Report — 受控机制消融（Task Reordering × Cache Policy × Pruning)

日期：2026-11-02
验证级别：`mechanism_ablation`（合成小数据、单机、受控变量；**非**论文级性能复现）
结论：**PASS**（成功条件 1–7 全部满足；见 §14）

---

## 1. Executive Summary

在 Gate 0–4B-0 冻结资产（P1/P3/W1H/W2H 合成数据、bucketization、GT）之上，以 62 槽容量、window=4、OMP=1 固定条件，完成 36 组主矩阵（2 数据集 × 3 任务序 × 3 缓存策略 × 2 error_bound）、12 组额外随机种子复核、8 组 W1H/W2H holdout 复核、36 组计时运行，全部 rc=0。

**核心量化结论**（P1/P3 gorder eb0.1，miss 计数）：

| | BELADY_REJECT | BELADY_FORCED | LRU_FORCED |
|---|---|---|---|
| P1 | **172** | 174 | 301 |
| P3 | **164** | 165 | 273 |

1. **任务序（H1）**：P1 上 Gorder(172) < Identity(195) < Random(246)；**P3 上 Identity(134) < Gorder(164) < Random(204)** —— Gorder 并非总优，P3 现象在 W2H holdout 复现（149 vs 171）。机理用 LRU 栈距离完整核算（§6、§11）。
2. **替换策略（H2）**：同一强制装入动作集下，Belady 未来信息 vs LRU：P1 174 vs 301（LRU 多 72.9% miss）、P3 165 vs 273（+65.5%）。**拒绝装入的边际贡献很小但恒非负**（24 组配置中 0–4 次 miss，全部 ≤2%）。
3. **剪枝（H3）**：eb0.1→1.0：任务数 −3.3%/−5.4%，dist_comp −3.3%/−3.7%，I/O 基本不变，Recall −0.80pp/−1.15pp；每损失 1 个 TP 节省 25.4（P1）/153.7（P3）次距离计算。
4. **正确性**：全量 Oracle 下 65 组运行 FP=0、重复对=0、Precision=1.0；同 (ds,eb) 下 Pair 集合在 9 个 order×policy 组合间逐对恒等；任务图（target,candidates）跨序恒等；dist_comp 跨 order×policy 严格不变。
5. **工程发现**：修复 ClusterWriter 两处泄漏（LSan 回归通过）；发现并修复**上游潜伏堆 bug**（`updateable_heap::sift_down` 在满堆 guard 节点读越界——原 Belady 语义不可达，由新增 lru_forced 暴露；修复行为等价，默认路径字节级不变）。

一切设备层物理 I/O 标记 **UNVERIFIED**；所有时间测量为亚秒级，仅记录、不作任何 SSD/性能加速结论。

---

## 2. 冻结资产与实验环境

- 参考源码：`reference/DiskJoin` @ `aa86151f97527b1dcf9a032d523c1d67d892454a`（全程 clean、零改动；结束时复核）。
- Gate 4A 冻结资产 md5 全量核验通过（8/8：p1/p3 的 fbin/clusters/metadata/hnsw，`md5sum -c gate4b0/data/gate4a_frozen_md5.txt`）。W1H/W2H 冻结 fbin/GT/pairs 只读共享。
- 隔离副本：`workspace/gate4b1/instrumented/DiskJoin`（自 gate4b0 HEAD `7e4df0c` 复制；本地提交 e0d11c1→f1ac471→17fa981→`51a90f7`，不推送）。补丁：`patches/gate4b1_mechanism_and_leakfix.patch`（229 行）+ `patches/gate4b1_heap_siftdown_guardfix.patch`（70 行）。
- 硬件/软件：单机 Linux、OMP_NUM_THREADS=1 全程、串行运行、每次 `timeout 600s`；无 sudo/安装/下载。
- 固定实验参数：n=4000, d=16, cluster_num=120, K=24, radius=0.2（各数据集原值）、**Cache 容量=62 槽（`GATE4B1_CAPACITY=62` 显式钉住）**、**Gorder window=4（`GATE4B0_WINDOW=4` 钉住）**、冻结 bucketization（每次运行重建 clusters/metadata/hnsw 并 `cmp` vs gate4a，全部字节一致）。
- 配置与产物：`gate4b1/data/*.config`（8 个：p1/p3 × eb0.1/eb1.0 + w1h/w2h × eb0.1/eb1.0，data_file 指向共享只读 fbin）、`gate4b1/runs/`（74 个 correctness 目录 + 36 个 timing 目录）、`gate4b1/logs/`（265 个日志，含全部失败证据）。

---

## 3. Cache Capacity / Policy 实现

### 3.1 实现（commit e0d11c1）

- `GATE4B1_CAPACITY`（lib/Cache.h 构造函数）：仅覆盖槽位数 `size`；不改 budget、length、ClusterWriter 缓冲、任务图、Gorder window。unset 时预算推导，**默认行为不变**（p1/p3 default 运行 trace/tasks/knn/pairs 与 gate4b0 冻结件逐字节一致）。
- `GATE4B1_POLICY` ∈ {`belady_reject`(默认), `belady_forced`, `lru_forced`}：
  - 三者共享**同一访问序列**（find 顺序由任务图决定，与策略无关——tasks.txt 跨策略字节一致）、同容量、同初始状态、同 miss 定义；
  - `belady_reject`：原 C++ 语义逐字保留（冷装/严格更远才逐出/否则拒绝）；
  - `belady_forced`：强制装入，victim=最远下次使用；
  - `lru_forced`：强制装入，victim=最久未用（recency 键 `SIZE_MAX-total` 复用同一 max-heap，编码与原 `LRUCache` 相同）；
  - 计数器口径不变：`admit` 只计冷装入（62=容量），驱逐换入计一次 `evict`；LRU 恒 `reject=0`。
- I/O 计量（ClusterIO.h/DiskJoin.h）：`posixDirectReadCluster` 增 `reads` 计数；`[gate4b1-io] read_calls / effective_bytes / requested_aligned_bytes`。**离线复算公式与实现精确一致**（`file_pos` 为紧邻打包；`requested = align4096(file_pos%4096 + size)`；65 组运行复算值与打印值全部相等）。

### 3.2 单元测试（commit 17fa981）

`oracle/policy_test.cpp`：14 个手工推导用例（T1–T5 × 3 策略），normal 与 **ASan** 双编译均 PASS（14/14）。ASan 版同时充当 heap 修复回归（见 §4.2）。

### 3.3 容量独立性验证

| 运行 | 容量 | 结果 |
|---|---|---|
| p1_default / p3_default（无 env） | 62 | 与 gate4b0 冻结件 trace/tasks/knn/pairs 逐字节一致 |
| p1_cap62pin | 62（显式） | 与 p1_default **trace 也逐字节一致**（钉住=默认） |
| p1_cap40 / p3_cap40 | 40 | tasks/pairs/knn 逐字节不变，**仅缓存统计变化**（P1 172→268 miss，P3 164→243） |

容量覆盖不改 Writer 缓冲（cap40 下仍 `writer_buffer_bytes=2304`、`task_num_total=1484`）、不改任务图、不改 Pair 集合。注：`[gate4a-config] capacity_slots` 是 gate4a 旧探针的**预算推导预测值**（先于 Cache 构造打印）；实际生效槽位以 `[gate4a-cache] capacity_slots` 为准（cap40 运行显示 40）。

---

## 4. Sanitizer 回归

### 4.1 ClusterWriter 泄漏修复（commit f1ac471）

- Gate 4B-0 发现的两处直接泄漏（430,080+256 B）在隔离副本最小修复（`delete[] data_buf; delete[] buffer;` 于 `writeClusters` 末尾）。
- 修复前 LSan 证据保留：`logs/prefix_leak_evidence_p3_default_asan.stderr`。
- 修复后 ASan（LSan 开启）运行 `p3_default_asan`/`p1_default_asan` rc=0 零泄漏；输出（pairs/tasks/trace）与 normal 构建逐字节一致。

### 4.2 上游潜伏堆越界（本轮新发现，commit 51a90f7）

- **现象**：`p3_lru_asan`（lru_forced, cap=62）join 阶段 ASan abort：`heap-buffer-overflow READ of size 8`，`Cache::Cache` 分配的 63×16B `storage` 区域之后一格（storage[63]）。
- **根因**（`utils/heap.h::sift_down`）：guard 节点（有左儿子、无右儿子，`right_son_pos(crawler)==current_bound`）在**两个读点**都先读 `right_son(crawler)`（= `storage[current_bound]`）后做边界判断——满堆（current_bound==max_size）时读越界；未满时读 stale 槽。
- **可达性**：原 Belady 语义不可达——hit 只**增** next-use 键（update 只走 sift_up），pop() 的 sift_down 在 `--current_bound` 之后（容量 62 为偶数，sift 期间不存在 guard 节点）。lru_forced 的 hit **递减** recency 键 → update 调 sift_down 且满堆 → 唯一触发路径（与默认运行字节级不变的事实验证一致）。
- **修复**：guard 前置（两处条件重排，`||`/`&&` 短路）；对一切有定义执行**行为等价**（真值表不变），仅将原本 UB/stale 的分支变为正确定义。
- **证据链**：真实运行崩溃 `logs/prefix_crash_p3_lru_asan.stderr` + 单元测试独立复现 `logs/prefix_policy_test_asan.stderr`（T3/T5 lru 用例，ASan 版修复前 abort、修复后 14/14 PASS）+ 修复后 ASan 四连（default×2 / lru / forced+cap40）rc=0 零错误。
- 默认惰性三向复核：post-fix default == gate4b0 冻结 == pre-fix 档案（trace/tasks/knn/pairs 全部逐字节）。

---

## 5. 实验矩阵与完整原始结果

矩阵：`oracle/run_matrix_gate4b1.sh`（预注册，36 组，命名 `${ds}_${order}_${policy}_eb${01|10}`）。全部 rc=0。完整 TSV：`results/gate4b1_summary.tsv`（65 组运行 × 40 列）；本文数字均出自该表（分析脚本 `oracle/analyze_gate4b1.py`，零一致性问题，见 §9）。

**Miss（admit/evict/reject）与 I/O 字节 [eff/req]**：

| 数据集/序 | BELADY_REJECT | BELADY_FORCED | LRU_FORCED |
|---|---|---|---|
| **P1 eb0.1** gorder | **172** (62/92/18) [351,744/1,040,384 B] | 174 (62/112/0) [355,456/1,052,672] | 301 (62/239/0) [634,240/1,847,296] |
| P1 identity | 195 (62/111/22) [397,568/1,191,936] | 196 (62/134/0) [398,976/1,200,128] | 362 (62/300/0) [748,928/2,207,744] |
| P1 random | 246 (62/111/73) [495,424/1,486,848] | 249 (62/187/0) [508,288/1,523,712] | 508 (62/446/0) [1,071,296/3,129,344] |
| **P3 eb0.1** gorder | **164** (62/67/35) [330,368/974,848] | 165 (62/103/0) [329,280/974,848] | 273 (62/211/0) [571,008/1,613,824] |
| P3 identity | **134** (62/54/18) [274,688/806,912] | 134 (62/72/0) [273,472/806,912] | 222 (62/160/0) [457,792/1,318,912] |
| P3 random | 204 (62/83/59) [406,848/1,216,512] | 208 (62/146/0) [412,096/1,236,992] | 395 (62/333/0) [813,184/2,338,816] |
| **P1 eb1.0** gorder | 172 (62/91/19) | 173 (62/111/0) | 281 (62/219/0) |
| P1 identity | 186 (62/98/26) | 187 (62/125/0) | 351 (62/289/0) |
| P1 random | 237 (62/109/66) | 240 (62/178/0) | 491 (62/429/0) |
| **P3 eb1.0** gorder | 161 (62/70/29) | 161 (62/99/0) | 250 (62/188/0) |
| P3 identity | 133 (62/54/17) | 133 (62/71/0) | 219 (62/157/0) |
| P3 random | 195 (62/81/52) | 197 (62/135/0) | 377 (62/315/0) |

同 (ds,eb) 下：任务图（target,候选集）跨序**多重集恒等**；tasks.txt 跨策略**字节恒等**；dist_comp 跨 order×policy **严格不变**（P1 eb01：1,833,576；P3 eb01：3,274,616；eb10：1,773,186 / 3,153,834）——顺序与策略的影响被完全隔离在缓存/IO 层。

**eb0.1 全部 6 个 gorder/identity/random×策略 miss 与 4B-0 Python 离线模型精确一致**（172/174/301、164/165/273、195、246、134、204）；逐事件 lockstep 核对：LRU victim **精确匹配**（12/12 运行零失配），forced victim 零硬失配（9–38 次 never-again 平局等价，属可互换选择），reject 策略完全复现 C++ 规则。

---

## 6. Task Ordering Ablation（H1）

**结果**（belady_reject，容量 62）：

| 数据集 | Identity | Gorder | Random(seed20260101) | 排序 |
|---|---|---|---|---|
| P1 eb0.1 | 195 | **172** (−11.8%) | 246 (+26.3%) | Gorder 最优 |
| P3 eb0.1 | **134** | 164 (+22.4%) | 204 (+52.2%) | **Identity 最优** |
| P1 eb1.0 | 186 | **172** | 237 | Gorder 最优 |
| P3 eb1.0 | **133** | 161 | 195 | **Identity 最优** |

随机序敏感性（belady_reject eb0.1，3 个未用于调参的种子）：P1 246/239/242（极差 7）；P3 204/205/199（极差 6）。单种子可代表随机序期望 ±~2%，**顺序结论对种子稳健**（random 恒最差，identity/gorder 关系不变）。

**机理**（LRU 栈距离核算，`results/gate4b1_locality.tsv`）：

| ds/序 | sd 均值 | sd<62 占比 | 预测 LRU miss(=120 冷 + sd≥62 复访) | 实测 LRU |
|---|---|---|---|---|
| P1 gorder | 31.3 | 0.797 | 120+181=301 | 301 ✓ |
| P1 identity | 37.8 | 0.756 | 120+242=362 | 362 ✓ |
| P1 random | 45.9 | 0.658 | 120+388=508 | 508 ✓ |
| P3 gorder | 27.3 | 0.838 | 120+153=273 | 273 ✓ |
| P3 identity | 26.4 | 0.868 | 120+102=222 | 222 ✓ |
| P3 random | 37.1 | 0.766 | 120+275=395 | 395 ✓ |

栈距离分布**完全解释** LRU miss 差异（精确到个位）。**不预设 Gorder 一定更优**：其在 P1 优于 Identity、在 P3 劣于 Identity（W2H holdout 复现后者，§12）；两种情况下 Random 均最差。容量曲线（`results/gate4b1_capcurve.tsv`）显示该排序关系在容量 40–80 全区间成立（P3: identity 216/134/120 vs gorder 243/164/132；P1: gorder 268/172/139 vs identity 332/195/141），非 cap=62 特例。P3 反常的深入解释见 §11。

---

## 7. Cache Replacement Ablation（H2）

**替换规则贡献**（belady_forced vs lru_forced，同一强制装入动作集——可比的纯替换规则对比）：

| 配置 (eb0.1) | Belady-forced | LRU-forced | LRU 惩罚 |
|---|---|---|---|
| P1 gorder | 174 | 301 | +127 (+72.9%) |
| P1 identity | 196 | 362 | +166 (+84.7%) |
| P1 random | 249 | 508 | +259 (+104.0%) |
| P3 gorder | 165 | 273 | +108 (+65.5%) |
| P3 identity | 134 | 222 | +88 (+65.7%) |
| P3 random | 208 | 395 | +187 (+89.9%) |

**拒绝装入的边际贡献**（belady_reject vs belady_forced——不同动作集，单列为准入控制能力，**不**与上表混为同条件替换算法比较）：

| 配置 | reject | forced | Δ(reject−forced) |
|---|---|---|---|
| P1 gorder/identity/random (eb01) | 172/195/246 | 174/196/249 | **−2/−1/−3** |
| P3 gorder/identity/random (eb01) | 164/134/204 | 165/134/208 | **−1/0/−4** |
| P1 eb10 同序 | 172/186/237 | 173/187/240 | −1/−1/−3 |
| P3 eb10 同序 | 161/133/195 | 161/133/197 | 0/0/−2 |

结论：(a) 未来信息替换规则在同一动作集内贡献巨大（+65%~+104% LRU 惩罚，且**顺序越差惩罚越大**——好顺序部分替代了替换智能）；(b) 拒绝装入在本工作负载上边际贡献小（0–4 次）但**方向恒为非负**（24/24 组合），在 random 序上稍大（最多 −4）；(c) 拒绝同时降低实际磁盘装入次数（miss 更少）与逐出次数（如 P1 gorder：evict 92 vs 112）。**不声称**全量允许拒绝模型的最优性（仅 4B-0 的 8 个小 DP 前缀验证过；greedy 规则与 C++ 一致但非全局最优证明）。

---

## 8. Pruning Ablation（H3）

固定数据/K/bucketization/容量/窗口，仅 error_bound 变化（gorder, belady_reject）：

| 指标 | P1: eb0.1→1.0 | P3: eb0.1→1.0 |
|---|---|---|
| Candidate tasks | 1484→1435 (**−3.3%**) | 1685→1594 (**−5.4%**) |
| Distance computations | 1,833,576→1,773,186 (**−3.3%**) | 3,274,616→3,153,834 (**−3.7%**) |
| Cache miss | 172→172 (−0) | 164→161 (−3) |
| 有效读字节 | 351,744→351,104 B (−0.2%) | 330,368→325,888 B (−1.4%) |
| TP（全量 Oracle） | 190,149→187,769 (**−2,380**) | 59,151→58,366 (**−785**) |
| Recall | 63.89%→63.09% (**−0.80pp**) | 86.95%→85.80% (**−1.15pp**) |
| 每 lost-TP 节省 dist_comp | **25.4 次/TP** | **153.7 次/TP** |

结论：剪枝的主要节省在**候选任务数与距离计算**（3–5%），I/O 节省微弱（miss 变化 ≤3）；Recall 代价按 4B-0 FN 归因，主要损失发生在 **KNN 候选生成与方向过滤阶段**（本门未修改该阶段、未做 K sweep / 候选对称化）。P3 上单位 Recall 代价换得的计算节省远高于 P1（153.7 vs 25.4 次/TP）。

---

## 9. Recall / Precision 验证（全量 Oracle）

对每个 (ds,eb) 用 gate4a 冻结的**全量 GT**（`gt_{ds}.txt`）独立枚举 TP/FP/FN（不使用二进制内的 sampled recall 打印）：

| 组 | pairs | GT | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|---|---|
| P1 eb01 | 190,149 | 297,600 | 190,149 | **0** | 107,451 | 1.000 | 63.89% |
| P1 eb10 | 187,769 | 297,600 | 187,769 | **0** | 109,831 | 1.000 | 63.09% |
| P3 eb01 | 59,151 | 68,029 | 59,151 | **0** | 8,878 | 1.000 | 86.95% |
| P3 eb10 | 58,366 | 68,029 | 58,366 | **0** | 9,663 | 1.000 | 85.80% |
| W1H eb01 | 198,710 | 294,556 | 198,710 | **0** | 95,846 | 1.000 | 67.46% |
| W1H eb10 | 196,101 | 294,556 | 196,101 | **0** | 98,455 | 1.000 | 66.58% |
| W2H eb01 | 65,746 | 72,502 | 65,746 | **0** | 6,756 | 1.000 | 90.68% |
| W2H eb10 | 65,181 | 72,502 | 65,181 | **0** | 7,321 | 1.000 | 89.90% |

不变量（65 组运行全部通过，`analyze_gate4b1.py` 报告 0 问题）：
- **Pair 集合逐对恒等**：同 (ds,eb) 的 9 个 order×policy 组合（含种子/holdout/ASan/normal）→ 同一集合；W1H/W2H/P1/P3 eb01 且与 gate4a 冻结 `pairs_{ds}.txt` 集合恒等；重复对 = 0。
- **任务图序不变**（删 slot 列后多重集恒等）；tasks.txt 跨策略字节恒等。
- trace↔stats 一致（A/P 事件计数=打印计数、trace 序列=tasks 重建序列）；`read_calls == miss`（内建锚点）；effective/requested 字节离线精确复算相等；`[gate3-inv]`/`[gate4a-gorder]` 全过（perm_ok、upper_triangle_ok 等）。
- ASan vs normal 构建 pairs 逐字节一致；identity/random 运行与 **gate4b0 冻结件四件套逐字节一致**（跨门可复现）。

---

## 10. I/O 与时间指标

- **三层字节口径**（以 P1 gorder reject eb01 为例）：程序有效读 351,744 B；O_DIRECT 4096 对齐后请求读 1,040,384 B（**读放大 ≈2.96×**，源于小桶+紧邻打包布局）；**设备层物理 I/O = UNVERIFIED**（未测量，不做任何 SSD 声明）。
- 读放大跨配置稳定（2.95–3.0×）：miss 下降按比例传导到两种字节口径（LRU vs reject：P1 634,240/1,847,296 B vs 351,744/1,040,384 B）。
- **时间**（MODE=timing，无 dump，36 配置；5 关键配置 REP=5）：wall 0.08–0.12 s/次（REP=5 极差 ≤0.02 s），build ≈0.05–0.06 s，search ≈0.03–0.06 s。**亚秒级——仅作记录，禁止据此得出任何加速比**（数据集 n=4000 远小于论文 10M/1B 场景）。完整数据 `results/gate4b1_timing.tsv`。
- 计时与正确性运行分离；计时运行关闭全部逐 pair 输出与诊断 dump。

---

## 11. P1/P3 差异解释（Identity 为何在 P3 优于 Gorder）

证据链（全部来自 access trace 实测，`results/gate4b1_locality.tsv`）：

1. **栈距离**：P3 identity sd 均值 26.4 < gorder 27.3（sd<62 占比 0.868 vs 0.838 → identity 多保住 51 次缓存视距内的复访）；P1 相反（gorder 31.3 vs identity 37.8）。LRU/Belady miss 差异被该指标精确解释（§6 表）。
2. **局部目标悖论**：P3 上 gorder 的**相邻 slot 重叠反而更高**（7.59 vs identity 6.52）——Gorder 的 window-4 局部目标优化的"相邻相似性"**不等于**全局复用距离最小化；identity（kmeans 质心创建序）在 P3 的非均匀结构上恰好把相关（热）桶排得更有利。
3. **热桶结构**：P3 top-10 桶占 38.9% 访问（P1 仅 25.9%）——非均匀负载的强热点使"创建序=密度序"天然形成更好的全局时序局部性。
4. **容量稳健性**：identity 的 P3 优势在容量 40/62/80 全区间成立（216/134/120 vs 243/164/132），cap→120 时二者收敛（全驻留）——结构性差异而非工作集恰好卡 62 的伪影。
5. **跨数据集外推**：W2H（非均匀类 P3）复现 identity 优势（149 vs 171）；W1H（类 P1）gorder 略优（173 vs 176，差距远小于 P1 的 23）。

结论：**Gorder 的收益依赖负载结构**；在强热点、非均匀分布上，简单 identity 序可优于 window-4 Gorder（小规模、单线程、62 槽下的受控观察；**不外推**到论文规模）。

---

## 12. Holdout 复核（W1H/W2H）

8 组（`GATE4B1_CAPACITY=62` 钉住，因 holdout max_points 不同导致预算推导容量不同）：

| 运行 | miss | tasks | recall | FP |
|---|---|---|---|---|
| w1h_identity_belady_reject_eb01 | 176 | 1519 | 67.46% | 0 |
| w1h_gorder_belady_reject_eb01 | **173** | 1519 | 67.46% | 0 |
| w1h_gorder_belady_reject_eb10 | 168 | 1466 | 66.58% | 0 |
| w1h_gorder_lru_forced_eb01 | 288 | 1519 | 67.46% | 0 |
| w2h_identity_belady_reject_eb01 | **149** | 1766 | 90.68% | 0 |
| w2h_gorder_belady_reject_eb01 | 171 | 1766 | 90.68% | 0 |
| w2h_gorder_belady_reject_eb10 | 156 | 1678 | 89.90% | 0 |
| w2h_gorder_lru_forced_eb01 | 282 | 1766 | 90.68% | 0 |

- Pair 集合与 gate4a 冻结 `pairs_{w1h,w2h}.txt` 恒等；重建产物与 gate4a 逐字节一致；LRU victim 模型精确匹配。
- **未根据 holdout 结果做任何调参**（一次性复核）。
- W2H 复现 P3 型 identity<gorder；W1H 复现 P1 型但差距小——与 §11 的负载结构解释一致。
- 过程记录：初次 holdout 因我方配置错误（data_file 被改写到不存在的路径，上游 `read_fbin` 不检查 open 失败 → n/d 读到栈垃圾 → 2×600s 超时 + 2×SIGFPE）失败；失败日志保留于 `logs/failedcfg_w*`、`runs/failedcfg_*`，修复后重跑全部通过。上游对 ifstream 失败的静默容忍记为**健壮性观察**（未在冻结参考库修复）。

---

## 13. 负结果与未验证假设（全部保留）

1. **Gorder 非全局最优**：P3/W2H 上 identity 优于 gorder（+22%/+15% miss）——与"Gorder 普遍改善"的直觉相反，机制解释见 §11。
2. **拒绝装入边际贡献小**：本负载 0–4 次 miss（≤2%）——准入控制在 62 槽、未来信息已知时收益有限。
3. **计时不可用**：全配置亚秒级，任何配置间时间差不构成性能结论。
4. **设备层物理 I/O UNVERIFIED**：`requested_aligned_bytes` 是 syscall 口径，非 SSD 实际流量。
5. **全量拒绝模型最优性未证明**：仅 4B-0 小 DP 前缀；本门 reject=greedy（=C++ 规则）。
6. **窗口敏感性未测**：协议固定 window=4；未做窗口 sweep（超出授权矩阵）。
7. **上游潜伏 bug**：`sift_down` 越界读（§4.2）与 `read_fbin` 无 open 检查（§12）——已按纪律处置/记录。
8. **eb1.0 的 Recall 损失主要来自 KNN/方向过滤阶段**（4B-0 归因），本门未触碰该阶段。

---

## 14. Gate 4B-1 判定：**PASS**

成功条件逐条：① 三策略经 14 用例单元测试 + 65 组运行逐事件模型核对（LRU victim 精确、forced 零硬失配）✓；② 容量/window 独立可控并经字节级验证 ✓；③ 36 组主矩阵 + 12 种子 + 8 holdout + 36 计时全部完成并归档（含命令/日志/退出码）✓；④ 正确性不变量全部成立（FP=0、Pair 集合恒等、任务图恒等、trace↔stats、IO 复算）✓；⑤ 主指标全部可复现（ASan/normal 构建一致、跨门与 gate4b0 冻结件一致、与 4B-0 模型精确一致）✓；⑥ 三机制均有量化证据结论（§6–§8）✓；⑦ 负结果保留并解释（§13）✓。停止条件无一触发（OMP=1 下全程确定；差异均归因并解决）。

范围声明：本 PASS 仅覆盖受控合成小负载上的**机制消融**，不构成对论文 SIGMOD 2026 性能声明的复现。

---

## 15. Gate 5 建议（真实数据实验；本轮未执行、未授权）

1. **数据**：BigANN10M / Deep10M（先 10M 再考虑更大）；沿用冻结桶化+重建流程；GT 用官方或采样协议并独立核验（注意 in-binary recall 打印为 sampled 口径）。
2. **容量 sweep**：在真实规模上重复本门方法（容量×策略×顺序矩阵），此时 I/O 主导、亚秒问题消失；预期 LRU 惩罚与读放大（≈3×）的联合效应才可测性能。
3. **策略对比**：优先 belady_forced vs lru_forced（同动作集、结论干净）；reject 的边际贡献在容量/负载变化下重测（本门显示小但恒非负）。
4. **顺序**：在真实负载上验证 §11 的负载结构依赖（是否复现 identity 局部优势）；window sweep 一并纳入。
5. **预算/方法学**：预注册矩阵与停止条件、正确性与计时分离、每配置多 REP、设备层 I/O 用 blktrace/iostat 实测（或明确 UNVERIFIED）；保留全部失败日志。

---

## 附录：复现命令

```
# 主矩阵（36 组）
bash workspace/gate4b1/oracle/run_matrix_gate4b1.sh
# 计时（36+20 次）
bash workspace/gate4b1/oracle/run_timing_gate4b1.sh
# 单元测试（normal + ASan）
g++ -std=c++11 -O2 workspace/gate4b1/instrumented/DiskJoin/oracle/policy_test.cpp -o build/policy_test && build/policy_test
g++ -std=c++11 -O2 -fsanitize=address ... -o build/policy_test_asan && build/policy_test_asan
# 分析（65 组运行 → results/*.tsv + digest）
python3 workspace/gate4b1/oracle/analyze_gate4b1.py
# 完整性
cd workspace && md5sum -c gate4b0/data/gate4a_frozen_md5.txt
cd reference/DiskJoin && git rev-parse HEAD && git status --short
```

补丁：`workspace/gate4b1/patches/gate4b1_mechanism_and_leakfix.patch`、`workspace/gate4b1/patches/gate4b1_heap_siftdown_guardfix.patch`（均相对 gate4b0 HEAD `7e4df0c` 链）。
