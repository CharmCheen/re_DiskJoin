# DiskJoin 核心思想（给复现 Agent 的技术背景）

**论文**：Yanqi Chen, Xiao Yan, Alexandra Meliou, Eric Lo. *DiskJoin: Large-scale Vector Similarity Join with SSD*. PACMMOD 3(6), Article 315, Dec. 2025, DOI `10.1145/3769780`（SIGMOD 2026）。

## 1. 问题和成本模型

输入为存储在 SSD 上的向量 `X = {x_1, ... x_n}`，距离阈值 `epsilon`。目标是寻找满足 `i<j` 且 `||x_i-x_j||_2 <= epsilon` 的相似对。公开实现采取近似策略，必须测量 Recall。

独立执行 n 次基于磁盘的近邻查询会造成：

- Read amplification：一次查询仅需要很少的字节，却触发页级甚至更大的 SSD 访问。
- Redundant I/O：邻近向量的候选近邻有较大重叠，独立查询反复加载同一数据。

DiskJoin 的核心洞察：离线相似连接可以提前组织完整候选任务，把任务之间潜在的数据复用用于执行顺序和缓存管理的联合优化。

## 2. 端到端路线

1. **Bucketing / access batching**：按距离将向量映射到 Bucket，并在 SSD 上连续布局。一个 Bucket 有中心、半径、成员列表。目标是让 I/O 与后续计算共享一个较大的访问粒度。
2. **Candidate bucket graph**：节点是 Bucket，边表示需要执行跨 Bucket 距离验证的潜在任务。通过几何过滤、HNSW 候选搜索和概率剪枝减少边数。桶内还需做自连接。
3. **Task orchestration**：每个 Bucket 可能关联若干候选 Bucket。选择处理桶的顺序，尽量让相邻任务共享输入桶。
4. **Gorder-based reordering**：给定节点执行排列 P，偏好在长度为 w 的滑动窗口里共享更多候选邻居，形成时间局部性。Gorder 是近似/启发式方法，不保证全局最优。
5. **Belady cache**：任务顺序已知后，缓存可预测未来访问；满缓存时淘汰下一次使用最晚的桶。在等大小块、固定访问序列的经典模型下最优。
6. **Exact distance checking of surviving pairs**：对实际载入的候选桶计算 L2 距离并确认阈值。近似/遗漏来自候选构建与剪枝，不来自精确距离公式本身。

## 3. 三层 Insight

- **空间局部性**：同一桶的数据连续写 SSD，以 bucket-wise loading 减少碎片化随机访问。
- **时间局部性**：把有共同候选邻居的桶排近，避免短期反复读取。
- **离线已知工作负载**：任务图与顺序确定后，可用未来访问序列优化 Cache Replacement。

**注意 Gorder 与 Belady 的分工**：前者改变访问序列以创造复用；后者在固定序列中决定缓存淘汰。单独使用 Belady 不能修正糟糕的任务顺序。

## 4. Micro thought experiment（见 `scripts/micro_task_cache.py`）

缓存 2 个等大小 Bucket，任务是 `(A,B), (C,D), (A,C)`。用 Belady 时，按原顺序需要 5 次加载；改成 `(A,B), (A,C), (C,D)` 只需 4 次。任务集合相同、距离计算量相同。这里的顺序为人工构造，**不声称是官方 Gorder 在这张 toy 图上的具体输出**。

## 5. 准备读源码时先回答

1. 候选桶图在什么位置建立？`tasks[i]` 的每项具体表示什么？
2. `order_gorder()` 怎样按邻居重叠构造新的桶处理顺序？输出的置换方向是什么？
3. `Cache.init()` 如何从执行序列生成 future-use 索引？cache find/miss/replace 的策略是什么？
4. `Kmeans` 的数据布局和 `ClusterIO` 的 `O_DIRECT` 如何相互配合？
5. Recall 的真实定义、统计方式、采样位置、精确 GT 对应什么数据集？

## 6. 强制区分的研究结论层级

- Micro toy 有差异 → 只能确认时间局部性的直观可行性。
- 官方 C++ 代码 toy 跑通 → 只能确认当前环境的基本兼容性与部分执行路径。
- 机制消融在相同数据/Recall/预算下有收益 → 能对机制的效果提供实证支持。
- 对齐正式论文的数据、基线、资源与实验设置 → 才能讨论论文级复现程度。
