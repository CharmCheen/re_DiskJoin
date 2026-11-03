# Gate 4B-0 Report — 实验方法学审计与机制对照前置验证

日期：2026-11-02 · 范围：FN 来源精确归因 / Cache 策略语义审计 / Gorder 对照公平性验证
参考源码：`reference/DiskJoin` @ `aa86151f97527b1dcf9a032d523c1d67d892454a`（本轮未改动，clean）
全部新产物：`workspace/gate4b0/`（gate4a 冻结产物零覆盖，运行前后 md5 全量核验通过）

---

## 1. Executive Summary

Gate 4B-0 三项判定**全部 PASS**：

| 判定 | 结论 | 一句话依据 |
|---|---|---|
| A. `FN_ATTRIBUTION` | **PASS** | P1/P3 全部 FN 六类互斥穷尽归因，各类之和与 oracle FN **逐对精确相等**（P1 107,451；P3 8,878）；"边覆盖却未输出"的 32 对全部量化为 ε² 浮点边界 tie，非算法 bug |
| B. `CACHE_POLICY_VALIDATION` | **PASS** | 172 vs 174（P1）与 164 vs 165（P3）的差异有**逐决策级**解释：C++ 的拒绝装入能力在 7/2 条分岔链上净省 2/1 次 miss；模型 C 与 C++ trace 命中标记 0 失配、动作类型 0 失配；A/B/C/D 四模型在同一访问序列/容量/初态/计数口径下校准 |
| C. `ABLATION_FAIRNESS` | **PASS** | identity/random/Gorder 三顺序的 bucketization（字节级）、候选任务多重集、pair 集合**完全不变**（仅 cache 动力学变化）；Gorder 窗口长度=4（整数除法链 `(budget/4/length)/K*2`）与真实滑动（`window_removals=116=120−4`）已实证；窗口已可通过 `GATE4B0_WINDOW` 独立控制而不动 mem_budget |

关键数字速览：

- **FN 归因（eb=0.1）**：P1 = class3 81,701 (76.06%) + class4 25,750 (23.94%)；P3 = class3 5,543 (62.44%) + class4 3,301 (37.18%) + class1 17 + class2 15 + class5 2。**P1/P3 的召回损失主体是 KNN 候选生成不足（class3）与上三角方向丢失（class4），而非 Algorithm 3 剪枝。**
- **Algorithm 3 增量（eb=0.1→1.0）**：P1 新增 FN 2,380（recall 63.89→63.09%），全部落在被剪的 49 条桶边上；P3 新增 785（86.95→85.80%），全部落在 91 条被剪边上；零恢复、零反向变化。
- **Cache**：A(强制 Belady)=174/165 > B=C(允许拒绝)=172/164 < D(强制 LRU)=301/273。B 的小规模精确 DP 表明 C++ 的贪心拒绝规则在全部 8 个测试前缀上恰为"允许拒绝动作集"内的最优；A 是"强制装入动作集"内的可证最优（Belady）。
- **顺序消融（P1/P3，capacity=62）**：Gorder 172/164；identity 195/**134**；random(seed 20260101) 246/204；Gorder-window-禁用 190/165。**P3 上 identity 优于 Gorder（少 30 miss）**——Gorder 在该负载上并非一致占优（观察，非结论）。

---

## 2. P1/P3 FN 分类与精确计数

### 2.1 分类语义（互斥，判定顺序固定）

对 GT 对 (u,v)（u<v，oracle：double 累加 sq_l2 < radius，严格 <），设 b(u), b(v) 为 metadata assignment 的桶号，a=min, b=max：

| 类 | 判定 | 机制 |
|---|---|---|
| 1 | b(u)==b(v) | 同桶：self-join 计算桶内全部对（`id2<id1`），理论上必被计算 |
| 2 | 边 (a→b) ∈ 最终任务图 | cross-join 对任务边**无 ID 过滤**（全部 a×b 对都算），理论上必被计算 |
| 3 | b ∉ cand[a] 且 a ∉ cand[b] | 两个方向的中心 KNN（K=24）都不含对方 → 桶对根本不可见 |
| 4 | b ∉ cand[a] 且 a ∈ cand[b] | 仅反向候选存在；任务构造的 `i <= neighbor` 上三角过滤丢弃 |
| 5 | b ∈ cand[a] 但 (a→b) ∉ 最终图 | Algorithm 3（error_bound 剪枝）丢弃前向候选 |
| 6 | 以上皆非 | 防御性；必须为 0 |

### 2.2 精确计数（总量与 oracle FN 严格相等）

**P1（eb=0.1，GT=297,600，TP=190,149，FN=107,451，FP=0）**

| 类 | FN 对数 | 占比 | 桶对数 | 最大桶对样本 |
|---|---:|---:|---:|---|
| 1 同桶 | 0 | 0.00% | 0 | — |
| 2 边覆盖 | 0 | 0.00% | 0 | — |
| 3 双向无候选 | 81,701 | 76.06% | 3,969 | (41,70):438 · (35,117):280 · (64,92):274 |
| 4 仅反向 | 25,750 | 23.94% | 476 | (7,86):306 · (86,99):259 · (8,64):255 |
| 5 Alg3 剪枝 | 0 | 0.00% | 0 | — |
| 6 未解释 | 0 | 0.00% | 0 | — |
| **合计** | **107,451** | 100% | | |

**P3（eb=0.1，GT=68,029，TP=59,151，FN=8,878，FP=0）**

| 类 | FN 对数 | 占比 | 桶对数 | 最大桶对样本 |
|---|---:|---:|---:|---|
| 1 同桶 | 17 | 0.19% | 16 桶 | 边界 tie（见 §9.1） |
| 2 边覆盖 | 15 | 0.17% | 15 桶对 | 边界 tie（见 §9.1） |
| 3 双向无候选 | 5,543 | 62.44% | 919 | (86,109):166 · (86,116):160 · (86,98):148 |
| 4 仅反向 | 3,301 | 37.18% | 206 | (93,104):489 · (93,112):233 · (104,113):189 |
| 5 Alg3 剪枝 | 2 | 0.02% | 2 桶对 | (2453,2459)@桶(24,91) fwd dist/2=0.466154；(1789,1811)@桶(57,113) fwd=0.46035 |
| 6 未解释 | 0 | 0.00% | 0 | — |
| **合计** | **8,878** | 100% | | |

**eb=1.0**：P1 FN=109,831（class5=2,380，其余各类不变）；P3 FN=9,663（class5=787）。

### 2.3 覆盖一致性双向验证

- `found ⊆ coverage`（join 语义覆盖集合）：P1/P3 **0 个 found 落在覆盖外**；
- `(coverage ∧ GT) − found` = 恰好 class1∪class2（P1: ∅；P3: 32 对，全部边界 tie）；
- 任务图无重复非头边（`tasks_dup_nonhead=0`）、knn dump 无重复标签（`knn_dup_labels=0`）、上三角不变量 `upper_triangle_ok=1`。

### 2.4 class5=2（P3, eb=0.1）机制注记

两个被剪前向候选的 `dist/2`（0.466 / 0.460）**大于 ε=√0.2≈0.4472**，其 `arcos(x>1)` 截断为 0；剪枝循环从远端累加角度、在到达该候选之前近端候选的角和已 ≥ eb=0.1，故 keep 区间 `[0..ptr]` 未覆盖它。这解决了 4A 遗留的"P3 eb=0.1 惰性未定"问题：**非惰性，但影响仅 2 个 GT 对**（75 条上三角兼容候选边被剪，仅 2 个桶对带 GT 对）。

---

## 3. Directed top-K / Upper-Triangle 机制影响

**候选图是有向的，桶对是无向的**：`knnSearchBaseLayer(i, K)` 对中心 i 返回 K 个近邻中心 → 有向候选边 i→j。K=24、120 桶 → 2,760 条有向候选边（去自环）：

| | P1 | P3 |
|---|---:|---:|
| 有向候选边总数 | 2,760 | 2,760 |
| 上三角兼容方向（i<j） | 1,364 | 1,640 |
| 仅反向方向（i>j） | 1,396 | 1,120 |
| 最终任务边（eb=0.1） | 1,364 | 1,565 |
| Alg3 在上三角兼容方向中剪掉 | 0 | 75 |

机制影响量化：

1. **上三角过滤（`i <= neighbor`）** 是为避免 (a,b) 与 (b,a) 重复 cross-join 的正确性设计，但把"哪个方向拥有边"变成标签偶然性：P1 有 476 个 GT 桶对、P3 有 206 个 GT 桶对**仅因为近邻方向恰好是 j→i 而完全丢失**（class4：P1 25,750 对 / P3 3,301 对，占 FN 的 23.94% / 37.18%）。这是仅次于候选不足的第二大漏召回来源，且**与 error_bound 无关、不可由 eb 恢复**。
2. 有向候选的重叠率低（P1 仅 1,364/2,760 方向兼容），说明 KNN 中心图的近邻关系高度不对称；对称化（取并集）理论上可消除 class4，代价是任务数增加（需 4B-1 单独消融验证，未执行）。
3. join 侧对任务边无 ID 过滤（全部 a×b 对计算、canonical (min,max) 输出），因此 class2 恒应为 0——P3 的 15 个非零全部是 ε² 边界 tie（§9.1），非算法错误。

---

## 4. Algorithm 3 的增量漏召回（eb=0.1 → 1.0）

| | P1 | P3 |
|---|---:|---:|
| FN(eb=0.1) | 107,451 | 8,878 |
| FN(eb=1.0) | 109,831 | 9,663 |
| **增量 FN** | **2,380** | **785** |
| 落在被剪桶边上的增量 | 2,380（100%） | 785（100%） |
| 被剪桶边总数（带 GT 对的） | 49（49） | 91（39） |
| 恢复（eb1.0 反而找到） | 0 | 0 |
| 新增边（eb1.0 新出现） | 0 | 0 |
| recall | 63.89 → 63.09% | 86.95 → 85.80% |

- 增量 FN **全部**可映射到被剪桶边（`incremental_on_dropped_edges == incremental_fn`，逐对验证）；被剪边集严格递减（`added_edges=0`），无任何恢复——剪枝是单调收紧。
- 带最多 GT 对的被剪边：P1 `34→100`:256、`94→114`:206、`72→88`:195；P3 `110→116`:283、`90→112`:145、`92→108`:99。
- **eb=0.1 时 P1 完全惰性（0 增量），P3 仅 2 对**——在预登记负载上 Algorithm 3 对召回的边际伤害在 eb≤0.1 可忽略，主要伤害在 class3/class4（候选生成与方向性）。

---

## 5. Cache Admission / Eviction 语义（源码级）

`lib/Cache.h` + `utils/heap.h` 逐行审计结论（gate4b0 副本与参考仓库逐字节一致）：

1. **future-use 索引**：`init(reordered_tasks)` 按 slot 顺序展开任务表，`iters[id]` = id 的全部访问位置升序列表 + 每桶一个 `SIZE_MAX` sentinel。**注意：索引建立在 Gorder 重排后的 slot 序上，顺序改变即改变未来使用序列**——这是顺序消融作用于 cache 的唯一通道。
2. **find**：`total++`；**`ptr[id]++` 先于驻留检查**，故 `iters[id][ptr[id]]` 恒为"本次访问之后的下一次使用位置"；未驻留 → miss（= 一次磁盘读）；驻留 → `priority.update((id, next_use))` 更新键 + memcpy 到 join scratch buffer。
3. **push（每次 miss 恰好调用一次）**三分支：
   - `filled < size`：**无条件 cold admit**（即使 next_use=sentinel 也装入，成为永久 victim 候选）；
   - `priority.top().second > iters[id][ptr[id]]`：驱逐 next-use 最远者（`updateable_heap<size_t,size_t,std::greater>` 为 max-heap，**sentinel=SIZE_MAX 视作 +∞，never-again 桶优先被驱逐**），装入 incoming；
   - 否则 **reject**：incoming 保持非驻留（`address_table[id]` 仍 −1），数据已在 scratch buffer，join 正确性不受影响；该桶下次访问将再次 miss 并重试 push。
4. **堆语义**：`std::greater` → `sift_up` 在 `aux > parent` 时上移 → top()=最大 next-use（Belady victim）✓；`update()` 原位换键并按升降重排 ✓；有限 next-use 两两不同（每个位置只访问一个桶），**平局仅存在于 sentinel 之间**（可互换，miss 口径不可区分，见 §6 victim 等价证明）。
5. **miss 统计定义**：`miss = find 返回 false 的次数 = 磁盘读次数`；`miss = total − hit`；每次 miss 恰一次 push（P1: 62+92+18=172 ✓；P3: 62+67+35=164 ✓）。
6. **容量**：`size = budget/4/length`（length=max_points×d）；P1 small 0.000255 GB→62 槽，P3 small 0.0004→62 槽。容量可从 trace 自推导（cold admit 计数=62）。
7. 仓内 `simulate_cache` 有**隐式 reject**（满载且 victim next-use ≤ incoming 时空 else 分支）——与 C++ `Cache::push` 同规则族；gate4a 的 `trace_policy_sim.py` 是 **always-admit**（= 本轮模型 A）。

---

## 6. Offline OPT 与 C++ Cache 差异解释（172 vs 174 / 164 vs 165）

### 6.1 四模型定义（同一访问序列 / 容量 62 / 空初态 / 同 miss 口径）

| 模型 | 动作集 | 决策规则 | P1 | P3 |
|---|---|---|---:|---:|
| **A 强制装入 OPT** | miss 必插入；满则驱逐任一常驻 | Belady：驱逐 next-use 最远（sentinel=∞）——**强制动作集内可证最优**（Belady MIN 论证；DP 复核） | 174 | 165 |
| **B 允许拒绝 OPT** | miss 可插入（驱逐任一）或跳过 | 全量 trace 上为贪心规则的**确定性模拟**（= C++ 规则）；精确最优仅在 8 个小前缀上 DP 验证（见 §6.3） | 172 | 164 |
| **C C++ 当前实现** | 同 B | `Cache::find/push` 精确复刻（ptr/iters/sentinel/update-on-hit） | 172 | 164 |
| **D 强制装入 LRU** | 同 A（仅 victim 规则不同） | 驱逐最久未使用 | 301 | 273 |

能力集关系：`Σ_forced={miss必插入+驱逐选择}` ⊂ `Σ_reject={插入+驱逐选择, 或跳过}`。A 是 Σ_forced 的最优；B/C 属 Σ_reject；D 与 A 同能力集。**LRU+拒绝在语义上不可定义**（拒绝判据 `victim_next_use > incoming_next_use` 需要未来知识，恰是 LRU 所无），故 D 取强制装入——这是公平的（D 与 A 同能力集）。

### 6.2 模型 C 与 C++ trace 逐决策校准

- 访问序列从任务 dump 重建 == trace A-line 序列（P1/P3 **完全相等**，长度 1484/1685）；gate4b0 trace 与 gate4a 冻结 trace **字节相同**。
- **A-line 命中标记：0/1484、0/1685 失配**；**P-line 动作类型：0 失配**；**P-line victim：0 硬失配**（23/15 处 sentinel 平局 victim 与 C++ 堆选择不同，经 iters/ptr 索引证明双方 victim 的 next-use 均为 sentinel——never-again，对后续命中/miss 不可区分，属可互换等价类）。
- 结论：C++ Cache 的策略语义被模型 C **完全捕获**。

### 6.3 172 < 174 / 164 < 165 的精确机制

**分岔链分析**（A 与 C 锁步模拟，链=驻留集相异的极大区间；链上 miss 差分之和 == 全局差分，逐链断言成立）：

- **P1：7 条链，净 +2。** 两条损失链：
  - 链 [526..689]（+1）：i=526 桶 2 miss。A **被迫**装入 2（驱逐 next-use@689 的 105——它是当时最远者但**会被再用**）；C 判 2 的 next-use（never-again=∞）≥ victim 的 689 → **拒绝**，保住 105。i=689：A miss 105 / C hit 105。净 +1。
  - 链 [883..1163]（+1）：同型——i=883 桶 26（never-again）miss，A 驱逐 112（next-use@1159）装入 26，C 拒绝；i=1159 A miss / C hit。净 +1。
  - 其余 5 条链 delta=0：强制装入驱逐的 victim 本就 never-again，无害。
- **P3：2 条链，净 +1。** 链 [439..456] delta=0（无害）。链 [532..1684]（+1，1153 事件）发起于 i=532 桶 119（A 驱逐 71@909 装入 119，C 拒绝）；命中差异事件 5 个：909（A miss/C hit）、970（A hit/**C miss**）、1112（A miss/C hit）、1494（A miss/C hit）、1555（A hit/**C miss**）→ 净 +1。**注意非单调**：拒绝也使 C 在 970/1555 付出代价（被拒的桶被再次访问），净收益为 +1 而非逐事件单边。

**最小反例**（容量 1，trace `[0,1,0]`，桶 1 never-again）：强制 Belady 3 miss（0 装、1 驱 0 装、0 miss）vs 拒绝规则 2 miss（0 装、1 拒、0 hit）；精确 DP 证实 3 与 2 分别为两动作集的最优（`results/cache_models.json`）。机制即上：**强制装入迫使系统用"会被再用的常驻者"换取"可能再也不会用的 incoming"；拒绝能力恰好免掉这笔坏交易**。

### 6.4 小规模精确 DP（不将近似标注为精确 OPT）

前缀 × 容量 = {40×2, 40×3, 60×2, 80×2}（P1/P3 各 4 组，共 8 组）：

| 组 | forced-DP | greedy-A | reject-DP | greedy-B |
|---|---:|---:|---:|---:|
| P1 40/2 | 39 | 39 | 38 | 38 |
| P1 40/3 | 38 | 38 | 37 | 37 |
| P1 60/2 | 58 | 58 | 56 | 56 |
| P1 80/2 | 76 | 76 | 72 | 72 |
| P3 40/2 | 39 | 39 | 38 | 38 |
| P3 40/3 | 38 | 38 | 37 | 37 |
| P3 60/2 | 58 | 58 | 56 | 56 |
| P3 80/2 | 77 | 77 | 74 | 74 |

- greedy-A == forced-DP（8/8）：Belady 强制最优性复核 ✓（同时验证 DP 实现本身）。
- **greedy-B == reject-DP（8/8）：未找到 C++ 贪心拒绝规则次优的反例**；reject-DP < forced-DP（8/8）：拒绝能力在该 trace 家族上严格有益。
- **诚实标注**：全量 trace（1484/1685 访问、容量 62、120 桶）的 Σ_reject 精确最优状态空间过大未求解；B 的全量结果 172/164 是**贪心规则的确定性模拟**（= C++ 行为），只能作为 Σ_reject 最优的**上界**引用。A 的 174/165 则是可证最优（Belady 论证 + DP 复核），非近似。

---

## 7. LRU 公平基线定义

- **D = 强制装入 LRU**：与 A 同动作集（miss 必插入、victim=LRU），同访问序列/容量/初态/计数。P1=301、P3=273（复现 gate4a 冻结值，逐 miss 一致）。
- LRU 与 C++ 的比较是**跨能力集**的：C++（B/C）多出拒绝动作且 victim 选择用未来知识。若要在同能力集内比较"victim 规则"的贡献，应比 A vs D（Belady vs LRU，均强制）：P1 省 127 miss、P3 省 108 miss；"拒绝能力"的贡献应比 B vs A：P1 省 2、P3 省 1。
- "LRU+拒绝"不可定义（拒绝判据需未来知识），故 4B-1 的策略因子应取 {C++ Belady-拒绝, 强制-Belady, 强制-LRU} 三档，全部在同一容量与访问序列下。

---

## 8. Gorder 公平对照验证（Task 3）

### 8.1 顺序改变的语义边界（代码级证明 + 运行级验证）

`search()` 中 `order_gorder` 返回 bucket→slot 的 rank 映射；`reordered_tasks[perm[i]] = shuffled_tasks[i]` **只搬运任务表的 slot 位置**——桶标签、任务表内容、上三角过滤（在任务构造期基于原始标签）、join 逻辑全部不变。因此顺序只通过一条通道起作用：**`cache.init(reordered_tasks)` 建立在 slot 序上的未来使用索引**（+ 逐 slot 的装载顺序）。

**运行验证**（`oracle/order_invariance.py`，全部 PASS）：

| 校验 | P1 | P3 |
|---|---|---|
| pair 集合跨 {default, identity, random, window120} + 冻结件不变 | ✓ 190,149 | ✓ 59,151 |
| 任务多重集 {(target, list)} 跨全部顺序 + 冻结件不变 | ✓ 120 条 | ✓ 120 条 |
| found ⊄ 覆盖 / 重复目标桶 | 0 / 0 | 0 / 0 |
| 与 default 同内容的 slot 数：identity / random / window120 | 2 / 2 / 14 | 1 / 0 / 10 |

### 8.2 跨顺序 cache 统计（capacity=62，同 mem_budget/policy/eb）

| 顺序 | window | P1 miss (evict/reject) | P3 miss (evict/reject) |
|---|---|---:|---:|
| Gorder（默认，真实滑动） | 4 | **172** (92/18) | 164 (67/35) |
| identity | — | 195 (111/22) | **134** (54/18) |
| random seed 20260101 | 4 | 246 (111/73) | 204 (83/59) |
| Gorder，窗口禁用 | 120 | 190 (95/33) | 165 (69/34) |
| （P3 eb=1.0，Gorder w=4，参考） | 4 | — | 161 (70/29)，访问数 1594 |

- **Gorder 窗口滑动机制的贡献**（唯一变量）：P1 190→172（−18 miss）、P3 165→164（−1）。
- **P3 上 identity（134）优于 Gorder（164）**：顺序优劣是负载相关的；Gorder 的收益假设（磁盘局部性）在 miss 计数上不成立于此负载。**观察，非结论**——正式结论需 4B-1 的多种子+I/O 时间口径。

### 8.3 Gorder 窗口长度与滑动机制确认

- 窗口长度 = `(budget/4/length)/K*2`（整数除法链）：P1 small `(273804/4/1104)=62; 62/24=2; 2*2=4` → **window=4**；与 cache capacity 同源于 mem_budget（一源三用：writer buffer / capacity / window）。
- **真实滑动**：`move_window` 中 `old_node = order[order.size()-window-1]`——窗口=order 序列最近 window 个节点；`[gate4a-gorder] insertions=120 window_removals=116`（=120−4，从第 5 次起每次移出窗口最老节点）；`GATE4B0_WINDOW=120 ≥ n` 时 `window_removals=0`（滑动关闭）。
- UnitHeap 惰性增量：`lazyIncrement` 挂起 `update[]` 增量，`ExtractMax→DecreaseTop` 应用一半并检查换顶——真实实现语义（**注**：`move_window` 中对 parent 本体的 `lazyIncrement(parent,±1)` 被注释，只更新 siblings——按实际代码记录，非论文理想形式）。
- `GATE4B0_ORDER/GATE4B0_PERM_FILE/GATE4B0_WINDOW` 补丁在 `order_gorder` **之后**替换 perm / 替换窗口参数，不触碰 mem_budget——cache capacity 与 writer buffer 不受影响；默认行为零改变（R2/R3 与 gate4a 冻结 trace/tasks/pairs/artifacts 逐字节一致 = 补丁惰性证明）。

### 8.4 公平性清单（对照任务要求逐项）

| 要求 | 状态 | 证据 |
|---|---|---|
| 完全相同 bucketization | ✓ | 每次运行后 `cmp`：重建 .clusters/.metadata/.hnsw 与 gate4a 冻结件**字节一致**（11 次运行全过；OMP=1） |
| 完全相同候选任务多重集 | ✓ | §8.1 任务多重集跨顺序恒等 |
| 相同 cache 容量 | ✓ | 全部 62 槽（同 mem_budget；顺序补丁不动预算） |
| 相同 cache 策略 | ✓ | 全部 C++ Belady-拒绝（未改 Cache.h） |
| 相同内存预算与硬件 | ✓ | 同机、OMP=1、mem_budget 不变（window 覆盖独立于预算） |
| 相同 Recall 口径 | ✓ | 全 oracle 集合比对（GATE3_PAIR_OUT vs gt_*.txt，TP/FP/FN/dup 全计数） |
| 任务集合跨顺序一致 | ✓ | §8.1 |
| Gorder 窗口长度与滑动确认 | ✓ | §8.3 |
| 不通过 mem_budget 同时改变两机制 | ✓ | window 独立暴露（补丁）；capacity 独立化留待 4B-1（§10） |

---

## 9. 已确认问题和未验证假设

### 9.1 已确认问题（本轮新证据）

1. **P3 的 17（同桶）+15（边覆盖）个"覆盖型 FN"是 ε² 浮点边界 tie，非算法 bug**：oracle（double 累加，阈值 0.2）判入、C++（float32 AVX2 FMA 距离，阈值 `float(sqrtf(0.2f))²=0.19999998807907104`）判出。32 对的 `|dist²−0.2|/0.2` 全部 ≤ 6.137e-8（最小 2.621e-9，float32 ULP 量级）；顺序 float32 模拟拒绝其中 29/32（其余 3 个归因 FMA 分道累加的舍入差，仍在 ULP 内）。P1/P3 上该分歧**单边**（FP=0：无 C++ 判入而 oracle 判出的对）。这是**度量约定差异**（精确 double oracle vs float32 实现口径），报告 recall 时应声明。
2. **上游内存泄漏（新发现）**：`ClusterWriter::writeClusters`（`lib/ClusterIO.h`）的 `new char[cluster_num*buffer_size]`（P3 small: 430,080 B）与 `new float[batch_size*d]`（256 B）从不释放。LeakSanitizer 使进程 exit 1（无其它内存错误）；`detect_leaks=0` 后 rc=0 且全部统计与 normal 构建一致。**非本轮补丁引入**（补丁只改 search()），未修改参考代码。
3. **P3 eb=0.1 剪枝非惰性**（4A 遗留问题关闭）：75 条上三角兼容候选边被剪、损失 2 个 GT 对（§2.4）。
4. **仓内 `simulate_cache` 隐式拒绝**：满载且 victim next-use ≤ incoming 时空 else——与 C++ `Cache::push` 同规则；gate4a 离线 sim 为 always-admit（本轮重新标注为模型 A）。
5. **Gorder `move_window` 只更新 siblings**（parent 本体增量被注释）——实际实现语义与论文理想形式的可能偏差，按代码记录。
6. （沿袭）gate3 `audit_metadata.py` check-6 的桶索引/向量 ID 混淆（4A 已勘误）；`add2choice` 2-choice vs 论文 nearest-center（G3-01 结论保留）。

### 9.2 未验证假设（显式登记）

1. **PACMMOD 正式版（DOI 10.1145/3769780）与 arXiv v2 的 parity**：正式 PDF 仍缺，无法核对（沿袭 Gate 0 blocker，非阻断）。
2. **greedy-B 在全量 trace 上的最优性**：仅在 8 个小前缀上与 reject-DP 相等；全量 Σ_reject 精确最优未求解（状态空间过大）。引用 172/164 时必须标注"贪心模拟=上界"。
3. **Gorder 在 P3 上 miss 劣于 identity 的根因**（磁盘局部性假设 vs miss 计数口径）：未测 I/O 时间，需 4B-1。
4. **float32 FMA 分道累加的 bit 级行为**：以顺序 float32 模拟近似（29/32 复现），3 个剩余 tie 归因于 FMA 舍入序（ULP 内，不影响"边界 tie"判定）。

---

## 10. Gate 4B-1 最小实验矩阵（设计，未执行）

**前提**（本轮已验证的公平性基础设施）：冻结 OMP=1 bucketization（每运行 cmp）、任务多重集/pair 集合恒等断言、全 oracle recall 口径、`GATE4B0_ORDER/PERM_FILE/WINDOW` 补丁。

| 因子 | 水平 | 载体 | 需要的新改动 |
|---|---|---|---|
| F1 任务顺序 | identity / Gorder / random(≥3 种子) | 已就绪 | 无（补丁已有） |
| F2 cache 策略 | C++ Belady-拒绝 / 强制-Belady / 强制-LRU | 需最小 patch | (a) 策略选择 env（接入 `LRUCache` 或强制装入变体）；(b) **`GATE4B0_CAPACITY` 容量覆盖**（当前 capacity 仍由 mem_budget 推导，须独立钉住才能与 F1/F3 正交） |
| F3 error_bound | 0.1 / 1.0 | 已就绪 | 无（config） |

- **矩阵**：P1/P3 × F1(3) × F2(3) × F3(2) = 36 次运行（OMP=1、分钟级）＋每运行不变量断言（pair 集合在固定 eb 下跨 F1/F2 恒等；recall 差异只能来自 F3；任务图差异只能来自 F3）。
- **度量**：全 oracle TP/FN/FP/recall；hit/miss/admit/evict/reject；读盘字节（每 miss 记 `bucket_sizes×d×4`，加一个 env 门控计数器）；dist_comp；正确性与计时分开跑。
- **停止条件**（沿袭 4A §11.4）：OMP=1 出现 run-to-run 漂移；任务图不变而 recall 变；任一变体 FP>0 或 ASan 报错；顺序/策略变体 pair 集合与基线不恒等。

---

## 11. 全部原始证据、命令与补丁

### 11.1 运行清单（`workspace/gate4b0/`，全部 OMP_NUM_THREADS=1、timeout 600、串行）

| # | run | config | GATE4B0 env | 结果（rc=0 除注明） |
|---|---|---|---|---|
| R1 | `runs/p3_eb1.0_small_dumps/` | `data/p3_eb1.0_small_g4b0.config` | — | 补齐 P3 knn dump + eb1.0 任务图；tasks=1594、pairs=58,366（与冻结集合相同）、miss=161(70/29) |
| R2 | `runs/p1_default/` | `data/p1_small_g4b0.config` | — | 补丁惰性证明：trace/tasks/knn/pairs 与 gate4a 冻结件**逐字节一致**；miss=172(92/18)、pairs=190,149 |
| R3 | `runs/p3_default/` | `data/p3_small_g4b0.config` | — | 同上（trace/tasks/pairs 字节一致；knn 跨 eb 字节一致）；miss=164(67/35)、pairs=59,151 |
| R4/R5 | `runs/{p1,p3}_identity/` | small | `GATE4B0_ORDER=identity` | miss=195(111/22) / 134(54/18)；pairs 190,149 / 59,151 |
| R6/R7 | `runs/{p1,p3}_random/` | small | `GATE4B0_ORDER=file GATE4B0_PERM_FILE=data/perm_random_seed20260101.txt` | miss=246(111/73) / 204(83/59) |
| R8/R9 | `runs/{p1,p3}_window120/` | small | `GATE4B0_WINDOW=120` | window_removals=0；miss=190(95/33) / 165(69/34) |
| R10 | `runs/p3_default_asan*/` | small | — | ASan：无内存错误；LeakSanitizer 报上游 2 处泄漏（exit 1，§9.1-2）；`detect_leaks=0` 后 rc=0 统计一致 |

每次运行后 `cmp` 重建 .clusters/.metadata/.hnsw vs gate4a 冻结件（全部字节一致）；运行前后 `md5sum -c data/gate4a_frozen_md5.txt` 全过（8 文件 OK）。固定种子排列：`data/perm_random_seed20260101.txt`（`random.Random(20260101).shuffle(range(120))`，首 10 项 114,14,75,71,48,102,109,31,60,26）。

### 11.2 命令（可复现序列）

```bash
# 构建（gate4b0 副本，含 4A 全部插桩 + 本轮补丁）
cd workspace/gate4b0/instrumented/DiskJoin
cmake -S . -B ../../build/normal -DCMAKE_BUILD_TYPE=Release && cmake --build ../../build/normal -j4
cmake -S . -B ../../build/asan -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_CXX_FLAGS="-fsanitize=address -fno-omit-frame-pointer" && cmake --build ../../build/asan -j4
# 运行（oracle/run_gate4b0.sh：OMP=1 + timeout 600 + 全部 dump env）
./oracle/run_gate4b0.sh p3_eb1.0_small_dumps data/p3_eb1.0_small_g4b0.config
./oracle/run_gate4b0.sh p1_default        data/p1_small_g4b0.config
./oracle/run_gate4b0.sh p3_default        data/p3_small_g4b0.config
./oracle/run_gate4b0.sh p1_identity       data/p1_small_g4b0.config GATE4B0_ORDER=identity
./oracle/run_gate4b0.sh p3_identity       data/p3_small_g4b0.config GATE4B0_ORDER=identity
./oracle/run_gate4b0.sh p1_random         data/p1_small_g4b0.config \
    GATE4B0_ORDER=file GATE4B0_PERM_FILE=data/perm_random_seed20260101.txt
./oracle/run_gate4b0.sh p3_random         data/p3_small_g4b0.config \
    GATE4B0_ORDER=file GATE4B0_PERM_FILE=data/perm_random_seed20260101.txt
./oracle/run_gate4b0.sh p1_window120      data/p1_small_g4b0.config GATE4B0_WINDOW=120
./oracle/run_gate4b0.sh p3_window120      data/p3_small_g4b0.config GATE4B0_WINDOW=120
BIN=build/asan/main ./oracle/run_gate4b0.sh p3_default_asan        data/p3_small_g4b0.config
BIN=build/asan/main ASAN_OPTIONS=detect_leaks=0 \
    ./oracle/run_gate4b0.sh p3_default_asan_noleak data/p3_small_g4b0.config
# 分析
python3 oracle/order_invariance.py     # Task 3 不变量
python3 oracle/fn_attribute.py         # Task 1 归因（含边界分析）
python3 oracle/cache_models.py         # Task 2 四模型 + DP + 分岔链
# 确定性/完整性
for f in clusters metadata hnsw; do cmp data/p3.$f ../gate4a/data/p3.$f; done
md5sum -c data/gate4a_frozen_md5.txt
```

### 11.3 补丁与代码资产

- `patches/gate4b0_order_window.patch`（85 行，commit `7e4df0c`，基于 4A 副本 6-commit 历史）：`lib/DiskJoin.h` 增 `#include <cstring>`；`GATE4B0_WINDOW`（覆盖 `order_gorder` 的窗口参数）；`GATE4B0_ORDER ∈ {identity, file}` + `GATE4B0_PERM_FILE`（在 `order_gorder` **之后**替换 perm；file 模式校验排列合法性）；env 设置时打印 `[gate4b0] order=... window=... window_default=...`。**默认（env 未设）行为零改变**（R2/R3 字节级证明）。
- `instrumented/DiskJoin`：本地 git，7 commits（HEAD `7e4df0c`），工作树 clean；gate4a 插桩仓库未被触碰。
- oracle 脚本（纯 stdlib）：`oracle/run_gate4b0.sh`、`oracle/order_invariance.py`、`oracle/fn_attribute.py`、`oracle/cache_models.py`。
- 结果：`results/order_invariance.json`、`results/fn_attribution.json`、`results/cache_models.json`、`results/divergence_summary.json`；日志 `logs/<run>.{stdout,stderr}`。
- gate4a 冻结资产零覆盖（md5 前后核验）；`reference/DiskJoin` 零改动（pinned SHA、clean）。

---

## 12. 最终判定

| 判定 | 结论 | 通过条件核对 |
|---|---|---|
| A. `FN_ATTRIBUTION` | **PASS** | P1: 81,701+25,750+0+0+0+0 = 107,451 = oracle FN；P3: 17+15+5,543+3,301+2+0 = 8,878 = oracle FN；eb=1.0 增量 2,380/785 全部落被剪边；class6=0；"边覆盖未输出"32 对已单独报告并量化为浮点边界 tie（非算法正确性缺陷，系度量约定差异） |
| B. `CACHE_POLICY_VALIDATION` | **PASS** | 172 vs 174 / 164 vs 165 = 拒绝能力在 2/1 条净损失链上的精确贡献（逐链 miss 差分求和==全局差分，断言通过）；A/B/C/D 同序列/容量/初态/口径校准；C 与 C++ trace 逐决策吻合（0 命中失配/0 动作失配/0 硬 victim 失配）；OPT 标注诚实（A 可证最优；B 全量为贪心模拟上界，最优性仅小规模 DP 验证） |
| C. `ABLATION_FAIRNESS` | **PASS** | 三因子（顺序/缓存/剪枝）的控制变量与指标口径明确：bucketization 字节级冻结、任务多重集与 pair 集合跨顺序恒等（运行验证）、容量/策略/预算/Recall 协议固定、Gorder 窗口长度与真实滑动已实证、窗口已可独立控制（不动 mem_budget）；容量独立控制（`GATE4B0_CAPACITY`）已识别为 4B-1 前置项 |

**Gate 4B-0 = PASS。** 按本轮授权范围在此停止：未执行 Gate 4B-1 消融矩阵（§10 仅设计）、未跑 Gate 5 / 论文级性能实验、未跑 10M/100M、未改参考仓库、未 sudo、未 commit/push 任何远程。下一步（若授权）：按 §10 矩阵执行 36 次 OMP=1 运行。
