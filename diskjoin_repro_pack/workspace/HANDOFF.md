# DiskJoin Gate 0–4B-1 Handoff

- 日期：2026-11-02（Gate 4B-1 更新）
- 范围：Gate 0（环境/源码/论文审计）、Gate 1（离线机制演示）、Gate 2（12k toy C++ Smoke Test）、Gate 3（正确性 + 论文–源码一致性审计）、Gate 4A/4B-0/4B-1（显式授权下的受控消融）
- 明确未执行：Gate 5（真实数据 10M+ 实验、论文级性能 Benchmark）、多机实验
- 结论速览：
  - **Gate 0：PASS（环境与源码）**。`git 2.34.1`、`cmake 3.22.1` 已就绪；固定 SHA 源码已 clone 且工作树干净。ACM 正式版 PDF 仍缺失，但 arXiv v2 已获取。
  - **Gate 1：PASS**。离线缓存演示与 5 个单元测试全部通过，退出码均为 0。
  - **Gate 2：PASS_SMOKE_ONLY**。12k × 16d toy 编译并运行成功，退出码 0，采样 Recall = 1.0（GT 599），两次重复运行一致。隔离插桩副本进一步确认 6 大执行路径全部实际执行：120/120 非空桶、459 候选任务、Gorder 有效非恒等置换、cache 339 命中/120 缺失/0 淘汰、约 3.59e6 次距离计算。完整报告见 `workspace/GATE2_REPORT.md`。
  - **Gate 3：Audit Completion = PASS；Algorithm Correctness = PASS_WITHIN_TESTED_SCOPE**。独立 Oracle（纯 stdlib Python，naive+精确窗口交叉验证）给出 12k GT=3,594,000、ID0 ε 邻域=599；隔离插桩 pair 输出与 GT **逐对一致**（recall=precision=1.0，FP=FN=重复=非法=0，3k/12k 均如此）；执行不变量（`target_tasks[0]==target_cluster` 等）成立；Cache 经独立 DP 最优确认正确。发现 1 处已核实论文–源码 MISMATCH（`add2choice` 2-choice 负载均衡 vs 论文“最近中心”）、1 处评估口径 MISMATCH（`%100000` 采样 vs 论文全量 recall），以及 `aligned_alloc`/`delete[]`（ASan 复现）等 Bug/Risk。完整报告见 `workspace/GATE3_REPORT.md`。
  - **Gate 4A：PASS（Workload Qualification + 机制激活）**。3 个 pilot（P1/P3 过密度筛、P2 记为负样本）+ W1H/W2H 独立种子 holdout 全 PASS；全量 Oracle 协议下 precision=1.0、recall 63.9–90.7%；Gorder 窗口（window=4<120，116 次滑动）与缓存逐出（容量 62<120）机制激活且 pair 集合/构建产物可证预算不变；G3-03 在隔离副本修复（修复前 ASan 证据保留，修复后输出字节级不变）；OMP>1 非确定性根因定位（并行 HNSW 中心图构建），受控比较一律 OMP=1。详见 §11 与 `GATE4A_REPORT.md`。
  - **Gate 4B-0：PASS（消融前置方法学审计）**。FN 六类互斥归因逐对总量相等（类6=0；P3 的 17+15 覆盖型 FN 全部量化为 ε² float32/double 边界 tie）；eb 0.1→1.0 增量 FN 100% 落被剪桶边；四 cache 模型同口径决策级校准（172 vs 174 / 164 vs 165 沿分岔链完全解释、C++ 复刻 0 失配、8 小前缀精确 DP）；顺序消融公平性证明（任务多重集/pair 集合跨序恒等）；观察：identity 在 P3 少 30 miss。详见 §12 与 `GATE4B0_REPORT.md`。
  - **Gate 4B-1：PASS（受控机制消融，验证级别 `mechanism_ablation`）**。§12.4 预注册 36 组主矩阵 + 12 独立种子 + 8 holdout + 36 计时运行全部 rc=0（容量 62/window=4/OMP=1/冻结桶化）；pair 集合/任务图/dist_comp 跨 order×policy 恒等、全 FP=0；**P1 gorder(172)<identity(195)<random(246)，但 P3 identity(134)<gorder(164)<random(204)**（W2H holdout 复现 149 vs 171；LRU 栈距离核算精确到个位）——Gorder 非全局最优；LRU 替换惩罚 +65.5%~+104.0%；剪枝 eb0.1→1.0 省 3.3–5.4% 计算、recall −0.80/−1.15pp；发现并修复上游 `sift_down` 越界读（默认路径字节级不变）；计时亚秒级仅记录、设备层 I/O UNVERIFIED。详见 §13 与 `GATE4B1_REPORT.md`。


> 本报告区分：[论文] 论文文字主张；[源码已检查] 本次直接读取源码；[实验观察] 本次命令输出；[推断] 尚未运行验证的解释。

---

## 1. 环境与依赖检查结果

### 1.1 主机

| 项目 | 观察值 |
|---|---|
| 操作系统 | Ubuntu 22.04.5 LTS (Jammy) |
| 内核 | Linux 6.8.0-40-generic |
| 架构 | x86_64 |
| CPU | Intel(R) Xeon(R) Silver 4310 CPU @ 2.10GHz |
| 逻辑 CPU | 24（12 核 × 2 线程） |
| 内存 | 62 GiB total，约 58 GiB available |
| 根文件系统 | `/dev/sda2`，ext4，879 G，已用 18 G，可用 817 G（3%） |
| CPU flags | `avx2` present，`fma` present |
| 项目根目录 | `/home/qch/DiskJoin/diskjoin_repro_pack` |
| 项目根 Git 状态 | 不是 Git 仓库（无 `.git`） |
| 参考仓库 Git 状态 | `reference/DiskJoin` 已 clone；HEAD 为固定 SHA；`git status --short` 为空 |

### 1.2 工具链

| 工具 | 结果 | 证据 |
|---|---|---|
| `git` | OK | `/usr/bin/git`，2.34.1；用户完成补充后实测 |
| `g++` | OK | Ubuntu 11.4.0-1ubuntu1~22.04.3，`/usr/bin/g++` |
| `cmake` | OK | `/usr/bin/cmake`，3.22.1；用户完成补充后实测 |
| `python3` | OK | 3.10.12，`/usr/bin/python3` |
| `curl` | OK | `/usr/bin/curl` |
| OpenMP | OK | `g++ -fopenmp -dM -E` 给出 `_OPENMP 201511`；CMake 找到 OpenMP 4.5 |
| `pdfinfo` / `pdftotext` | OK | 用于论文页数与文本抽取 |

注意：`scripts/check_env.sh` 只打印工具是否存在，不以缺失工具作为非零退出条件；本次重新运行已显示 `git`/`cmake` 均 OK。

### 1.3 最小编译/文件系统探针

在 `/tmp/opencode/diskjoin_env` 做了不涉及参考仓库的极小探针：

| 探针 | 退出码 | 结果 |
|---|---|---|
| `#include <filesystem>` + `g++ -std=c++11` | 0 | g++ 11 下可编译（未使用 `std::filesystem`） |
| `aligned_alloc` + `<omp.h>` + `-fopenmp` | 0 | 可用 |
| `<immintrin.h>` + `-mavx2 -mfma -march=native` | 0 | 可用 |
| ext4 上 `dd ... oflag=direct` 写 4096 B | 0 | O_DIRECT 写可用 |
| ext4 上 `dd ... iflag=direct` 读 4096 B | 0 | O_DIRECT 读可用 |

这些只证明工具链/文件系统的基本能力，**不证明参考 C++ 工程可编译或可运行**。

---

## 2. 参考仓库与论文来源

### 2.1 参考源码

- 上游：`https://github.com/iidyc/DiskJoin`
- 固定提交：`aa86151f97527b1dcf9a032d523c1d67d892454a`
- 提交时间（GitHub API）：`2025-06-08T01:27:54Z`
- 提交信息：`fix anonymous github issue caused by file names`
- Git tree SHA：`3042889c3dfd6b797a3516557c4ebace9c87fe3c`

Gate 0–1 阶段本机没有 `git`，当时用 `curl` 下载了固定提交的 GitHub tarball 完成源码审计；用户补充 `git`/`cmake` 后，已按既定脚本执行 `bash scripts/fetch_sources.sh`，创建了 `reference/DiskJoin` Git 克隆并检出固定 SHA。两条来源均已保留，可交叉核对：

- Git 克隆：`reference/DiskJoin`；`git rev-parse HEAD` = `aa86151f97527b1dcf9a032d523c1d67d892454a`；`git status --short` 为空
- 固定提交 tarball：

- 下载 URL：`https://codeload.github.com/iidyc/DiskJoin/tar.gz/aa86151f97527b1dcf9a032d523c1d67d892454a`
- 本地文件：`workspace/source_snapshot/DiskJoin-aa86151f97527b1dcf9a032d523c1d67d892454a.tar.gz`
- tarball SHA-256：`cac4c08ccd37caf4e46a6326a1c45ad84550ee087047100373fc56667d43bb58`
- 解压目录：`workspace/source_snapshot/DiskJoin-aa86151f97527b1dcf9a032d523c1d67d892454a/`
- 来源记录：`workspace/source_snapshot/provenance.json`

**内容完整性核验**：通过 GitHub `git/trees/<tree_sha>?recursive=1` 获取远端 42 个 blob 的 Git blob SHA-1，并对本地 42 个文件逐一计算 Git blob SHA-1：

- remote blob count：42
- local blob count：42
- missing：`[]`
- extra：`[]`
- mismatch：`[]`
- `tree_matches_commit: true`

因此可以确认：**本地 tarball 内容与固定提交的 Git tree 一致**。此外，`reference/DiskJoin` 的真实 Git 克隆也已验证 HEAD 与 clean 状态，两个来源互相印证。

### 2.2 论文

- 目标正式版：PACMMOD 3(6), Article 315, Dec. 2025（SIGMOD 2026），DOI `10.1145/3769780`
- 本次已获取：arXiv **v2**，`https://arxiv.org/pdf/2508.18494v2`
- 本地文件：`paper/DiskJoin_arXiv_2508.18494v2.pdf`
- 文件大小：3,077,125 bytes
- SHA-256：`95f256b9b01cc600e76698cafe553b4bc4394ba340fc6a36b258abbd3cdcea05`
- `pdfinfo`：15 页；Title 为 *DiskJoin: Large-scale Vector Similarity Join with SSD*；作者 Yanqi Chen, Xiao Yan, Alexandra Meliou, Eric Lo；CreationDate 2025-10-13
- 文本抽取：`workspace/paper_text/DiskJoin_arXiv_2508.18494v2.txt`；首页含 `arXiv:2508.18494v2 [cs.DB] 10 Oct 2025`

**正式版状态**：`paper/DiskJoin_PACMMOD_2025_formal.pdf` 不存在。未尝试绕过访问控制获取 ACM 正式版，也未把 arXiv v2 冒充正式版。两者必须继续分开记录。

---

## 3. DiskJoin 核心算法理解

### 3.1 端到端流程

```
.fbin (n × d float32)
  └─ 1. Bucketization (Kmeans.h / ClusterIO.h)
       → cluster_file（按 bucket 连续存放的向量）
       → metadata_file（bucket_sizes, centroids, radii, assignment）
       → hnsw_file（bucket centers 的 HNSW 索引）
  └─ 2. Bucket Graph 构造 (DiskJoin.h::search 前半)
       → tasks[i]：target bucket i 需要检查的候选 bucket 列表
  └─ 3. Gorder 重排 (Gorder.h::order_gorder)
       → rank/perm：新的 bucket 处理顺序
  └─ 4. Belady Cache (Cache.h::Cache)
       → 固定访问序列下的 future-use 淘汰
  └─ 5. Similarity Join 执行 (DiskJoin.h::search 后半 + ClusterIO.h)
       → 桶内自连接 + 跨桶距离验证
       → 采样 Recall = count / config.gt
```

### 3.2 模块映射（均为本次直接读取源码）

源码根目录：`workspace/source_snapshot/DiskJoin-aa86151f97527b1dcf9a032d523c1d67d892454a/`。

| 模块 | 输入 | 输出/作用 | 核心机制 | 源码位置 | 状态 |
|---|---|---|---|---|---|
| Config 解析 | 10 行“字段名 + 值”配置 | `data_file, radius, cluster_num, cluster_file, metadata_file, hnsw_file, K, mem_budget, error_bound, gt` | 固定顺序交替读取 token，不支持注释/复杂格式 | `lib/ConfigReader.h:22-35` | [源码已检查] |
| 数据读取 | `.fbin`：8 字节 header `n,d`，随后行主序 float32 | 批量向量 | `DataReader` 用 `ifstream` 顺序读 | `lib/DataReader.h:17-36` | [源码已检查] |
| 分桶 | `.fbin` + `cluster_num` + `mem_budget` | `cluster_file`, `metadata_file`, `hnsw_file` | 随机采样中心（seed 283）→ 在中心上建 HNSW → 每个向量取近邻中心做 2-choice 负载均衡分配 → 按 bucket 连续写盘并计算半径 | `lib/Kmeans.h:165-219`；`lib/Kmeans.h:127-146`；`lib/ClusterIO.h:43-114` | [源码已检查] |
| Bucket Graph | 中心 HNSW + `K` + `error_bound` | `tasks[i]` 候选 bucket 列表 | 对每个 bucket center 做 HNSW KNN → 距离升序 → 从最远开始累加 `arccos(d/(2ε))`，达到 `error_bound` 后截断 → 保留 `i <= neighbor` 的上三角任务 | `lib/DiskJoin.h:46-77`；`lib/hnswlib/hnswalg.h:454-540` | [源码已检查] |
| Gorder | `tasks`、滑动窗口 `w` | 新顺序 `rank/perm` | 以出度为初始 key；加入新节点时给其“父节点的兄弟”加 key，移出旧节点时减 key；每次取最大 key | `lib/Gorder.h:60-102`；`lib/Gorder.h:9-58`；`lib/Unitheap.h` | [源码已检查，未运行] |
| Belady Cache | `reordered_tasks` 形成的访问序列、`mem_budget`、bucket 长度 | 缓存 bucket 数据；miss 时读盘 | 预先建立每个 bucket 的未来访问位置表；最大堆按“下一次访问最晚”淘汰 | `lib/Cache.h:7-72`；`lib/Cache.h:132-176` | [源码已检查，未运行] |
| LRU（对照） | 固定访问序列 | 模拟 LRU | 存在 `LRUCache` 与 `simulate_cache_LRU`，但主执行路径未使用 | `lib/Cache.h:74-130`；`lib/Cache.h:178-212` | [源码已检查] |
| 执行/验证 | `tasks`, `order`, cache, cluster 文件 | 距离计算、采样 recall | 按重排顺序遍历 target bucket；加载其候选 bucket；桶内自连接 + 跨桶 L2² 比较；命中阈值时按 ID 采样计数 | `lib/DiskJoin.h:101-157` | [源码已检查，未运行] |
| O_DIRECT 读 | `cluster_file` | bucket 数据 | `open(O_RDONLY|O_DIRECT)`；按 4096 对齐读取；`memcpy` 到调用者缓冲 | `lib/ClusterIO.h:147-208` | [源码已检查，未运行] |
| 输出解析 | 参考程序 stdout | `summary.json` | 正则提取 `recall`、`Build done`、`Join done` | `scripts/parse_run.py` | [源码已检查] |

### 3.3 关键机制说明

**Bucketization。** `one_level_kmeans` 并不运行完整的迭代 k-means；它先随机选 `cluster_num` 个样本作为中心，在中心上建 HNSW（构造参数 `20, 100`），然后对每个输入向量 `searchBaseLayerST` 取最近的 2 个中心，用“更近中心 vs 更小 bucket”的 2-choice 规则决定归属。`ClusterWriter` 为每个 bucket 维护内存缓冲，按 `mem_budget` 分块顺序写盘，同时计算 `max distance to centroid` 作为 `radii`。详见 `lib/Kmeans.h:165-219`、`lib/ClusterIO.h:43-99`。

**Bucket Graph。** 代码对每个 bucket `i` 调 `graph->knnSearchBaseLayer(i, K)`。该函数返回的是**欧氏距离**（内部对 `fstdistfunc_` 取了 `sqrt`），不是平方距离；因此 `DiskJoin.h` 中 `temp = distance / 2` 后 `acos(temp / epsilon)` 是无量纲的几何角。`dis_to_boundary` 按距离升序；从最远候选开始累加角度，达到 `config.error_bound` 时停止，保留从最近到截断点的候选。`error_bound` 在配置中对应论文的 `1 - λ`（论文默认目标 recall 0.9 → 0.1）。详见 `lib/DiskJoin.h:46-77`、`lib/hnswlib/hnswalg.h:454-540`。

**Gorder。** `order_gorder` 返回的是 **rank permutation**：`rank[old_id] = new_position`。`DiskJoin.h` 用 `reordered_tasks[perm[i]] = shuffled_tasks[i]`、`order[perm[i]] = i` 将其转换为执行顺序。滑动窗口参数为：

```cpp
budget / 4 / length / config.K * 2
```

其中 `length = cluster_reader.max_points * d`。详见 `lib/DiskJoin.h:94-100`、`lib/Gorder.h:60-102`。

**Belady。** `Cache::init` 遍历 `reordered_tasks`，为每个 bucket 建立“第 k 次访问在全局访问序列中的位置”列表，并在末尾追加 `max`。`Cache::find` 命中时更新该 bucket 的下一次访问位置；`Cache::push` 在缓存满时比较堆顶（最晚再访问）与当前 bucket 的下一次访问位置，淘汰堆顶。`priority` 是最大堆。详见 `lib/Cache.h:30-67`。

**执行。** 对每个 target bucket，代码先按 `target_tasks` 顺序把候选 bucket 逐个 `cache.find` / `posixDirectReadCluster` / `cache.push` 到 `data` 的 `j` 号槽位，然后：

- 桶内自连接：`data.data() + j*d` 与同桶其他向量比较；
- 跨桶：`k = 1 .. target_tasks.size()-1`，与 `data.data() + k*length` 中的向量比较；
- 距离为平方 L2，与 `epsilon*epsilon` 比较，其中 `epsilon = sqrt(config.radius)`；
- 命中时只对 `id % 100000 == 0` 的端点计数，最后输出 `count / config.gt`。详见 `lib/DiskJoin.h:112-157`。

### 3.4 与论文表述的差异/待审计点

以下不是“已证明的错误”，而是**直接读代码后发现的、Gate 3 应逐条核对的差异**：

1. **论文 Eq.(1) 的三角不等式候选过滤在图中没有直接出现。** 代码构造图时使用的是 HNSW KNN + 角度和概率截断；`radii` 虽被写入 metadata 并在 `search` 中赋给 `graph->radii`，但 `knnSearchBaseLayer` 不使用 `radii`。`rangeSearchBaseLayer`（使用 `prune` 和 `radii`）存在但未被调用。  
   [源码已检查] `lib/DiskJoin.h:46-77`、`lib/hnswlib/hnswalg.h:392-450`、`lib/hnswlib/hnswalg.h:454-540`。

2. **执行不是严格“每次只处理一条边、只加载两个 bucket”。** 代码把一个 target bucket 的所有候选 bucket 一次性加载到 `data` 的 `max_task_num` 个槽位，再统一做自连接和跨桶比较；cache 仍在每个 bucket 上工作，但 `data` 是额外的批处理缓冲。  
   [源码已检查] `lib/DiskJoin.h:101-121`。

3. **自连接隐含假设 `target_tasks[0] == target_cluster`。** 自连接使用 `data.data() + j*d`，即 0 号槽位；如果 HNSW 没有把自身放在候选首位，自连接会读错 bucket，且 `k=1` 会跳过 0 号候选。当前 HNSW 实现会以距离 0 加入自身，且任务只保留 `i <= neighbor`，所以正常情况下该不变量成立，但代码没有断言。  
   [源码已检查] `lib/DiskJoin.h:64-68`、`lib/DiskJoin.h:112-146`、`lib/hnswlib/hnswalg.h:463-467`。

4. **Recall 是采样口径，不是全量 Join Recall。** 仅统计至少一个端点 ID 能被 100000 整除的相似对。12k toy 中只有 ID 0 被采样；`toy_metadata.json` 记录 `sample_ids: [0]`、`gt_sampled: 599`。若两个端点都被采样，代码会分别 +1，可能重复计数；12k 数据不会触发，但更大数据会。  
   [源码已检查] `lib/DiskJoin.h:134-156`；[实验观察] `workspace/toy/toy_metadata.json`。

5. **论文 Algorithm 2 是“窗口内邻居重叠”贪心；代码是 Gorder 风格的增量 key 维护。** `move_window` 中部分 `heap.lazyIncrement(parent, ...)` 被注释掉，实际更新的是“父节点的兄弟”。这与论文的精确 score 不完全同构，需要 Gate 3 逐行核对。  
   [源码已检查] `lib/Gorder.h:9-58`、`lib/Gorder.h:60-102`；[论文] Algorithm 2。

6. **`error_bound` 的命名与论文 `1 - λ` 对应，但配置中没有显式 `λ`。** toy config 使用 `error_bound = 0.1`，对应目标 recall 0.9 的语义；`gt` 是采样 GT，不是目标 recall。  
   [源码已检查] `lib/DiskJoin.h:58-63`；[实验观察] `workspace/toy/toy.config`。

### 3.5 离线 micro demo 的定位

`scripts/micro_task_cache.py` 是一个**教学模型**：

- 4 个 bucket：A, B, C, D；3 个 pair 任务；
- 缓存容量 2；
- 访问序列由任务展开；
- 比较 Belady 与 LRU。

它验证的是“任务顺序会影响缓存 miss”这一直觉，**不是**官方 C++ `order_gorder` 的输出，也不是官方 `Cache` 的复现。报告中的 5→4 只能作为机制直觉证据。

---

## 4. 实际执行的命令、退出码与测试结果

所有日志在 `workspace/logs/`。

| # | 命令 | 退出码 | 关键结果 |
|---|---|---|---|
| 1 | `bash scripts/check_env.sh`（Gate 0–1 初次） | **0** | Linux 6.8.0-40；x86_64；`git` MISS；`g++` OK；`cmake` MISS；`python3`/`curl` OK；内存 62 GiB；根盘 817 G 可用；AVX2/FMA present |
| 1b | `bash scripts/check_env.sh`（补充后） | **0** | `git` OK `/usr/bin/git`；`cmake` OK `/usr/bin/cmake`；其余同上 |
| 2 | `python3 scripts/micro_task_cache.py` | **0** | `original_belady cache_misses=5 hits=1`；`original_lru=6`；`reordered_belady=4`；`reordered_lru=4` |
| 3 | `python3 -m unittest discover -s tests -v` | **0** | 5/5 tests OK（4 个 cache 测试 + 1 个 toy 数据生成/配置测试） |
| 4 | `bash scripts/self_test.sh` | **0** | 重跑 5/5 tests；micro 输出同上；`Toy data checked: n=12000, d=16, sampled_gt=599` |
| 5 | `python3 scripts/validate_toy.py` | **0** | `n=12000, d=16, sampled_gt=599`；fbin 大小 768,008 B；config 10 个字段 |
| 6 | `bash -n scripts/check_env.sh scripts/fetch_sources.sh scripts/run_smoke.sh scripts/self_test.sh` | **0** | shell 语法通过 |
| 7 | `sha256sum -c SHA256SUMS` | **0** | 22/22 原始包文件 OK；未修改既有文件 |
| 8 | `curl ... arxiv.org/pdf/2508.18494v2` | **0** | 3,077,125 B，15 页 PDF，SHA-256 见 §2.2 |
| 9 | `curl ... codeload.github.com/.../tar.gz/aa861...` | **0** | 41,418 B tarball，SHA-256 见 §2.1 |
| 10 | GitHub API + 本地 Git blob SHA-1 对比 | **0** | 42/42 blob 匹配，`tree_matches_commit: true` |
| 11 | `dd` O_DIRECT 写/读探针（ext4） | **0**/0 | O_DIRECT 基本可用 |
| 12 | `bash scripts/fetch_sources.sh` | **0** | `REFERENCE VERIFIED: aa86151f...`；`PAPER VERIFIED`；创建 `reference/DiskJoin` |
| 13 | `git -C reference/DiskJoin rev-parse HEAD` | **0** | `aa86151f97527b1dcf9a032d523c1d67d892454a` |
| 14 | `git -C reference/DiskJoin status --short` | **0** | 输出为空，参考工作树 clean |
| 15 | `OMP_NUM_THREADS=4 BUILD_JOBS=4 bash scripts/run_smoke.sh` | **0** | CMake 配置/编译成功；toy 运行成功；`recall = 1`；`summary.json` 为 `PASS_SMOKE_ONLY` |
| 16 | 重复运行相同 smoke 命令 | **0** | 第二次仍为 `recall = 1`；build 0.0558 s，join 累计 0.0965 s |

### 4.1 Gate 1 原始输出

```text
original_belady    cache_misses=5 hits=1
original_lru       cache_misses=6 hits=0
reordered_belady   cache_misses=4 hits=2
reordered_lru      cache_misses=4 hits=2
```

```text
test_bad_capacity (test_micro.CacheTests) ... ok
test_belady_no_worse_than_lru_in_this_example (test_micro.CacheTests) ... ok
test_original_belady_five_misses (test_micro.CacheTests) ... ok
test_reordered_belady_four_misses (test_micro.CacheTests) ... ok
test_generation_and_config (test_toy.DataTests) ... ok

----------------------------------------------------------------------
Ran 5 tests in 0.250s

OK
```

### 4.2 生成数据

| 项目 | 值 |
|---|---|
| `workspace/toy/toy.fbin` | 12,000 × 16 float32 + 8 B header = 768,008 B |
| `epsilon` | 0.25 |
| `radius` | 0.0625（即 ε²） |
| `cluster_num` | 120 |
| `K` | 24 |
| `mem_budget` | 0.1 GiB |
| `error_bound` | 0.1 |
| 采样 GT | 599（仅 ID 0 参与采样） |
| 种子 | 283 |

### 4.3 Gate 2 实际结果

```text
Toy data checked: n=12000, d=16, sampled_gt=599
-- Found OpenMP: TRUE (found version "4.5")
-- Configuring done
-- Generating done
[ 50%] Building CXX object CMakeFiles/main.dir/expr/main.cpp.o
[100%] Linking CXX executable main
[100%] Built target main
Run folder: workspace/runs/toy-jw4eXS
[0.0560715 s] Build done
recall = 1
[0.0836922 s] Join done
```

第一次 run 目录：`workspace/runs/toy-jw4eXS/`

| 文件 | 大小/内容 |
|---|---|
| `stdout.log` | 60 B；含 `Build done`、`recall = 1`、`Join done` |
| `stderr.log` | 0 B |
| `config.snapshot` | 452 B |
| `reference_commit.txt` | `aa86151f97527b1dcf9a032d523c1d67d892454a` |
| `summary.json` | `status: PASS_SMOKE_ONLY`；`sampled_recall: 1.0`；`sampled_gt: 599`；build 0.0560715 s；join 累计 0.0836922 s |

第二次重复运行：`workspace/runs/toy-65b1dv/`，退出码 0，`recall = 1`，build 0.0557985 s，join 累计 0.0964714 s。两次采样 Recall 一致。

生成的参考产物：

- `workspace/toy/toy.clusters`（约 750 KiB）
- `workspace/toy/toy.metadata`（约 103 KiB）
- `workspace/toy/toy.hnsw`（约 29 KiB）

**解释边界**：Recall = 1.0 只表示在该 toy 的参考采样口径（仅 ID 0 参与）下，599 个采样 GT 对全部被找到；它**不是**全量 Join Recall，也不能证明论文级精度或性能。

### 4.4 仍未执行的命令

- 上游 `scripts/run.sh`、`scripts/create_datasets.sh`：按约束未执行。
- 10M/100M 数据生成、下载、实验：未执行。
- Gorder-off / Belady vs LRU / Pruning-off 消融：未执行（Gate 4 需要单独授权）。
- 正式 ACM PDF 获取与逐节对照：未执行。

---

## 5. 当前阻塞和潜在代码风险

### 5.1 阻塞项

已解决：

1. **`git` 缺失** → 用户已补充 `git 2.34.1`，`fetch_sources.sh` 成功。
2. **`cmake` 缺失** → 用户已补充 `cmake 3.22.1`，CMake 配置/编译成功。
3. **`reference/DiskJoin/` 不存在** → 已创建真实 Git 克隆，HEAD 为固定 SHA，工作树 clean。

仍未解决/仅部分满足：

4. **ACM 正式版 PDF 不存在**：当前只有 arXiv v2；正式版 27 页与 arXiv 15 页不能混同。这不阻塞 Gate 2，但阻塞论文级对照。
5. 未执行 `sudo`/`apt`/`pip install`；本次依赖补充由用户完成。

### 5.2 直接读代码发现的风险（按严重度）

**R1 — `aligned_alloc` 与 `delete[]` 不匹配（潜在 UB）。**  
`ClusterReader::readMetaData` 用 `aligned_alloc(PAGE_SIZE, ...)` 分配 `buffer`，析构函数却用 `delete[] buffer`。这在标准上是未定义行为，可能在退出时崩溃或只在某些 allocator 下暴露。  
证据：[源码已检查] `lib/ClusterIO.h:183`、`lib/ClusterIO.h:203-208`。

**R2 — O_DIRECT 读返回值未检查。**  
`lseek` 与 `read` 的返回值都没有检查；`read` 短读/失败时仍会 `memcpy`，可能把未初始化或旧数据当作 bucket 数据。  
证据：[源码已检查] `lib/ClusterIO.h:191-201`。

**R3 — 自连接依赖隐式不变量。**  
`target_tasks[0]` 被当作 `target_cluster` 本身；代码没有断言。若 HNSW 候选顺序变化或 K/中心重复导致自身不在首位，自连接会读错 bucket，跨桶循环还会跳过 0 号候选。  
证据：[源码已检查] `lib/DiskJoin.h:112-146`。

**R4 — `exit(0)` 静默终止。**  
当某个 bucket 的 `tasks[i]` 为空且候选距离非零时，`search` 内部直接 `exit(0)`。这会让进程以 0 退出但没有 `recall` 行，`run_smoke.sh` 只检查进程退出码时会误以为成功，直到 `parse_run.py` 报 “no recall”。  
证据：[源码已检查] `lib/DiskJoin.h:70-74`；`scripts/parse_run.py:16-17`。

**R5 — 采样 Recall 口径。**  
`count / config.gt` 只统计 `id % 100000 == 0` 的端点；12k toy 只有 ID 0。若两个端点都可被 100000 整除，会分别 +1，可能重复计数。不能把该数值当作全量 Join Recall，更不能当作 Precision。  
证据：[源码已检查] `lib/DiskJoin.h:134-156`；[实验观察] `workspace/toy/toy_metadata.json`。

**R6 — 指标/日志不足。**  
`io_size`、`sum`、`disk_time`、`comp_time`、`dist_comp` 等变量存在但未输出；cache 的 `hit/total` 也未打印。`parse_run.py` 只解析 recall 与两个累计时间，不验证 `n/d`、config、cache 命中率或实际读盘量。  
证据：[源码已检查] `lib/DiskJoin.h:103-111`、`lib/Cache.h:13-19`；`scripts/parse_run.py`。

**R7 — CMake/编译器兼容性风险（Gate 2 部分实测）。**  
`CMakeLists.txt` 使用 `cmake_minimum_required(VERSION 2.8)`、`OPENMP_FOUND`、`add_definitions(... -lboost ...)`、C++11 与 `std::random_shuffle`。本次用 **cmake 3.22.1 + g++ 11.4.0** 实测：配置、编译、链接均成功；只出现 CMake 2.8 兼容性 deprecation warning，`-lboost` 未导致失败。现代 CMake 4.x 仍可能拒绝 2.8 最低版本，未实测。  
证据：[实验观察] `workspace/logs/gate2_run_smoke_console.log`；[源码已检查] `CMakeLists.txt:1-25`、`lib/Kmeans.h:176`。

**R8 — 依赖声明与实际使用不一致。**  
上游 README 要求 `libboost-dev`、`libgoogle-perftools-dev`，但源码 grep 未发现 boost/tcmalloc 使用；`CMakeLists.txt` 的 `-lboost` 仍是潜在链接风险。  
证据：[源码已检查] `README.md:7`、`CMakeLists.txt`；grep 未命中 boost/tcmalloc 头文件。

**R9 — toy 规模下 cache/Gorder 机制基本不被激活。**  
- 12k × 16d 数据约 768 KB；`mem_budget = 0.1 GiB`，`Cache::size = budget/4/length` 远大于 120 个 bucket，所有 bucket 都能常驻缓存，不会发生淘汰。
- Gorder 窗口 `budget/4/length/K*2` 在 toy 上很可能大于 `cluster_num=120`，`move_window` 不会移出旧节点，滑动窗口退化。
- 因此 **Gate 2 toy smoke 只能验证执行通路，不能验证 Belady/Gorder 的收益**。Gate 2 已实际跑通，但程序未打印 cache hit/miss，无法从日志确认是否发生淘汰；上述容量判断仍属基于源码公式的推断。  
证据：[推断，基于源码公式与 toy 参数；Gate 2 已运行但未插桩]。

**R10 — `Cache` 容量为 0 的边界。**  
若 `budget / 4 / length` 为 0，`Cache::push` 会访问空堆的 `top()`，属于越界/UB。toy 与论文配置不会触发，但机制消融若故意压小内存需要注意。  
证据：[源码已检查] `lib/Cache.h:21-28`、`lib/Cache.h:54-66`。

**R11 — 批处理缓冲可能超出 cache 预算。**  
`std::vector<float> data(max_task_num * length)` 按“最大候选数 × 最大桶大小”分配，和 `Cache` 的 `budget` 是两笔内存；在极端 `max_points`/`K` 下可能显著。toy 无碍。  
证据：[源码已检查] `lib/DiskJoin.h:101`、`lib/DiskJoin.h:20`。

**R12 — 线程安全/并行正确性未审计。**  
`one_level_kmeans` 对 `graph.addPoint` 使用 `#pragma omp parallel for`；`search` 对 HNSW KNN 并行。HNSW 内部是否完全线程安全、是否存在共享 `visited_list_pool` 竞争，需要 Gate 2/3 实测与源码审计。  
证据：[源码已检查] `lib/Kmeans.h:197-200`、`lib/DiskJoin.h:46-48`；[未验证]。

### 5.3 论文/源码版本风险

- 参考仓库根目录没有 LICENSE；不能默认允许再分发。
- 公开仓库与 ACM 正式版的一致性未独立核对；仅凭代码相似或 smoke 通过不能宣称 “ACM artifact” 或 “paper-level reproduction”。
- arXiv v2 是 15 页预印本；正式版是 27 页 PACMMOD。两者的图表、实验细节可能不同。

---

## 6. Gate 判定

### Gate 0：**PASS（环境与源码）**

| 子项 | 结果 | 说明 |
|---|---|---|
| Linux | PASS | Ubuntu 22.04.5 / kernel 6.8 |
| x86_64 + AVX2/FMA | PASS | `/proc/cpuinfo` 与编译探针均通过 |
| g++ | PASS | 11.4.0 |
| CMake | PASS | 3.22.1；配置/编译成功 |
| Git | PASS | 2.34.1；固定 SHA clone 成功 |
| 磁盘/内存 | PASS | 817 G 可用 / 62 GiB |
| 参考源码 SHA | PASS | `git rev-parse HEAD` = 固定 SHA；`git status --short` 为空；tarball tree 42/42 匹配 |
| 论文可用性 | PARTIAL | arXiv v2 已获取；ACM 正式版仍缺失 |
| 网络 | PASS | GitHub / arXiv 可访问 |

结论：**Gate 0 环境与源码部分 PASS**。ACM 正式版 PDF 缺失仍是论文级对照的已知缺口，但不阻塞 Gate 2。

### Gate 1：**PASS**

| 子项 | 结果 | 说明 |
|---|---|---|
| `micro_task_cache.py` | PASS | exit 0；original Belady 5 → reordered Belady 4 |
| `unittest discover` | PASS | 5/5 OK，exit 0 |
| `self_test.sh` | PASS | exit 0；重复验证 |
| toy 数据生成/校验 | PASS | 12,000 × 16；GT 599；exit 0 |
| 包完整性 | PASS | `sha256sum -c` 22/22 OK |
| 机制解释边界 | 已标注 | micro demo 是教学模型，不是官方 Gorder/Cache 的精确复现 |

### Gate 2：**PASS_SMOKE_ONLY**

| 子项 | 结果 | 说明 |
|---|---|---|
| 参考源码 SHA | PASS | HEAD `aa86151f...`；工作树 clean |
| CMake 配置 | PASS | cmake 3.22.1；找到 OpenMP 4.5；仅有 2.8 deprecation warning |
| 编译/链接 | PASS | `[100%] Built target main`；生成 `workspace/build/main` |
| toy 数据 | PASS | 12,000 × 16 float32；fbin 768,008 B；GT 599 |
| 进程退出码 | PASS | 0 |
| Recall | PASS | `recall = 1`，有限且位于 `[0,1]` |
| 日志/快照 | PASS | `stdout.log`、`stderr.log`（0 B）、`config.snapshot`、`reference_commit.txt`、`summary.json` |
| 重复运行 | PASS | 第二次仍为 `recall = 1` |
| 机制收益 | **未验证** | toy cache 可容纳全部 bucket，且无 cache 统计插桩 |

结论：**参考 C++ 实现的基本执行通路可用**。该结果只能标记为 `PASS_SMOKE_ONLY`，不能解释为论文性能或完整 Recall 复现。

---

## 7. 下一轮 Gate 3（只读审计）建议

Gate 2 已完成，下一步是 **Gate 3：源码/论文对齐审计**，不跑新的 10M/100M 作业。

### 7.1 审计范围

只读以下文件，并保持 `reference/DiskJoin` 不变：

- `reference/DiskJoin/lib/DiskJoin.h`
- `reference/DiskJoin/lib/Gorder.h`
- `reference/DiskJoin/lib/Cache.h`
- `reference/DiskJoin/lib/Kmeans.h`
- `reference/DiskJoin/lib/ClusterIO.h`
- `reference/DiskJoin/lib/hnswlib/hnswalg.h`（只审计被 DiskJoin 调用的 KNN/prune 路径）
- `reference/DiskJoin/CMakeLists.txt`
- 论文 arXiv v2 的 §3–§5 与 §6.5 消融描述

### 7.2 必答问题

1. 论文 Eq.(1) 的三角不等式候选过滤是否在代码中实际生效？当前证据显示图构造使用 HNSW KNN + 角度概率截断，`rangeSearchBaseLayer` 未被调用。
2. Gorder 与论文 Algorithm 2 的 score/窗口是否同构？`move_window` 中注释掉的 `lazyIncrement` 对结果有何影响？
3. `Cache` 的 Belady 语义是否与论文 Algorithm 1 完全一致？`LRUCache` 是否可作为公平对照？
4. “每条边两个 bucket”与代码“一个 target bucket 批量加载全部候选”的差异，对 cache miss 和内存预算统计意味着什么？
5. 采样 Recall 的精确 GT 口径；n≥100000 时双端点均被采样是否会重复计数。
6. O_DIRECT 短读、`aligned_alloc`/`delete[]` 不匹配是否需要在隔离副本中修复。
7. 若做消融，最小必要 patch 是什么？如何保证不改 `reference/DiskJoin`？

### 7.3 建议的低风险验证

- 只做静态审计与已有日志复核；如需验证 cache 语义，可在 `workspace/` 下复制一份源码做小型插桩实验，**不要修改参考仓库**。
- 用独立 Python 模型复核 Belady/LRU 的 miss 计数，不依赖论文性能数据。
- 所有新实验继续使用 `OMP_NUM_THREADS=4`、`BUILD_JOBS=4`，并记录独立 run 目录。

### 7.4 Gate 3 停止条件

- 若源码与论文的关键机制无法对齐，先报告 mismatch，不进入 Gate 4。
- 若需要修改参考源码才能消融，必须使用隔离副本并生成 patch；不得直接改 `reference/DiskJoin`。
- Gate 4（Gorder-off、Belady vs LRU、Pruning-off）需要用户**单独明确授权**后才能开始。

### 7.5 本轮明确不建议做的事

- 不运行上游 `scripts/run.sh` 或 `scripts/create_datasets.sh`。
- 不下载/生成 10M/100M 数据。
- 不做 Gorder/Belady/Pruning 消融（Gate 4 需要单独授权）。
- 不把 `PASS_SMOKE_ONLY` 写成 `PAPER_REPRODUCED`。

---

## 8. 尚未验证的内容

以下仍为 **UNVERIFIED / 未充分验证**，不得在后续报告中写成已验证：

1. Gorder 的置换有效性已由插桩确认（dup=0，首 8 项 6,10,29,42,46,54,76,84，非恒等排序）；但窗口是否退化、重排是否改善缓存行为/miss 率仍未验证。
2. Belady 在 toy 上未发生任何淘汰（插桩观察 filled_slots=120 < capacity_slots=5429；339 命中/120 缺失）；但 `Cache::push` 的 Belady 替换分支（`lib/Cache.h:60-65`）本次未执行，其正确性与收益仍未验证。
3. `aligned_alloc`/`delete[]` 不匹配是否会导致实际崩溃（本次未崩溃，但 UB 仍存在）。
4. O_DIRECT `read` 短读/失败时的行为（本次 toy 跑通，但代码未检查返回值）。
5. 自连接是否始终读取正确 bucket（本次 recall=1 间接支持，但无断言）。
6. 参考仓库与 ACM 正式版论文的逐节一致性。
7. 正式版 PDF 的 27 页内容、图表与实验配置。
8. 论文报告的 50×–1000× 加速、全量 Recall、I/O 指标能否复现。
9. 10M/100M/SPACEV1B 数据上的任何行为。
10. Gorder-off、Belady vs LRU、Pruning-off 的消融结果。
11. 跨数据集/跨 join 扩展。
12. 上游代码 LICENSE 与再分发权限。
13. CMake 4.x 下的兼容性（本次仅测 cmake 3.22.1）。
14. 全量 Join 的精确 GT / Precision / Recall（本次只有采样口径）。
15. 参考程序原生的 trace/`--json` 级输出（参考代码不提供）；Gate 2 通过隔离副本插桩补齐了 cache hit/miss、读盘字节、距离计算次数的观察，但这属于外部插桩，不是参考程序原生能力。

---

## 9. Gate 2 详录：插桩验证与证据索引

本节为 `workspace/GATE2_REPORT.md` 的配套索引，记录仅靠 smoke 观察无法确认的模块执行路径证据。插桩方式：`workspace/instrumented/DiskJoin`（`git archive HEAD` 导出固定 SHA 内容后仅添加只读计数/打印），构建于 `workspace/build_instr`，补丁 `workspace/patches/gate2_instr.patch`（104 行，仅涉及 `lib/DiskJoin.h` 与 `lib/Kmeans.h`）。参考仓库全程未修改。

方法学要点：`cache.total/hit/filled/size` 与 `cluster_reader.total/used` 是参考代码原生态计数器（`lib/Cache.h:13-15,21-27,45,48`；`lib/ClusterIO.h:144-145,196-197`），插桩只是读取现成字段；未添加任何影响任务生成、排序、缓存决策或距离计算的代码。

插桩运行 stdout（run 目录 `workspace/runs/gate2-instr-run1/`，exit 0，stderr 0 B）：

```text
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

模块判定（对应任务要求表）：

| 模块 | 证据 | 判定 |
|---|---|---|
| Bucketization | 120/120 非空桶、12,000 全部分配、max 309 | PASS |
| Bucket Graph | 459 候选任务、empty_tasks=0 | PASS |
| Gorder | 置换 dup=0 且非恒等（首 8 项 6,10,29,…） | PASS |
| Belady Cache | init/find/push 均执行：339 命中/120 缺失/0 淘汰 | PASS（替换分支未执行） |
| Join Execution | dist_comp≈3.594e6、sampled_matches=599=gt | PASS |
| End-to-end | exit 0、Build/Join done、stderr 0 B | PASS |

资源统计（`/usr/bin/time -v`，两次直接运行，`OMP_NUM_THREADS=4`，`timeout 300`）：

| 项 | 参考（gate2-ref-run1） | 插桩（gate2-instr-run1） |
|---|---|---|
| wall | 0:00.08 | 0:00.09 |
| user / sys | 0.28 s / 0.01 s | 0.29 s / 0.03 s |
| CPU | 348% | 351% |
| Max RSS | 9,508 KB | 9,508 KB |
| Major faults | 0 | 0 |
| 退出码 | 0 | 0 |

既有含义确认：mock 配置下 cache 容量（5429 槽 ≈ mem_budget 字节）远大于 120 个桶，因此 0 次淘汰；Gorder 窗口（budget/4/length/K*2 ≈ 452）大于桶数，window 移出分支未触发。**因此本轮仍不能验证 Belady/Gorder 的机制收益**，只能在机制消融（Gate 4）中验证。

重复实验（幂等）：

```bash
cd /home/qch/DiskJoin/diskjoin_repro_pack
OMP_NUM_THREADS=4 BUILD_JOBS=4 bash scripts/run_smoke.sh                    # 参考链路（自动生成 run 目录）
cmake -S workspace/instrumented/DiskJoin -B workspace/build_instr && \
cmake --build workspace/build_instr -j 4                                    # 插桩链路
OMP_NUM_THREADS=4 timeout 300 ./workspace/build_instr/main workspace/toy/toy.config
git -C reference/DiskJoin status --short                                    # 应为空
```

已知语义疑点新增记录（供 Gate 3）：

- n ≥ 100000 时，若一对的两端点都是 100000 倍数，代码 `id1`/`id2` 各 `count++` 一次（`lib/DiskJoin.h:135-136,149-150`），同一对可能被计 2 次；GT 生成器必须同口径。12K toy 内只有 ID 0，无此问题。
- `dist_comp` 是 float 归约变量（`lib/DiskJoin.h:111,124`），打印计数为浮点近似。
- `ClusterWriter`（`lib/ClusterIO.h:43-99`）每桶写入缓冲按 `max_points` 布局、桶文件连续分页；`radii` 为 sqrt 后的真实半径（97），与 `radius=epsilon^2` 的 config 语义不同层，需在 Gate 3 里与论文符号逐一对照。

---

## 附录 A：本次新增/生成的文件

未修改任何既有文件；`sha256sum -c SHA256SUMS` 22/22 OK。

新增：

- `paper/DiskJoin_arXiv_2508.18494v2.pdf`（arXiv v2 原始 PDF，未改动）
- `workspace/logs/gate1_micro_task_cache.log`
- `workspace/logs/gate1_unittest.log`
- `workspace/logs/gate1_self_test.log`
- `workspace/paper_text/DiskJoin_arXiv_2508.18494v2.txt`（PDF 文本抽取，临时分析用）
- `workspace/source_snapshot/DiskJoin-aa86151f97527b1dcf9a032d523c1d67d892454a.tar.gz`
- `workspace/source_snapshot/DiskJoin-aa86151f97527b1dcf9a032d523c1d67d892454a/`（解压源码）
- `workspace/source_snapshot/provenance.json`
- `workspace/toy/toy.fbin`
- `workspace/toy/toy.config`
- `workspace/toy/toy_metadata.json`
- `workspace/toy/toy.clusters` / `toy.metadata` / `toy.hnsw`（Gate 2 生成）
- `workspace/build/`（Gate 2 out-of-tree 构建）
- `workspace/runs/toy-jw4eXS/`（Gate 2 第一次 run）
- `workspace/runs/toy-65b1dv/`（Gate 2 重复 run）
- `workspace/logs/gate2_run_smoke_console.log`
- `workspace/logs/gate2_run_smoke_repeat.log`
- `workspace/logs/gate0_fetch_sources.log`
- `workspace/GATE2_REPORT.md`（Gate 2 完整 13 章节报告）
- `workspace/instrumented/DiskJoin/`（隔离插桩副本；`git archive HEAD` 导出后仅加只读统计/打印）
- `workspace/build_instr/`（插桩副本 out-of-tree 构建）
- `workspace/patches/gate2_instr.patch`（104 行 diff，仅 `lib/DiskJoin.h` 与 `lib/Kmeans.h`）
- `workspace/runs/gate2-ref-run1/`（参考二进制 `/usr/bin/time -v` 运行：stdout/stderr/time.log）
- `workspace/runs/gate2-instr-run1/`（插桩二进制运行：stdout/stderr/time.log）
- `workspace/logs/instr/build_instr.log`
- `workspace/HANDOFF.md`

## 附录 B：一键复核命令

```bash
cd /home/qch/DiskJoin/diskjoin_repro_pack
bash scripts/check_env.sh
python3 scripts/micro_task_cache.py
python3 -m unittest discover -s tests -v
python3 scripts/validate_toy.py
sha256sum -c SHA256SUMS
git -C reference/DiskJoin rev-parse HEAD
git -C reference/DiskJoin status --short
```

若要复核 Gate 2（会重新编译/运行 12k toy，不下载数据）：

```bash
OMP_NUM_THREADS=4 BUILD_JOBS=4 bash scripts/run_smoke.sh
```

若要复核插桩验证（隔离副本，不修改 `reference/`）：

```bash
cmake -S workspace/instrumented/DiskJoin -B workspace/build_instr
cmake --build workspace/build_instr -j 4
OMP_NUM_THREADS=4 timeout 300 ./workspace/build_instr/main workspace/toy/toy.config
git -C reference/DiskJoin status --short   # 应为空
```

这些命令不会安装依赖、不会下载数据、不会运行 10M/100M 实验。

---

## 10. Gate 3 详录：正确性审计与论文–源码一致性（2026-11-02）

> 完整报告：`workspace/GATE3_REPORT.md`（12 章 + 两个独立判定）。以下为要点与证据索引，Gate 0–2 记录见前述章节，未删改。

### 10.0 两个独立判定

- **A. Audit Completion = `PASS`**（全部审计任务完成，证据充分）。
- **B. Algorithm Correctness = `PASS_WITHIN_TESTED_SCOPE`**（被测范围内输出与独立 Oracle 逐对一致）。
- **audit PASS ≠ correctness PASS**；correctness 结论限定在 3k/12k、20 类强分离、ε=0.25、正常参数范围。

### 10.1 隔离工作副本与插桩

- 参考仓库 `reference/DiskJoin` 全程未改（HEAD=`aa8615…454a`，`git status --short` 空，插桩前后复核）。
- 全新隔离副本 `workspace/gate3/instrumented/DiskJoin`（`git archive HEAD` 展开；插桩前与参考 `diff -r` 为 `IDENTICAL`）。
- 插桩补丁 `workspace/gate3/patches/gate3_instr.patch`（115 行，**仅 `lib/DiskJoin.h`**）：
  - `GATE3_PAIR_OUT`：命中对 `(min_id,max_id)` 输出；**每线程缓冲**避免 OpenMP 竞争；**不改变**候选/Gorder/Cache/剪枝/距离逻辑。
  - `GATE3_INVARIANTS`：只读运行期不变量与统计。
- out-of-tree 构建 `workspace/gate3/build/{main, main_asan, cache_test, cache_test_asan}`；数据 `workspace/gate3/data/`（不覆盖 `workspace/toy/`）。

### 10.2 Gate 3A — 执行不变量与数据流

运行期（`GATE3_INVARIANTS=1`）：

```
[gate3-inv] perm_ok=1 empty_tasks=0 head_mismatch=0 self_missing=0 upper_triangle_ok=1 task_total=459 bucket_sum=12000 n=12000   (12k)
[gate3-inv] perm_ok=1 empty_tasks=0 head_mismatch=0 self_missing=0 upper_triangle_ok=1 task_total=470 bucket_sum=3000  n=3000    (3k)
```

- `target_tasks[0]==target_cluster` 成立且 Gorder 重排后保持；self 恒在任务内；任务仅上三角；`order` 为有效置换。
- 独立 Python 解析 metadata/cluster/fbin（`oracle/audit_metadata.py`）：`sum(bucket_sizes)=n`、assignment 为置换、cluster 文件逐向量 bit 级一致、`radii=sqrt(max‖x−centroid‖²)` 一致。**唯一异常：120/120 个中心不在自身桶**（`add2choice` 负载均衡的后果，见 G3-01/G3-13）。
- 距离口径：`epsilon=sqrt(radius)`，比较 `dist_l2`（平方 L2）`< epsilon*epsilon` → 有效阈值=config.radius。论文用 `≤ε`，代码严格 `<`（仅边界差异，G3-06）。

### 10.3 Gate 3B — 独立 Oracle 与 Pairwise Recall

- Oracle `oracle/oracle_pairs.py`：naive O(n²) + 按坐标 0 必要条件滑窗（结果集相同），含手工边界用例与随机交叉验证，`SELFTEST PASS`。
- 12k GT = **3,594,000**（=20×C(600,2)）；ID 0 ε 邻域 = **599**（与 Gate 2 `gt=599` 独立吻合）。
- 规模级交叉验证：3k 全 naive GT=223,500 == 12k 窗口 GT 限制到 id<3000 的子集（逐对 `diff` 相同）。
- 全量对比（`oracle/compare_pairs.py`）：
  - 12k：found=3,594,000，TP=3,594,000，FP=FN=重复=非法=0，**recall=precision=1.0**；`dist_comp=3,594,000`（=GT，即无浪费比较）。
  - 3k：found=223,500，同样 recall=precision=1.0。
- 采样口径独立审查：`id%100000==0` 计数在 n<100000 退化为仅 ID 0（=599）；n≥100000 时两端点均被采样会对同一对**双计**；且与论文全量 `|R∩R'|/|R|` 口径不同。**采样 Recall 与全量 Pairwise Recall 已严格分开**。
- 近似边界诊断（非 Gate 4）：`error_bound=100` 时仅 self-join（120 任务），FN=2,796,651、FP=0、precision=1.0 → 剪枝**只漏不错**；`error_bound=0.9` 与 `0.1` 结果相同（远端角度截断为 0）。
- 可复现：同输入两次运行 pair 集合逐对一致。

### 10.4 Gate 3C — 论文–源码一致性（要点）

- **Bucketization**：中心=随机采样数据向量（固定种子 283）；分配=`add2choice` 2-choice 负载均衡，与论文“最近中心”**不一致**（G3-01）；半径定义一致；**K-means 迭代从未执行**（`Kmeans::train` 未被调用，G3-12）。
- **Bucket Graph / Pruning**：论文 §5.2 弃用 Eq.(1) 改 HNSW + Algorithm 3；代码主路径正是 HNSW 候选（top-K）+ Algorithm 3 角度剪枝，**结构一致**；Eq.(1) 风格过滤 `prune` 存在于 `rangeSearchBaseLayer` 但**是死代码**（G3-08）。剪枝参数化细节（`x=(dist/2)/ε`、`x>1→1`）与论文公式可能有别（G3-10，Potential）。
- **Gorder**：初始最大出度、贪心重叠、rank 映射方向均一致；兄弟增量与论文 O(Σd⁺²) 相符；**toy 上窗口 w≈452>n=120，窗口移除分支从未触发**（G3-11，影响 Gate 4 公平性）。
- **Belady**：Algorithm 1 与 `Cache.h` 一致，并**独立确认最优**——`oracle/cache_test.cpp` 与独立 DP 最优在 300 组随机序列×容量上 `ref==opt`；数据完整性（槽位映射/精确拷贝长度/无残留）通过；ASan/UBSan 干净。访问粒度为 |tasks|（论文为 2|E|）为建模差异（G3-10）。
- **其他**：`aligned_alloc`+`delete[]`（ASan 复现 UB，G3-03）；`read/lseek` 未检查（G3-04）；空任务 `exit(0)`（G3-05）；`dist_l2(vec1,centroid)` 死计算（G3-07）；`Cache::init` 的 id 契约（G3-09）。

### 10.5 Gate 3D 问题清单（摘要，完整表见报告 §7）

| ID | 类型 | 严重度 | 结论 |
|---|---|---|---|
| G3-01 | Mismatch（2-choice vs 最近中心） | Medium | Confirmed |
| G3-02 | Mismatch（采样 recall vs 全量 recall） | High（评估口径） | Confirmed |
| G3-03 | Bug（aligned_alloc/delete[]，UB） | Low–Medium | Confirmed |
| G3-04 | Risk（read/lseek 未检查） | Medium | Potential |
| G3-05 | Risk（空任务 exit(0)） | Low | Potential（实际不可达） |
| G3-06 | Mismatch（`<` vs `≤` 阈值） | Low | Confirmed |
| G3-07 | Risk（死计算） | Low | Confirmed |
| G3-08 | Mismatch/Note（Eq.(1) 过滤为死代码） | Low | Confirmed |
| G3-09 | Risk（Cache::init id 契约） | Low | Confirmed |
| G3-10 | Potential（剪枝/窗口/粒度参数化） | Low | Potential |
| G3-11 | Risk（Gorder 窗口未激活） | Medium（对 Gate 4） | Confirmed |
| G3-12 | Note（K-means 死代码） | Low | Confirmed |
| G3-13 | Note（中心非成员） | Low | Confirmed |
| G3-14 | Risk（并行构建可复现性） | Low | Potential |
| G3-15 | Risk（ConfigReader 无校验） | Low | Potential |

### 10.6 Gate 3 产物索引

- 报告：`workspace/GATE3_REPORT.md`
- Oracle/测试源码：`workspace/gate3/oracle/{oracle_pairs.py, compare_pairs.py, audit_metadata.py, cache_test.cpp}`
- 插桩补丁：`workspace/gate3/patches/gate3_instr.patch`
- 测试配置：`workspace/gate3/data/{toy12k.config, toy3k.config, toy12k_eb09.config, toy12k_eb100.config}`
- TP/FP/FN 与审计结果：`workspace/gate3/runs/{compare_12k.txt, compare_3k.txt, compare_12k_eb100.txt, metadata_audit_12k.json, oracle_id0.json, oracle_gt_12k_summary.json, oracle_gt_3000_naive.json}`
- Pair 输出与 GT：`workspace/gate3/runs/pairs_*.txt`、`workspace/gate3/runs/gt_toy_*.txt`
- 原始日志：`workspace/gate3/runs/std{out,err}_*.log`、`workspace/gate3/logs/*.log`

### 10.7 Gate 3 停止条件（已遵守）

完成上述审计与报告后**立即停止**，未进入 Gate 4 消融、未跑 10M/100M、未做论文级 Benchmark、未下载真实数据、未 sudo/安装、未改参考仓库、未 commit/push。

### 10.8 Gate 4 前置条件与建议（只提方案，不执行）

1. 统一评估口径为全量 GT/found（弃用 `%100000`，处理 G3-02）。
2. 激活 Gorder 窗口（调大 n 或显式设 w，处理 G3-11），在固定线程数下评估顺序收益（H1）。
3. 固定 access sequence 上比较 Belady vs LRU（H2）。
4. `error_bound` 合法范围内扫描，用 pair dump 给 pruning 的 FN 与 `dist_comp`/I/O（H3）。
5. 每个变体单独 patch 并记录；固定数据/ε/K/线程/内存预算；重复取稳定方向。
6. 消融前决定是否在隔离副本修 G3-03（改 `free`）以消除 UB 噪声；参考仓库保持只读。

---

## 11. Gate 4A 详录：Workload Qualification 与机制激活（2026-11-02）

> **对 §10 的勘误（amendment，原文保留不改）**：§10.4/§10.5 中 G3-13（"中心非成员"）及 G3-01 的证据描述有误——`workspace/gate3/oracle/audit_metadata.py` 的 check 6 存在自身 bug（`elif b not in ids` 把**桶下标**与**数据向量 ID** 两个 ID 空间混淆）。Gate 4A 用独立复查脚本（`workspace/gate4a/oracle/g3_01_investigate.py`，中心按 float32 字节精确匹配数据向量）证实：**120/120 中心都在自身桶内**（P1 与 toy12k 双重复核）。G3-01 的核心结论（`add2choice` 2-choice 分配 vs 论文 "nearest center" 的不一致）**维持 Confirmed**，但幅度修正为：抽样中 15.2%（P1）/16.2%（toy12k）的向量被分到次近中心。详见 `GATE4A_REPORT.md` §10。

### 11.1 范围与产物

- Gate 4A = 工作负载资格审定 + Gorder 窗口/Cache 驱逐**激活验证** + G3-03 修复回归 + G3-01 复查。**不含**性能消融（4B）。
- 全部产物在 `workspace/gate4a/`：`instrumented/DiskJoin`（本地 git 6 commit，工作树 clean）、`build/{prefix,postfix}_{normal,asan}`、`patches/{gate4a_instr(263行,f8d6f2e..HEAD,含G3-03修复), g3_03_fix(16行), gate3_instr_reapplied(116行)}`、`oracle/{gen_workload,qualify,g3_01_investigate,trace_policy_sim}.py + gorder_test.cpp`、`data/`（5 数据集 + meta JSON + 配置）、`runs/`、`logs/`。新增 ~79 MB，单次运行 <180 s，线程 ≤4。
- 插桩全部 env 门控 print-only：`GATE4A_STATS/GATE4A_TASK_OUT/GATE4A_CACHE_TRACE/GATE4A_KNN_OUT` + gate3 的 `GATE3_PAIR_OUT/GATE3_INVARIANTS`。

### 11.2 关键结果

1. **工作负载**（预登记筛选：密度∈[0.1%,20%]、dist_comp>TP、无效候选≥5% 等）：P1（W1 重叠, box0.15/σ0.08, radius0.2, seed283）PASS：GT=297,600（3.72%），OMP=1 recall 63.89%/precision 1.0；P2（box0.10/σ0.12, radius0.44）**FAIL 密度**（29.57%，如实留作否定样本）；P3（W2 Zipf 792..29 + 三档σ + 20% ε-边界向量, radius0.2）PASS：GT=68,029（0.85%），recall 86.95%/precision 1.0。独立种子 holdout（1283，单次不迭代）：W1H PASS（GT 294,556, recall 67.46%）、W2H PASS（GT 72,502, recall 90.68%）。全量 oracle 口径（复用 gate3 工具）。
2. **Gorder 窗口激活（G3-11 处置）**：mem_budget=0.0003/0.000255/0.0004（按 float32 精算）→ capacity=62 槽、window=4<120 → `window_removals=116`（W0/P1/P3 全部真实执行，大预算下为 0）。harness 16/16 PASS（真实 `order_gorder()`，removals=n−min(window,n) 精确成立、任务表逐字保留、确定性）。**任务多重集（按目标桶键控）跨 window 2026/1294 vs 4 完全相同**（P1 1484 边、P3 1685 边）→ 窗口只改顺序不改集合。
3. **Cache 驱逐激活（Gate 2 遗留处置）**：capacity=62<120 → W0 evict48/reject10、P1 evict92/reject18、P3 evict67/reject35（大预算全 0）。**pair 集合跨预算不变**（223,500/190,149/59,151 排序 cmp 全等）；clusters/metadata/hnsw 跨预算**字节级相同**（OMP=1 基线）；metadata 审计 PASS（check 6 输出为已知脚本 bug，见勘误）；ASan 干净；trace 上离线 OPT vs LRU = 174 vs 301（P1）、165 vs 273（P3）→ 4B 可区分。
4. **G3-03 修复**：`delete[]`→`free`（commit `eafa7ae`，独立 patch）。修复前 ASan alloc-dealloc-mismatch 证据留存（`logs/w0_prefix_asan_run.txt`）；修复后 0 报错（含驱逐激活态）；pair 输出修复前后逐字节相同（223,500 对）。
5. **error_bound 真值（G3-10 处置；曾因 sed 空格数（5 vs 6）得出假惰性，已纠正）**：W1 eb∈{0.01,0.1,0.5} 惰性（1484 任务/recall 63.89%），eb=1.0 剪枝（1435/63.09%）；W2 eb=1.0：1685→1594/86.95%→85.80%；W0 全惰性。机制经 `GATE4A_KNN_OUT` dump + arcos 表逐位复算确认：自候选表远端累加角度，eb≤远端首角度（W1 中位 0.89 rad）即 keep-all。
6. **确定性根因（G3-14 落实）**：中心图 `addPoint` 并行构建非确定 → OMP>1 在重叠数据上 pair 集合逐次漂移（190,050/190,171/190,057，全部 TP）；**OMP=1 比特级确定**（metadata/hnsw/pairs）。规程固化：受控对照一律 OMP=1。
7. **mem_budget 三重身份**：同一参数同时决定写缓冲（构建期，P1 894,784B vs 2,304B）、cache 容量、Gorder 窗口；分配/任务/pair 与预算无关。

### 11.3 Gate 4A 判定

A. WORKLOAD_READY **PASS**；B. GORDER_READY **PASS**；C. CACHE_READY **PASS** → **Gate 4A = PASS**。

### 11.4 Gate 4B 最小矩阵（设计，未执行；执行前需明确授权）

- 公平性前提：数据/ε/bucketization（冻结 OMP=1 构建产物）/候选任务/CPU/内存预算/Recall 协议固定；**OMP=1**；正确性与计时分开；每变体独立 patch+审计。
- F1 任务顺序 {identity, random(seed 20260101), Gorder} × F2 缓存策略 {C++ Belady, LRU}（先冻结 trace 离线、再二进制 patch）于 eb=0.1，载体 P1/P3；F3 error_bound {0.1, 1.0} 扫描。度量全计数优先：hit/miss/evict/reject、读盘字节、dist_comp、任务数、oracle TP/FN/recall、pair 集合恒等校验。约 30–40 次运行，分钟级。
- 停止条件：(1) OMP=1 出现 run-to-run 不确定；(2) 任务图不变而 recall 变；(3) 任一变体 FP>0 或 ASan 报错；(4) 顺序变体的 pair 集合与基线不恒等。

### 11.5 停止点（已遵守）

完成上述实验与三份报告（`GATE4A_REPORT.md`、本节、`REPORT.md`）后**立即停止**：未执行任何 Gate 4B 消融运行，未跑 10M/100M，未用真实数据，未 sudo/安装，未改参考仓库（SHA 与 clean 状态不变），未 commit/push 参考仓库。

---

## 12. Gate 4B-0 详录：消融前置方法学审计（FN 归因 / Cache 策略 / Gorder 公平）（2026-11-02）

> 与 Gate 4B-1 的区别：本节只做消融的**前置验证与解释性审计**——FN 来源逐对归因、cache 策略语义与 miss 差异解释、顺序对照公平性基础设施——**不执行** §12.4 的 36 次消融矩阵。详细报告：`GATE4B0_REPORT.md`（12 节）。

### 12.1 范围与产物

- 三项任务：Task 1 FN 六类互斥归因；Task 2 cache 策略四模型审计（A 强制装入 Belady / B 允许拒绝（全量为贪心模拟）/ C C++ 精确复刻 / D 强制装入 LRU）；Task 3 顺序对照公平性（identity / random / Gorder / window 覆盖）。
- 全部产物在 `workspace/gate4b0/`：`instrumented/DiskJoin`（复制 4A 插桩仓库后追加 commit `7e4df0c`，共 7 commits，工作树 clean；4A 仓库未触碰）、`build/{normal,asan}`、`patches/gate4b0_order_window.patch`（85 行：`GATE4B0_WINDOW` 窗口覆盖 + `GATE4B0_ORDER/GATE4B0_PERM_FILE` 顺序覆盖，均在 `order_gorder` **之后**应用；默认行为零改变——R2/R3 与 4A 冻结 trace/tasks/knn/pairs/重建产物逐字节一致证明惰性）、`oracle/{run_gate4b0.sh, order_invariance.py, fn_attribute.py, cache_models.py}`（纯 stdlib）、`data/`（3 个本地输出路径 config + `perm_random_seed20260101.txt` + 冻结 md5 基线）、`runs/`（11 目录）、`results/{order_invariance,fn_attribution,cache_models,divergence_summary}.json`、`logs/`。
- 11 次串行运行全部 OMP=1、timeout 600；每运行后 cmp 重建 .clusters/.metadata/.hnsw == 4A 冻结件（字节级）；运行前后 `md5sum -c` 冻结 8 文件全 OK；ASan 无内存错误（2 处上游泄漏见 §12.2-6）。

### 12.2 关键结果

1. **FN 六类互斥归因（总量逐对等于 oracle FN）**：类语义（判定序固定）：1 同桶 / 2 边覆盖（cross-join 无 ID 过滤） / 3 双向无 KNN 候选 / 4 仅反向候选被上三角过滤 / 5 Algorithm-3 剪枝 / 6 未解释。**P1(eb0.1) FN=107,451 = c3 81,701 (76.06%) + c4 25,750 (23.94%)**（c1=c2=c5=c6=0）；**P3(eb0.1) FN=8,878 = c3 5,543 (62.44%) + c4 3,301 (37.18%) + c1 17 + c2 15 + c5 2**（c6=0）。召回损失主体是**候选生成不足（c3）与有向 top-K 的上三角方向丢失（c4）**，非 Algorithm 3。覆盖一致性双向验证：found ⊆ coverage 0 违例；(coverage∧GT)−found 恰为 c1∪c2。有向候选图：P1 2,760 条有向边中 1,364 条上三角兼容（eb0.1 全保留）；P3 1,640 条上三角兼容中 75 条被剪（仅 2 个桶对带 GT 对）。
2. **P3 的 17（同桶）+15（边覆盖）个"覆盖型 FN"全部是 ε² 浮点边界 tie，非算法 bug**：oracle（double 累加，阈值 0.2）判入 vs C++（float32 AVX2 FMA，阈值 float(√0.2f)²=0.19999998807907104）判出；32 对 |dist²−0.2|/0.2 ∈ [2.62e-9, 6.14e-8]（float32 ULP 量级）；该分歧单边（FP=0）。
3. **Algorithm 3 增量（eb 0.1→1.0）逐对映射到被剪边**：P1 新增 FN 2,380（recall 63.89→63.09%），100% 落在 49 条被剪桶边；P3 新增 785（86.95→85.80%），100% 落在 91 条被剪桶边；恢复 0、新增边 0（剪枝单调收紧）。P1 eb0.1 完全惰性；P3 eb0.1 非惰性（75 条候选被剪，仅 2 对 GT 受损）——4A 遗留问题关闭。
4. **Cache 四模型（同访问序列 / 容量 62 / 空初态 / 同 miss 口径）**：A(强制装入 Belady)=174/165 > B=C(允许拒绝；B 全量为贪心模拟、C 为 C++ 复刻)=172/164 < D(强制装入 LRU)=301/273（P1/P3）。C 与 C++ trace 逐决策吻合：A-line 命中标记 0/1484、0/1685 失配；P-line 动作类型 0 失配；P-line victim 0 硬失配（23/15 处 sentinel 平局 victim 经 iters/ptr 证明 never-again 等价）。**172<174 / 164<165 的机制**：拒绝能力沿分岔链的净贡献——P1 7 条链净 +2（@526 桶 2 never-again 而被 A 驱逐的 105@689 会被再用 → @689 A miss/C hit；@883 同型桶 26/112@1159）；P3 2 条链净 +1（链 [532..1684] 含 5 个命中差异事件，**非单调**——C 在 970/1555 也付出被拒再访的代价）。最小反例（容量 1，[0,1,0]）：强制 3 miss vs 拒绝 2 miss，精确 DP 双侧验证。小规模精确 DP（8 个前缀×容量组）：greedyA==forced-opt 8/8（Belady 最优性复核）；greedyB==reject-opt 8/8（未找到 C++ 拒绝规则次优反例）；reject-opt<forced-opt 8/8。**诚实标注**：A=174/165 为可证最优；B=172/164 全量上是贪心模拟（reject-opt 的上界），最优性仅小规模验证。LRU+拒绝语义不可定义（拒绝判据需未来知识）→ 4B-1 策略档取 {C++ Belady-拒绝, 强制-Belady, 强制-LRU}。
5. **顺序对照公平性（Task 3）**：`order_gorder` 返回 bucket→slot rank，perm 只搬 slot 位置——任务多重集与 pair 集合不变，顺序仅通过 `cache.init` 的未来使用索引起作用。运行验证（`order_invariance.py` PASS）：pair 集合（P1 190,149 / P3 59,151）与任务多重集（各 120 条）跨 {default, identity, random(seed 20260101), window120} + 冻结件恒等。Miss 表（capacity=62，同预算/策略/eb）：Gorder **172/164**；identity 195/**134**；random 246/204；Gorder-窗口禁用（w=120，window_removals=0）190/165。窗口滑动贡献 P1 −18 / P3 −1 miss；窗口长度整数链 `(budget/4/length)/K*2`（P1：(273804/4/1104)/24*2=4），真实滑动由 `window_removals=116=120−4` 实证。**P3 上 identity 优于 Gorder（少 30 miss）**——顺序收益负载相关，观察非结论。
6. **上游新发现（本轮）**：`ClusterWriter::writeClusters` 两处泄漏（`new char[cluster_num*buffer_size]` P3 small 430,080 B + `new float[batch_size*d]` 256 B，从不释放；LeakSanitizer 令 exit 1，`detect_leaks=0` 后 rc=0 且统计一致）——非补丁引入（补丁只改 search()），参考代码未改。仓内 `simulate_cache` 有隐式 reject（与 C++ 同规则，无计数器）。

### 12.3 判定

- A. `FN_ATTRIBUTION` **PASS**：总量逐对相等 + class6=0 + 覆盖型 32 对已单独量化为 ε² 边界 tie + 增量 100% 落被剪边。
- B. `CACHE_POLICY_VALIDATION` **PASS**：四模型同口径校准 + C 与 C++ 逐决策吻合 + 172/164 vs 174/165 差异分岔链级解释 + OPT 标注诚实（A 可证最优；B 全量为贪心上界）。
- C. `ABLATION_FAIRNESS` **PASS**：bucketization 字节级冻结 + 任务多重集/pair 集合跨顺序恒等 + 容量/策略/预算/Recall 协议固定 + 窗口长度与真实滑动实证 + 窗口可独立控制（不动 mem_budget）；容量独立控制（`GATE4B0_CAPACITY`）已识别为 4B-1 前置项。

**Gate 4B-0 = PASS。**

### 12.4 Gate 4B-1 最小矩阵（设计，未执行；执行前需明确授权）

- F1 顺序 {identity, Gorder, random≥3 种子} × F2 策略 {C++ Belady-拒绝, 强制-Belady, 强制-LRU} × F3 eb {0.1, 1.0}，载体 P1/P3 = **36 次运行**（OMP=1，分钟级）＋每运行不变量断言（pair 集合在固定 eb 下跨 F1/F2 恒等）。
- 前置改动：(a) 策略选择 env（接入 `LRUCache`/强制装入变体）；(b) `GATE4B0_CAPACITY` 容量覆盖（当前容量仍由 mem_budget 推导，须独立钉住才能与 F1/F3 正交）。
- 度量与停止条件见 `GATE4B0_REPORT.md` §10（沿袭 4A §11.4）。

### 12.5 停止点（已遵守）

完成本节、`GATE4B0_REPORT.md` 与 `REPORT.md` 更新后**立即停止**：未执行 Gate 4B-1 矩阵（仅设计）、未跑 Gate 5/论文级实验、未跑 10M/100M、未用真实数据、未 sudo/安装、未改参考仓库（pinned SHA 与 clean 不变）、未 commit/push 任何远程；gate4a 冻结资产零覆盖（md5 前后核验通过）。

---

## 13. Gate 4B-1 详录：受控机制消融（任务序 × 缓存策略 × 剪枝）（2026-11-02）

> 按 §12.4 预注册设计执行（用户显式授权 Gate 4 消融）：36 组主矩阵（P1/P3 × {identity, Gorder, random} × {C++ Belady-拒绝, 强制-Belady, 强制-LRU} × eb{0.1, 1.0}）+ 12 组独立种子复核 + 8 组 W1H/W2H holdout + 36 组计时运行，全部 rc=0。验证级别 `mechanism_ablation`（合成 4k 向量受控负载，计数/IO 字节口径；**非**论文级性能复现）。详细报告：`GATE4B1_REPORT.md`（15 节，判定 PASS）。

### 13.1 范围与产物

- 全部产物在 `workspace/gate4b1/`：`instrumented/DiskJoin`（复制 gate4b0 HEAD `7e4df0c` 后 4 个本地 commit：`e0d11c1` 机制实现 + IO 计量 → `f1ac471` ClusterWriter 泄漏修复 → `17fa981` 策略单元测试 → `51a90f7` heap 越界修复；工作树 clean；gate4a/gate4b0 仓库未触碰；本地 commit 不 push）、`build/{normal,asan}`、`patches/gate4b1_mechanism_and_leakfix.patch`（229 行）+ `patches/gate4b1_heap_siftdown_guardfix.patch`（70 行，均相对 gate4b0 HEAD 链导出）。
- `oracle/`：`run_gate4b1.sh`（单运行封装：correctness/timing 双模式、OMP=1、timeout 600、运行后 cmp 重建产物==gate4a）、`run_matrix_gate4b1.sh`（预注册 36 组主矩阵）、`run_timing_gate4b1.sh`（36 配置计时，5 关键配置 REP=5）、`policy_test.cpp`（14 用例 × 3 策略，normal+ASan 双编译均 PASS）、`analyze_gate4b1.py`（纯 stdlib；65 组运行零一致性问题）。
- `data/`：8 个 config（p1/p3/w1h/w2h × eb0.1/1.0；data_file 指向共享只读 gate4a fbin、输出路径本地）+ `perm_random_seed{20260101,20261102,424242}.txt` 冻结随机序。
- `runs/`（74 correctness + 36 timing 目录）、`logs/`（265 个日志，含全部失败证据：`prefix_crash_p3_lru_asan.*`、`prefix_policy_test_asan.*`、`prefix_leak_evidence_*`、`failedcfg_w*`、`*_preheapfix`）、`results/`（gate4b1_{summary,locality,capcurve,timing}.tsv + gate4b1_digest.md）。
- 固定条件：容量 62 槽（`GATE4B1_CAPACITY=62` 显式钉住，与顺序/剪枝因子正交）、window=4、OMP=1、串行、冻结 bucketization（每运行 cmp 重建 clusters/metadata/hnsw == gate4a 字节级）；gate4a 冻结资产 md5 8/8 前后复核通过。

### 13.2 关键结果

1. **机制隔离（消融公平性）**：同 (ds,eb) 下 pair 集合在 9 个 order×policy 组合间逐对恒等（P1 eb01=190,149 / P3 eb01=59,151，且 == gate4a 冻结 pairs）；任务图（target+候选集）跨序恒等、tasks.txt 跨策略字节恒等；**dist_comp 跨 order×policy 严格不变**（P1 eb01=1,833,576 / P3 eb01=3,274,616）——顺序/策略的影响被完全隔离在缓存与 I/O 层；全量 Oracle 下 65 组运行 FP=0、重复对=0。
2. **H1 任务序**：P1 gorder(172)<identity(195)<random(246)；**P3 identity(134)<gorder(164)<random(204)**（eb1.0 同型：P1 172<186<237、P3 133<161<195）；W2H holdout 复现 P3 型（identity 149 < gorder 171），W1H 为 P1 型但近平（173 vs 176）——**Gorder 非全局最优（负结果保留）**。随机序对种子稳健（3 种子极差 ≤7）。机理：LRU 栈距离核算精确到个位（miss = 120 冷 + #{栈距 ≥62 的复访}，6/6 组态吻合）；P3 identity 优势为结构性（容量 40/62/80 全区间成立；P3 top-10 桶占 38.9% 访问的强热点下“创建序=密度序”天然时序局部性更优；gorder 相邻 slot 重叠反而更高（7.59 vs 6.52）但栈距离更差——window 局部目标 ≠ 全局复用距离最小化）。
3. **H2 替换策略**：同一强制装入动作集下 Belady vs LRU：LRU 惩罚 +65.5%~+104.0%（P1 174→301、P3 165→273 等 6 组态），**顺序越差惩罚越大**（好顺序部分替代替换智能）；拒绝装入边际贡献 0–4 miss（24/24 组合恒非负、random 序上稍大），且同时降低 miss 与 evict 次数（P1 gorder：evict 92 vs 112）。
4. **H3 剪枝**：eb0.1→1.0（gorder/reject）：tasks −3.3%/−5.4%、dist_comp −3.3%/−3.7%、有效读字节 −0.2%/−1.4%、TP −2,380/−785（recall 63.89→63.09% / 86.95→85.80%）；每损失 1 个 TP 节省 25.4（P1）/153.7（P3）次距离计算。
5. **可复现性（三重）**：eb0.1 全部 miss 与 4B-0 离线模型精确一致（P1 gorder 172/174/301、P3 164/165/273、identity 195/134、random 246/204；种子 246/239/242、204/205/199）；逐事件 lockstep：LRU victim 精确匹配（全部 LRU 运行零失配）、forced victim 零硬失配（9–38 次 never-again 平局等价）、reject 完全复现 C++ 规则；read_calls==miss；eff/req 字节按 ClusterIO.h 精确公式离线复算全等（O_DIRECT 读放大 ≈2.96×，syscall 口径；**设备层物理 I/O UNVERIFIED**）；ASan 与 normal 构建输出逐字节一致。
6. **上游工程发现（均按纪律处置、参考仓库不动）**：(a) `updateable_heap::sift_down` 满堆 guard 节点**两处**先读后判越界（READ of size 8，storage[63]）——原 Belady 语义不可达（update 只 sift_up；pop 在 --current_bound=62 偶数后 sift、无 guard 节点），由新增 lru_forced（hit 递减 recency 键）暴露；guard 前置修复、定义域行为等价、默认路径与 4B-0 冻结件/修复前档案**三向字节级不变**（证据：`logs/prefix_crash_p3_lru_asan.stderr` 真实运行崩溃 + `logs/prefix_policy_test_asan.stderr` 单元测试独立复现）；(b) 4B-0 发现的 ClusterWriter 两处泄漏已修复（LSan 归零，修复前证据保留）；(c) `read_fbin` 不检查 ifstream open 失败——holdout 首轮我方配置错误（data_file 被 sed 改到不存在路径）放大为 2×600s 超时 + 2×SIGFPE，失败运行归档 `failedcfg_*`，上游健壮性问题记录未修。
7. **计时**：36 配置 wall 0.08–0.12 s/次（REP=5 极差 ≤0.02 s；build ≈0.05–0.06 s、search ≈0.03–0.06 s）——**亚秒级，仅记录，不作任何性能/SSD 结论**（n=4000 ≪ 论文规模）。

### 13.3 判定

- 主矩阵 36/36、种子 12/12、holdout 8/8、计时 36 配置全部 rc=0；停止条件（OMP=1 出现不确定性、任务图不变而 recall 变、任一变体 FP>0、顺序/策略变体改变 pair 集）**无一触发**。
- 成功条件全满足：① 三策略 14 用例单元测试（normal+ASan）+ 65 组逐事件模型核对；② 容量/window 独立可控且字节级验证；③ 矩阵+种子+holdout+计时完成归档（含全部失败证据）；④ 正确性不变量全部成立（FP=0、pair 集合/任务图恒等、trace↔stats、IO 复算）；⑤ 三重可复现（ASan/normal、跨门冻结件、4B-0 模型）；⑥ 三机制量化结论（H1–H3）；⑦ 负结果保留并解释。
- **Gate 4B-1 = PASS**（范围：受控合成小负载上的机制消融，不构成对论文 SIGMOD 2026 性能声明的复现）。

### 13.4 与预注册设计（§12.4）的偏差

- “random ≥3 种子”：主矩阵 seed20260101 + 独立复核 seed20261102/424242（12 组，未用于调参）。
- 容量覆盖按设计落地为独立 env `GATE4B1_CAPACITY`（4B-0 识别的前置项），62 钉住 + cap40 对照验证容量独立性。
- W1H/W2H holdout（8 组）为设计外的一次性额外复核（未据其调参）；首轮失败为我方配置错误（见 13.2-6c），修复后全部通过、失败证据全保留。
- 未做（超出授权）：窗口 sweep、K sweep、候选对称化、真实数据。

### 13.5 停止点（已遵守）

- 未执行 Gate 5 / 真实数据 / 10M–100M / 论文级性能对比；未 sudo/安装/下载、未多机。
- 参考仓库 pinned SHA 不变、工作树 clean；gate4a 冻结资产 md5 8/8 复核通过；gate4a/gate4b0 仓库未触碰；gate4b1 本地 commit 未 push。
- 计时结果未用于任何性能声明；设备层物理 I/O 保持 UNVERIFIED 标注。

一键复核：

```bash
bash workspace/gate4b1/oracle/run_matrix_gate4b1.sh   # 36 组主矩阵
python3 workspace/gate4b1/oracle/analyze_gate4b1.py   # 65 组 -> results/*.tsv（预期 0 一致性问题）
cd workspace && md5sum -c gate4b0/data/gate4a_frozen_md5.txt   # 冻结资产 8/8 OK
cd reference/DiskJoin && git rev-parse HEAD && git status --short  # pinned + clean
```

---

## 14. Gate 5A 详录：BigANN100K 真实数据有界试点（2026-11-02）

> 按用户显式授权的 Gate 5A 规范执行：审计移交内容 → 官方来源**部分下载**准备 BigANN100K（FTP Range 24 MiB；无完整 1B 下载、不跑上游大脚本）→ 记录类型/行数/维度/SHA-256/确切命令 → 验证 C++ 管道 → **独立精确距离采样召回评估**（禁用 ANN kNN GT 替代）→ 任务序/缓存策略少量诊断对照（固定输入/候选图/容量）→ 不声明真实性能加速比。7 组端到端配置（V0、R1–R4、R5、R6；六组 rc=0，R5 为 ASan 依设计中止 rc=1，证据归档见 14.4-F1）+ 1 次计时测量，全部在资源限额内。验证级别 `realdata_pilot`（100K 真实向量、受控变量；**非**论文级性能复现）。详细报告：`GATE5A_REPORT.md`（10 节，判定 **PARTIAL 偏 PASS**）。

### 14.1 范围与产物

- 全部产物在 `workspace/gate5a/`：`instrumented/DiskJoin`（复制 gate4b1 HEAD `51a90f7`，**本轮零本地 commit**、工作树 clean、未 push；gate4a/gate4b0/gate4b1 仓库未触碰）、`build/{normal,asan,asan_g,asan_patched}` + `policy_test{,_asan}`。
- `oracle/`：`run_gate5a.sh`（单运行封装，correctness/timing 双模式、OMP=1、timeout 600）、`sample_gt_endpoints.py`（端点采样器，算法与种子记录在案）、`gt_calib.cpp`（**精确 int32** 校准器 + 暴力 GT，无浮点）、`v0diag.cpp`（向量 0 诊断）、`analyze_gate5a.py`（纯 stdlib 终检：召回 + 不变量 + lockstep + IO 复算 + 跨序恒等；`results/analyze_gate5a_output.txt` Problems: none）。
- `data/`：gz 前缀（凭证）、`bigann100k.bvecs`（13,200,000 B）、`bigann100k.fbin`（51,200,008 B）、`bigann100k.config`、校准表 ×2、`gt_m272.txt`（201 端点精确 GT）、`gt_endpoints.txt` / `calib_ids_2000.txt`（种子 20260101，CPython Mersenne Twister）、`frozen_r1/`（R1 分桶冻结副本 + md5）。
- `runs/`（v0、r1–r6、r1t_timing）、`logs/`（全部 stdout/stderr + 构建日志 + policy_test）、`results/`、`patches/gate5a_prefetch_guard.diff`（F1 诊断守卫；源树已恢复并 sha256 复核）。
- 固定条件：radius=73984、cluster_num=1000、K=24、eb=0.1、budget=5,120,000 B（精确 10%）、**C0=28 槽 / W0=2**（R1 派生；R2–R4 用 `GATE4B1_CAPACITY=28 GATE4B0_WINDOW=2` 钉住，钉住值 == 派生值）、OMP=1、每运行 cmp 重建分桶 == `frozen_r1` 字节级（4/4）。

### 14.2 数据获取与校准（预注册）

- **官方来源部分下载**：`ftp://ftp.irisa.fr/local/texmex/corpus/bigann_base.bvecs.gz`（IRISA/texmex ANN_SIFT1B；服务器 Content-Length 97,941,899,519 B ≈ 91.2 GiB、Accept-ranges ✓、仅 FTP 可达）。命令 `curl -sS -r 0-25165823 --max-time 570`——**Range 0–25,165,823，仅 24 MiB**，误下全量风险为零；官方子集约定原文 "These subsets are the n first vectors of the bigann_base.bvecs file" → 前 100,000 向量即 BigANN100K。
- 记录：类型 = 逐记录（uint32 维数头 + 128×uint8）、行数 = 100,000、维度 = 128、SHA-256：gz 前缀 `0b2ced404942c55c67fa8434d3e492fbb4643a288714e59ab2979996634eb58d`、bvecs `cd48bfd0f8d8b86a179a36fde4f838ebdffaa79f7f12acbfee28f057acce69c3`、fbin `d967109732b708dd054c2d1289203159ebae88b9bc46004a54961466816e16e1`。
- **诚实边界**：截断 gz 流无法 CRC 校验 → 结构性校验替代：gzip magic ✓、全部 **100,001 个记录头 == 128**（含 1 条过量读取的对齐证明）、uint8 值域 min 0 / max 205 / 180 个不同值、uint8→float32 转换往返精确（记录 0/1/99,999 逐分量）。gz 前缀留档可复核。
- **阈值校准（论文默认协议）**：2,000 个校准 id（`random.Random(20260101).sample`）+ 精确 int32 校准器扫描 m → **m=272（radius=73984=272²）时 mean=100.46 邻居/向量 ≈ 论文 100**；分布重尾（中位数 4、26.4% 端点零邻居）如实记录。`gt=3 == |N(0)|`（GT 文件实证 {2, 93937, 95491}，写入前验证非零）。
- **float32 精度链（正确性根基）**：uint8 数据 → 128 维平方和 ≤ 8,323,200 < 2²⁴ → float32 距离**精确等于整数**（与 AVX2/FMA 累加顺序无关）；radius 为完全平方数 → `dist < epsilon²` ≡ 整数严格 `< m²` ≡ GT 比较 → 4B-0 的 ε² 边界平局类问题在本数据**结构性消除**。`mem_budget=0.00476837158203125`（=625/2¹⁷ 二进有理）→ float32×1024³ 链每步精确 → budget 恰为 5,120,000 B（python 逐位验证）。
- 与官方 100M 配置的有意偏差（预注册非静默）：radius 10000→73984（官方值在 100K 子集上仅 ~0.24 邻居/向量）；cluster_num 200,000（0.2‰）→ **1,000（1%）**——论文最优域 1–2‰ 在 100K 上使 W=2⌊C/K⌋ 塌缩为 0、Gorder 机制不可观测。

### 14.3 关键结果

1. **可执行性与回归**：V0 合成回归 4 个 dump 与 gate4b1 `runs/p1_default` 逐字节一致 + 构建产物 md5 == gate4a 冻结值；policy_test 14 用例（normal+ASan）输出与 gate4b1 冻结日志逐字节一致；R1–R4 全 rc=0；派生 max_points=348、task_total=13,011、`[gate3-inv]` 全部不变量通过（upper_triangle_ok=1、bucket_sum=100,000）；Gorder window=2 真实滑移（window_removals=998）。
2. **机制对照**（固定输入/候选图/容量 C0=28/W0=2）：**Gorder 5,192 vs identity 9,052 miss（−42.6%）**；**belady_reject 5,192 vs lru_forced 7,297（−28.8%）** vs belady_forced 5,215（拒绝边际 23 miss ≈ 0.4%）；方向与 4B-1 合成 P1 一致、未出现 P3 型 identity 反超（单一数据集单点，不作普适结论）。**pair 集合 3,855,811 对跨 4 组 order×policy 逐对恒等**（0 重复行）、knn.txt 恒等。
3. **独立采样召回**（201 预注册端点 = 200 均匀采样 + 向量 0；**精确整数暴力 GT，非 ANN kNN、非 in-binary 打印**）：端点级 **23,354/30,531 = 0.764927**（Wilson95 [0.760138, 0.769650]）；对级去重 0.765053（23,328/30,492）；**FP=0**（两级均）；每端点 min 0 / median 0.5865 / mean 0.5213 / max 1.0；55/201 端点零邻居（如实记录）；in-binary 打印 2/3 交叉核验吻合（向量 0 GT {2, 93937, 95491}、找到 {93937, 95491}、漏 {2} = 桶级剪枝）。
4. **机制复核（全部精确闭合）**：lockstep 逐事件重放 R1(C)/R2(C)/R3(D)/R4(A) 计数器全等、0 硬失配、victim 差异 102/25/0/241 全为 SIZE_MAX 永不再用平局等价（D 精确）；read_calls==miss；eff/req 字节离线重算逐一相等（286,884,352 / 305,594,368；read() 视角放大 1.065×；**设备层物理 I/O UNVERIFIED**）；LRU 栈距离核算 cold 1,000 + #(sd≥28) 6,297 = **7,297 == R3 miss**；dist_comp 任务图离线精确重算 **154,113,486**（五运行同值 ⇒ join 工作量确实顺序不变）。
5. **资源包络全遵守**：下载 24 MiB（≤1 GiB）、新磁盘 428 MB（≤5 GiB）、RSS 峰值 15,004 KB（≤12 GiB）、单次最长 14.3 s（≤600 s）、OMP=1（≤4）、端到端配置 7 组（≤8）、无 1M/10M/100M、无 sudo/安装；计时 wall 7.27 s（user 5.45 / sys 0.19 / RSS 15,004 KB，无插桩干净路径）仅记录、不作任何性能声明。

### 14.4 上游发现 F1/F2（均非本复现引入、均不影响 join 结果）

- **F1（重要）**：hnswlib `searchBaseLayer` SSE 预取操作数 `*(datal+j+1)` 在 `j+1==size` 时读链接数组后一个 `tableint`（`hnswalg.h:264`；`USE_SSE` 由 `hnswlib.h:4` 无条件定义）——level≥1 链接表是独立 `malloc(84×level+1)` 块，满链接（20）时越界读 3 字节。真实 1000 中心图首次触发（R5 ASan abort，证据 `logs/r5_default_asan.stderr` + `-g` 构建行号级复现 `logs/r5g_default_asan.stderr`）；合成 120/240 中心从未触发（4B-1 ASan 全绿的原因）。读值仅喂 `_mm_prefetch`（提示指令）→ **零功能影响**。处置：诊断守卫补丁 `patches/gate5a_prefetch_guard.diff` → R6 ASan+LSan 全绿 + 4 个 dump 与 R1 逐字节一致 ⇒ 守卫为功能无操作、R5 中止唯一归因于该越界读、search/join 全管线 sanitizer 干净；跑毕恢复源文件（sha256 `4b6607b721f6c8c04825b9b89cdf4400df92e481566ec9db0fb6e1180aaf1d8f` 复核 + instrumented 树 git status 0 行）。参考仓库未动、未 commit。
- **F2（轻微，仅打印）**：`DiskJoin.h:245` `float dist_comp` 为 **float32 计数器**——真值 154,113,486 顺序不变，打印 +66(gorder)/+114(identity)（>2²⁴ 后 ULP=16 的序相关舍入；合成 p1=1.83M / p3=3.27M < 2²⁴ 从未触发）。仅打印计量失真、不参与任何分支/输出决策；其余统计均为 size_t。建议后续以任务图重算值为准报告。

### 14.5 判定

- 正常构建路径 7/7 通过（V0、R1–R4、r1t + policy_test×2 回归）；ASan 路径 1/2（R6 补丁版通过、R5 原版被上游 F1 阻断）。
- 成功条件：数据来源/完整性/转换 ✓（结构性校验 + 诚实边界）；资源限额 ✓；真实数据端到端可执行 ✓（机制全部激活可观测、4/4 分桶重建字节一致）；独立精确采样召回 ✓（FP=0、Wilson CI、in-binary 交叉核验）；机制对照 ✓（pair 集跨序恒等 + lockstep 0 硬失配 + 栈距离精确闭合）；无性能声明 ✓。
- **Gate 5A = PARTIAL（偏 PASS）**：唯一扣分项为 R5 被上游 F1 阻断（根因已定位、影响已界定为零功能影响、补丁已验证为无操作、证据全留档）。

### 14.6 与预注册规范的偏差

- cluster_num=1000（1%）而非论文最优域 1–2‰（机制可观测性选择，预注册记录）；radius 按密度协议重校准（官方 100M 值在 100K 上密度趋零）。
- ASan 路径需要隔离诊断守卫补丁（授权范围内；源树恢复 + sha256 复核）。
- 端点级召回采用预注册双计口径（两端点均采样的对各计一次）+ 对级去重变体并列报告。
- 未做（超出授权）：λ 召回协议、K/radius/cluster_num/W 扫描、Deep/SPACEV、1M 以上规模、设备层 I/O。

### 14.7 停止点（已遵守）

- 未进入 Gate 5B；未执行 1M/10M/100M；未跑上游大脚本；未 sudo/安装/付费；**本轮零 git commit/push**（gate5a 工作树保持未提交、clean）。
- 参考仓库 pinned `aa86151f97527b1dcf9a032d523c1d67d892454a` + clean；gate4a 冻结资产 md5 8/8 复核通过；gate4a/gate4b0/gate4b1 仓库未触碰；F1 补丁仅以 diff 文件存档且源文件已恢复原状。
- 计时结果未用于任何性能声明；设备层物理 I/O 保持 UNVERIFIED 标注；PACMMOD 正式 PDF 仍缺失（Gate 0 遗留，未解除）。

一键复核（全部只读）：

```bash
python3 workspace/gate5a/oracle/analyze_gate5a.py    # 终检（预期 Problems: none）
cd workspace && md5sum -c gate4b0/data/gate4a_frozen_md5.txt    # 4A 冻结资产 8/8 OK
git -C reference/DiskJoin rev-parse HEAD && git -C reference/DiskJoin status --short    # pinned + clean
sha256sum workspace/gate5a/instrumented/DiskJoin/lib/hnswlib/hnswalg.h    # 源树已恢复：4b6607b7…
# （可选，同一资源包络内重跑）cd workspace/gate5a && bash oracle/run_gate5a.sh r1_default data/bigann100k.config
```

