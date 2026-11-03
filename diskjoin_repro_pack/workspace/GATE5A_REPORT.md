# DiskJoin Gate 5A Report — BigANN100K 真实数据有界试点（Bounded Real-Data Pilot）

日期：2026-11-02
验证级别：`realdata_pilot`（单机、100K 真实向量、受控变量；**非**论文级性能复现，**非**加速比声明）
结论：**PARTIAL**（§1–§9 全部预注册检查完成、正确性证据完整；唯 ASan 全程运行被上游 hnswlib 预取操作数越界读阻断——根因已定位、影响已界定为零功能影响、修复补丁已存档并验证为无操作；详见 §7 F1。若按"受检项通过率"计：正常构建路径 7/7 通过，ASan 路径 1/2 通过）

---

## 1. Executive Summary

在 Gate 0–4B-1 冻结资产之上，从官方 IRISA/texmex ANN_SIFT1B 服务器以 **24 MiB FTP Range 部分下载**取得 BigANN100K（官方"前 n 个向量"子集约定），按论文协议校准阈值（**每向量平均 100.46 个相似邻居 ≈ 论文的 100**），完成 7 组端到端实验配置（V0 合成回归 + R1–R4 机制对照 + R5/R6 ASan 对照）+ 1 次计时测量，全部在资源限额内（下载 24 MiB ≪ 1 GiB、新磁盘 428 MB ≪ 5 GiB、RSS 峰值 14.7 MiB ≪ 12 GiB、单次 ≤14.3s ≪ 600s、OMP=1）。

**核心量化结论**：

1. **真实数据可执行性**：R1–R4 全部 rc=0；bucketization/metadata/任务图/Gorder(window=2)/Cache/Belady-LRU 对照/Join 全部机制统计与不变量通过；每次运行重建的分桶产物 **4/4 次字节一致**（vs 冻结 R1 副本）。
2. **独立采样正确性**（201 端点精确整数暴力 GT，**非** ANN k-NN GT，**非** in-binary 采样打印）：端点级召回 **0.7649**（23,354/30,531，Wilson 95% CI [0.7601, 0.7697]）；对级去重召回 0.7651（23,328/30,492）；**FP = 0**（两端点级与对级）；in-binary 打印 2/3 与向量 0 的 GT（|N(0)|=3）逐项吻合。
3. **机制对照**（固定输入/候选图/容量 C0=28/窗口 W0=2）：任务序 Gorder 5,192 miss vs Identity 9,052 miss（**−42.6%**）；缓存策略 belady_reject 5,192 vs lru_forced 7,297（**−28.8%**）vs belady_forced 5,215（拒绝装入的边际贡献 23 miss ≈ 0.4%）。方向与 4B-1 合成基线一致（P1：Gorder 172 vs Identity 195；belady 172 vs lru 301）。**Pair 集合在 4 组 order×policy 间逐字节恒等**（3,855,811 对，无重复行）。
4. **发现两个上游问题**（均非本复现引入、均不影响 join 结果）：F1 = hnswlib `searchBaseLayer` SSE 预取操作数越界读（ASan 阻断 R5；真实数据首次触发；诊断补丁验证为功能无操作、search/join 全管线 sanitizer 干净）；F2 = `dist_comp` 为 **float32 计数器**（真实值 154,113,486 顺序不变；打印值 +66/+114 的序相关舍入差；合成数据 <2²⁴ 从未触发）。

一切设备层物理 I/O 保持 **UNVERIFIED**；亚秒/十秒级时间仅记录、不构成任何性能或加速比声明。

---

## 2. 真实数据来源及完整性

### 2.1 来源与部分下载（不触碰 1B 全量）

- 官方入口：`http://corpus-texmex.irisa.fr/`（Jégou 等 ANN_SIFT1B 页面；落地页已存 `/tmp/opencode/texmex.html`）。
- 文件：`ftp://ftp.irisa.fr/local/texmex/corpus/bigann_base.bvecs.gz`（FTP 服务器头：Content-Length **97,941,899,519** 字节 ≈ 91.2 GiB；**Accept-ranges: bytes** ✓；Last-Modified 2010-06-16）。无未压缩版（FTP rc=78）；HTTP/HTTPS 变体 403/404/证书错误——仅 FTP 可用。
- **官方子集约定**（落地页原文）："These subsets are the n first vectors of the bigann_base.bvecs file (n=1M,2M,…)" —— BigANN100K = base 的前 100,000 个向量，与 DiskJoin 的 `crop_nb_` 约定一致。
- 下载命令（**Range 0–25,165,823，仅 24 MiB，误下全量的风险为零**）：

```bash
curl -sS -r 0-25165823 --max-time 570 \
  -o data/bigann_base.bvecs.gz.prefix24m \
  ftp://ftp.irisa.fr/local/texmex/corpus/bigann_base.bvecs.gz
```

- 完整性方法（**诚实声明：截断的 gzip 流无法做 CRC 校验**）：gzip magic `1f 8b` ✓；流式解压得到 ≥13,200,004 字节（≥ 100,000 条记录 + 1 条过量读取）；**全部 100,001 个记录头（含第 100,001 个过量读取头）== 128**（4 字节 LE uint32）——记录对齐的结构性证明；载荷为 uint8（首维 min=0/max=205/180 个不同值/均值 25.01，符合 SIFT 量化描述子分布）。gz 前缀文件保留为凭证。

### 2.2 格式转换与哈希（原始类型 → 目标类型）

| 文件 | 内容 | 字节 | SHA-256 |
|---|---|---|---|
| `data/bigann_base.bvecs.gz.prefix24m` | gz 流前缀（凭证） | 25,165,824 | `0b2ced404942c55c67fa8434d3e492fbb4643a288714e59ab2979996634eb58d` |
| `data/bigann100k.bvecs` | 100,000 × (4B 头 + 128×uint8) | 13,200,000 | `cd48bfd0f8d8b86a179a36fde4f838ebdffaa79f7f12acbfee28f057acce69c3` |
| `data/bigann100k.fbin` | fbin 头 (uint32 n=100000, uint32 d=128) + 100,000×128×**float32**（uint8→float32 精确） | 51,200,008 | `d967109732b708dd054c2d1289203159ebae88b9bc46004a54961466816e16e1` |

- 转换：uint8 → float32 **精确**（无舍入；记录 0/1/99,999 往返校验逐分量相等）。
- 精度链论证（供 §4 正确性使用）：数据为整数 ≤255 → 每维平方 ≤65,025、128 维平方和 ≤8,323,200 < 2²⁴ → **float32 距离无论 AVX2/FMA 累加顺序如何都精确等于整数**；取 radius = m²（完全平方数，m≤4095 ⇒ m² 在 float32 精确可表示，`sqrt` 正确舍入到精确的 m，`epsilon²` = m² 精确）→ 二进制阈值 `dist < epsilon²` ≡ 整数严格 `< m²` ≡ GT 的比较。4B-0 的 ε² 边界平局类问题在本数据上**结构性消除**。

### 2.3 阈值校准（论文默认协议）

- 校准采样：2,000 个 id，`random.Random(20260101).sample(range(100000), 2000)`（CPython 3.10.12 Mersenne Twister，排序后写入 `data/calib_ids_2000.txt`；另含向量 0 的 2,001 id 版本 `data/calib_ids_with0.txt`）。
- 精确整数校准器：`oracle/gt_calib.cpp`（int32 精确算术；OMP=4 ≤ 限额）。密度–m 曲线（`data/calib_table*.txt`）：m=262→77.04、266→85.70、270→95.33、**272→100.46**、274→106.02、276→111.83 邻居/向量（不含自配对）。
- **选定 m=272，radius=73984**：命中论文协议"每向量平均 100 个相似向量"（100.46）。分布高度重尾（m=272 时中位数仅 4、26.4% 端点邻居数为 0）——按协议取均值口径，如实记录。
- `data/bigann100k.config`（字段顺序按 `ConfigReader.h` 固定序）：

```
data_file        .../gate5a/data/bigann100k.fbin
radius           73984          # 272^2，float32 精确链
cluster_num      1000           # 1%（见 §2.4 偏差说明）
cluster_file/metadata_file/hnsw_file   .../gate5a/data/bigann100k.{clusters,metadata,hnsw}
K                24             # 桶候选数（受控门控沿用）；桶连接度 24/1000=2.4%
mem_budget       0.00476837158203125   # =625/2^17 二进有理：float32×1024³ 每步精确 → budget 恰为 5,120,000 B = 数据集(51,200,000 B)的 10%（论文默认协议；经 python float32 链精确验证）
error_bound      0.1            # 官方 bigann100M 配置原值
gt               3              # |N(0)|（见 §5），写入前已验证非零
```

### 2.4 与官方 100M 配置的有意偏差（预注册，非静默）

- **radius**：官方 100M 用 10000（=100²）；在 100K 子集上该值平均仅 ~0.24 邻居/向量 → 按论文默认协议重新校准为 73984。
- **cluster_num**：官方 100M 用 200,000（0.2‰）→ 论文最优域 1–2‰ 在 100K 上对应 100–200 桶，会使派生窗口 `W=2×⌊C/K⌋` 塌缩为 0（Gorder 窗口不滑移、机制不可观测）→ 预注册取 **1000（1%）**，得到派生 **C0=28 槽、W0=2**（机制全部可观测）。此为本试点的机制验证选择，**不是**性能声明。

---

## 3. 环境与资源消耗

- 硬件/软件：单机 Linux（24 核可见）、g++ 11.4.0、cmake 3.22.1、Release `-O3 -DNDEBUG`；全程 **OMP_NUM_THREADS=1**（≤4 限额；4B-1 已证明 OMP>1 时并行 HNSW 中心图构建非确定）。
- 限额遵守：

| 项 | 限额 | 实际 | 证据 |
|---|---|---|---|
| 网络下载 | ≤1 GiB | **24 MiB** | `data/bigann_base.bvecs.gz.prefix24m` |
| 新磁盘 | ≤5 GiB | **428 MB**（gate5a 全目录） | `du -sh workspace/gate5a` |
| 进程内存 | ≤12 GiB | **RSS 峰值 15,004 KB ≈ 14.7 MiB** | `runs/r1t_timing/time_r1.log`（`/usr/bin/time -v`，无插桩干净路径） |
| 单次运行时长 | ≤600 s | 最长 **14.29 s**（R6 ASan 全程）；正常构建 7.7 s | `logs/*.stdout` 计时行 |
| OMP 线程 | ≤4 | 1 | wrapper `export OMP_NUM_THREADS=1` |
| 端到端配置数 | ≤8 | **7**（V0、R1、R2、R3、R4、R5、R6；另 1 次同配置计时测量 r1t） | §4 |
| 1M/10M/100M | 禁止 | 未执行 | — |
| sudo/安装/付费 | 禁止 | 未执行（无新依赖；分析纯 stdlib Python + 自写 C++ 校验器） | — |

- 无 git commit/push/reset/clean（本轮约束）；源码改动仅以补丁形式存档且跑完即恢复（§7 F1）。

---

## 4. 实际命令、退出码与日志

- 构建命令与退出码：

```bash
# normal / asan / asan(-g 诊断) / asan(补丁) —— 均 rc=0
cd build/normal && cmake -DCMAKE_BUILD_TYPE=Release ../../instrumented/DiskJoin && make -j4
cd build/asan    && cmake -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_FLAGS="-fsanitize=address -fno-omit-frame-pointer" ../../instrumented/DiskJoin && make -j4
g++ -O2 -o build/policy_test        instrumented/DiskJoin/oracle/policy_test.cpp     # rc=0
g++ -O2 -fsanitize=address -fno-omit-frame-pointer -o build/policy_test_asan \
     instrumented/DiskJoin/oracle/policy_test.cpp                                    # rc=0
g++ -O2 -fopenmp -o oracle/gt_calib oracle/gt_calib.cpp                              # rc=0
```

- 运行封装：`oracle/run_gate5a.sh`（自 gate4b1 wrapper 适配，ROOT 指向 gate5a；correctness 模式导出全部插桩 env：`GATE4A_KNN_OUT/GATE4A_TASK_OUT/GATE3_PAIR_OUT/GATE4A_CACHE_TRACE/GATE4A_STATS/GATE3_INVARIANTS/GATE4B1_IO_STATS`，先 `rm -f knn.txt` 追加模式防串写）。

| 运行 | 命令（等价） | rc | 关键产物 |
|---|---|---|---|
| policy_test ×2 | `./build/policy_test{,_asan}` | 0/0 | `logs/policy_test_{normal,asan}.log`，**与 gate4b1 冻结日志逐字节一致**，14 用例全过 |
| V0 | `run_gate5a.sh v0 runs/v0/p1_v0.config` | **0** | knn/tasks/pairs/trace 与 gate4b1 `runs/p1_default` **逐字节一致**（190,149 对）；构建产物 md5 == gate4a 冻结值（`04042af9…`/`efc0685c…`/`aad03bc4…`） |
| R1 | `run_gate5a.sh r1_default data/bigann100k.config` | **0** | 全部插桩 dump；分桶冻结至 `data/frozen_r1/` |
| R2 | 同配置 + `GATE4B0_ORDER=identity GATE4B1_CAPACITY=28 GATE4B0_WINDOW=2` | **0** | 分桶重建 cmp 4/4 字节一致 |
| R3 | 同配置 + `GATE4B1_POLICY=lru_forced GATE4B1_CAPACITY=28 GATE4B0_WINDOW=2` | **0** | 同上 |
| R4 | 同配置 + `GATE4B1_POLICY=belady_forced GATE4B1_CAPACITY=28 GATE4B0_WINDOW=2` | **0** | 同上 |
| R5 | `BIN=build/asan/main run_gate5a.sh r5_default_asan …` | **1** | ASan abort（§7 F1）；`logs/r5_default_asan.stderr` 全文保留 |
| R6 | `BIN=build/asan_patched/main run_gate5a.sh r6_default_asan_patched …` | **0** | **0** ASan/LSan 发现；4 个 dump 与 R1 **逐字节一致** |
| r1t | `MODE=timing run_gate5a.sh r1t_timing …` | **0** | wall 7.27s / user 5.45s / sys 0.19s / RSS 15,004 KB；无插桩路径 recall 打印与 R1 一致 |

日志全量：`logs/`（运行 stdout/stderr + policy_test + 构建日志）、`runs/<name>/`（knn/tasks/pairs/trace）、`results/analyze_gate5a_output.txt`。

---

## 5. C++ 运行与机制统计（R1–R6 + V0）

### 5.1 派生配置分解（R1 stderr `[gate4a-config]`）

n=100,000 d=128 cluster_num=1000 **max_points=348** budget_bytes=**5,120,000**（精确 10%）length=44,544 **capacity_slots=28** K=24 **window=2** task_num_total=13,011 max_task_num=24 writer_buffer=5,120 B。R2–R4 显式钉住 C=28/W=2（stderr `[gate4b1]`/`[gate4b0]` 行记录 capacity_default=28、window_default=2 —— 钉住值 == 派生值，与 4B-1 结论一致）。

### 5.2 机制对照总表（固定输入/候选图/容量）

| 运行 | 任务序 | 策略 | total | hit | **miss** | admit | evict | reject | read_calls | dist_comp（打印） | 对数 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R1 | gorder | belady_reject | 13,011 | 7,819 (60.1%) | **5,192** | 28 | 3,437 | 1,727 | 5,192 | 154,113,552 | 3,855,811 |
| R2 | identity | belady_reject | 13,011 | 3,959 (30.4%) | **9,052** | 28 | 3,805 | 5,219 | 9,052 | 154,113,600 | 3,855,811 |
| R3 | gorder | lru_forced | 13,011 | 5,714 (43.9%) | **7,297** | 28 | 7,269 | 0 | 7,297 | 154,113,552 | 3,855,811 |
| R4 | gorder | belady_forced | 13,011 | 7,796 (59.9%) | **5,215** | 28 | 5,187 | 0 | 5,215 | 154,113,552 | 3,855,811 |
| R6 | gorder | belady_reject（ASan+补丁） | 13,011 | 7,819 | **5,192** | 28 | 3,437 | 1,727 | 5,192 | 154,113,552 | 3,855,811 |

- **跨序×策略不变性**：knn.txt（候选图）R1–R4 逐字节一致；**pair 集合 R1–R4 逐对恒等**（3,855,811 对、0 重复行）——join 输出仅由（分桶、任务图）决定，order/policy 只改变 I/O 调度，与 4B-1 合成结论在真实数据上成立。
- 任务图不变量（`[gate3-inv]`，R1–R4 全过）：perm_ok=1、empty_tasks=0、head_mismatch=0、self_missing=0、**upper_triangle_ok=1**、task_total=13,011、bucket_sum=100,000。
- Gorder 窗口（`[gate4a-gorder]`）：window=2、insertions=1000、**window_removals=998**（窗口滑移真实发生，对比 toy 上 w>n 的 0 次滑移）。
- **I/O 计量**（`[gate4b1-io]`，R1）：read_calls=5,192 **== miss** ✓；effective 286,884,352 B、requested_aligned 305,594,368 B —— 离线从 metadata+trace 按精确公式重算**逐一相等**；read() 视角放大 1.065×。设备层物理 I/O 仍 **UNVERIFIED**。
- **缓存机制复核**（lockstep trace 重放，移植自 4B-1）：R1(C) 计数器全等 + 102 个 victim 差异**全部**为 SIZE_MAX（永不再用）键平局等价；R2(C) 25 个同理；R3(D=LRU) victim 精确（recency 键唯一）；R4(A=forced-Belady) 241 个平局等价。**acc/type/victim 硬失配 = 0**。
- **LRU 栈距离核算**（R1 访问序列，C=28）：cold 1,000 + #(sd≥28) 6,297 = **7,297 == R3 的 lru_forced miss**（精确闭合）。局部性：interslot 重叠均值 4.858、sd 中位数 31。

### 5.3 与合成负载（4B-1）的初步比较

| 现象 | 4B-1 合成（P1/P3, 4k 向量） | 5A 真实（BigANN100K, 100k 向量） |
|---|---|---|
| Gorder vs Identity miss | P1: 172 vs 195（−11.8%）；**P3: 164 vs 134（Identity 反超）** | 5,192 vs 9,052（**−42.6%**，Gorder 优） |
| belady_reject vs lru_forced | P1: 172 vs 301（+75%）；P3: 164 vs 273（+66%） | 5,192 vs 7,297（+40.5%） |
| belady 拒绝装入边际 | 0–4 miss（≤2%） | 23 miss（0.4%） |
| pair 集跨 order×policy 恒等 | ✓ | ✓ |
| dist_comp 跨序不变 | ✓（1.83M/3.27M < 2²⁴ 精确） | **✗ 打印值 +66/+114 漂移**（真实值 154,113,486 不变；F2，§7） |
| 召回（各自 GT 口径） | P1 63.89% / P3 86.95%（全量 oracle） | 端点采样 76.49%（Wilson CI ±0.48pp） |

- 真实数据上 **Gorder 优势远大于合成 P1**、且未出现 P3 的 Identity 反超——1000 桶/100K 向量的任务图局部性更强（interslot 4.86 邻接桶、栈距离中位 31 ≈ 槽容量 28 的边缘）。单一数据集单点，不作普适结论。
- 重尾密度（26.4% 端点零邻居 vs 合成均匀密度）使召回分布宽（每端点 min 0 / median 0.59 / max 1.0）——真实负载结构差异的直接体现。

---

## 6. 独立采样正确性结果

### 6.1 协议（预注册）

- **采样总体**：{0..99,999} 全体向量；**端点采样**：200 个 id，`random.Random(20260101).sample(range(100000), 200)`（与校准采样相互独立的流）+ 显式追加端点 0（in-binary 采样约定 id%100000==0 在 n=100000 时即向量 0；0 不在 200 样本内）→ **201 端点**，文件 `data/gt_endpoints.txt`（含 EXPLICIT 行记录）。
- **分母与去重规则**：端点级——每个端点 e 的分母 |N(e)|（e 的精确 GT 邻居数，不含自配对），分子 = join 输出中与 e 相关且 ∈ N(e) 的对数；**两端点均被采样的对在两个端点各计一次**（预注册的双计口径）；55 个 |N(e)|=0 的端点排除出比率（计入报告）。对级（去重变体）——GT 对集 30,492 个（min(e,j),max(e,j)），分子 = 输出对中命中者。
- **误差边界**：Wilson 95% CI（双侧 z=1.959964）。
- **GT 构造**：`oracle/gt_calib gt`，对每端点与全部 100,000 向量做**精确 int32 平方距离**、严格 `< 73984`——与二进制 float32 阈值链逐值等价（§2.2 精度论证），**不使用 ANN k-NN GT**。

### 6.2 结果（R1；pair 集恒等 ⇒ R2–R4 同值）

| 口径 | k/n | 召回 | Wilson 95% CI | FP |
|---|---|---|---|---|
| 端点级（双计） | 23,354 / 30,531 | **0.764927** | [0.760138, 0.769650] | 0 |
| 对级（去重） | 23,328 / 30,492 | 0.765053 | [0.760261, 0.769778] | 0 |

- 每端点分布（146 个 GT>0 端点）：min 0.0000、median 0.5865、mean 0.5213、max 1.0000；召回 0 的端点 25 个、召回 1 的 11 个。
- **in-binary 打印交叉核验**：向量 0 的 GT = {2, 93937, 95491}，join 找到 {93937, 95491}（漏 2）→ count=2 == stderr `sampled_count=2` == 打印 recall 2/3 = 0.666667 ✓；config `gt=3` == |N(0)| ✓。FN 的机理即桶级剪枝（向量 2 与向量 0 未落入共同候选桶对）。
- **FP=0 的含义**：输出对全部满足精确阈值 ⇒ join 输出无任何假阳性（结构性结论 + 201 端点实证）；召回缺口 100% 来自漏检（bucket-level 剪枝），符合 DiskJoin 近似 join 语义（λ 目标在 100M/官方配置下评估，本试点不评估 λ 协议）。

---

## 7. 已发现的问题与修复

**F1（重要，上游潜伏，真实数据首次触发）：hnswlib `searchBaseLayer` SSE 预取操作数越界读**
- 现象：R5（ASan，默认配置）在 **build 阶段**（`one_level_kmeans` 中心图 addPoint 循环）abort：`heap-buffer-overflow READ of size 4`，位于 85 字节 malloc 块尾（读 [84,88)，越界 3 字节）。`logs/r5_default_asan.stderr` + `-g` 复现 `logs/r5g_default_asan.stderr`（行号级）。
- 根因（代码级定位）：`lib/hnswlib/hnswlib.h:4` 无条件 `#define USE_SSE`；`hnswalg.h:264` 预取操作数 `*(datal+j+1)` 在 `j+1==size` 时读链接数组**后一个** `tableint`；level≥1 节点的链接表是独立 `malloc(size_links_per_element_×level+1)` 块（上游 "+1" 松弛仅 1 字节）→ **满链接（size==maxM_==20）** 时越界 3 字节。level-0 链接在 `data_level0_memory_` 大 arena 内（每元素记录后跟数据）→ 不越界；search 阶段全部走 `get_linklist0` → 不受影响。
- 触发条件解释：1000 个中心的真实数据图存在满 20 链接的 level≥1 节点；合成 p1/p3（120/240 中心）不存在 → 4B-1 ASan 全绿。
- **影响界定**：越界读的值**仅作为 `_mm_prefetch` 的地址提示参数**（提示指令不可 fault、不改变数据/控制流）→ 对结果零功能影响；R1–R4 normal 构建 4/4 字节一致 + V0 与 4B-1 冻结一致 + R6（见下）佐证。
- 处置（按本轮授权的隔离诊断补丁，非参考行为）：`patches/gate5a_prefetch_guard.diff`（仅对 crash 点两行加 `if (j+1<size)` 守卫）→ R6：ASan+LeakSanitizer **全程 0 发现**、4 个 dump 与 R1 **逐字节一致** ⇒ ① 守卫是功能无操作；② R5 中止**唯一**归因于该预取操作数读；③ search/join 全管线 sanitizer 干净。跑毕恢复原始 `hnswalg.h`（sha256 `4b6607b7…` 复核一致；instrumented 树 git status 0 行）。
- 未修改参考仓库；未 commit（本轮约束）。

**F2（轻微，上游，仅影响打印）：`dist_comp` 是 float32 计数器**
- 现象：R2 打印 dist_comp=154,113,600，R1/R3/R4/R6 打印 154,113,552，而任务图精确重算 = **154,113,486**（五运行同值 ⇒ join 工作量确实顺序不变）。
- 根因：`DiskJoin.h:245` `float dist_comp = 0;` —— 真实计数 1.54×10⁸ > 2²⁴ 后每次累加有 float32 舍入（此量级 ULP=16），累加顺序随槽序/向量化分块而异 → +66（4 ULP，gorder 序）/ +114（7 ULP，identity 序）的**序相关打印漂移**（相对误差 ≤7.4×10⁻⁴）。
- 为何 4B-1 未发现：p1=1,833,576、p3=3,274,616 均 < 2²⁴ 精确可表示 → 跨序严格相等。
- 影响：**仅打印计量失真**，不参与任何分支/输出决策；join 结果与所有其他统计（size_t 计数器）不受影响。

**无其他问题**：LeakSanitizer（R6）0 泄漏（4B-1 的 ClusterWriter 修复有效）；R1–R4 无崩溃/无超时/无 OOM；GATE3/GATE4A 全部不变量通过；分析器终检 Problems: none。

---

## 8. 未验证事项（诚实边界）

- **设备层物理 I/O**：O_DIRECT 下 SSD 实际行为（页缓存命中、预读、队列合并）——仅 read() 系统调用字节级（effective/aligned 重算闭合）；与此前所有门控一致保持 UNVERIFIED。
- **性能/加速比**：7–14 秒级单机小规模运行，不作任何时间性能声明；R1–R4 时长仅作记录。
- **数据完整性边界**：截断 gz 无 CRC 校验（结构性校验代替：100,001 头全对齐 + 值域/分布 + 转换往返精确）；gz 前缀留档可复核。
- **规模外推**：1M/10M/100M、Deep/SPACEV 数据集、λ 目标召回协议、K/radius/cluster_num 扫描、W 窗口扫描均未执行（限额与授权边界）。
- **召回口径**：76.5% 是**本配置**（cluster_num=1000, K=24, eb=0.1, radius=73984）的采样估计，不评估论文的 λ=0.9 协议（需 100M 级 GT 与调参）；55/201 端点零邻居的重尾结构如实记录。
- **F1 的通用性**：守卫补丁仅在 BigANN100K 单点验证为无操作；上游若修复应走官方渠道。真实数据上 hnswlib 其他路径（updatePoint 等）未执行（DiskJoin 不调用）。
- ACM PACMMOD 正式 PDF 仍缺失 → arXiv↔formal 对齐仍未验证（自 Gate 0 遗留）。

---

## 9. Gate 5A 结论

**PARTIAL（偏 PASS）**：
- **通过**（证据完整）：数据来源/完整性/转换（§2）；资源限额全遵守（§3）；真实数据端到端可执行性（R1–R4 全 rc=0、机制全部激活可观测、4/4 分桶重建字节一致）（§4–5）；独立采样正确性（FP=0、召回 76.49% ± 0.48pp、in-binary 交叉核验吻合）（§6）；与合成基线的机制方向一致性 + pair 集恒等（§5.3）；V0/policy_test 二进制回归（§4）。
- **扣分项**：ASan 全程运行（R5）被上游 F1 阻断（非复现引入；已定位根因、界定零功能影响、补丁验证无操作、search/join 管线 sanitizer 干净）；F2 打印失真（影响极小但如实报告）。
- 若采用"每个预注册检查项通过/失败"口径：正常构建路径 7/7 通过；ASan 路径 1/2（R6 补丁版通过、R5 原版阻断）。

---

## 10. Gate 5B 所需资源和授权建议

1. **范围建议**：BigANN1M 或 10M 单数据集（10M = 下载 gz 前缀 ~2.2 GiB 解压 13.2 GB→fbin 5.1 GB，注意 5 GiB 新磁盘限额需上调至 ~25 GB，或改存 bvecs+流式转换）；Deep100M 不建议首轮。保持 ≤8 配置的受控矩阵（默认 + identity + lru_forced + ASan 补丁版 + 1 组计时）。
2. **授权项**：磁盘限额（≥25 GB）、下载限额（≥3 GiB，gz Range 分段续传）、若需 λ 协议则 10M 级 GT 构造的 CPU 时间（精确暴力 200 端点 × 10M × 128 维 int32 ≈ 单机分钟级，可行）。
3. **工程前置**：将 F1 守卫补丁正式化为 gate5b 隔离副本补丁（本轮已验证无操作），ASan 全程回归纳入标准流程；F2 建议以任务图重算值为准报告 dist_comp（二进制打印值标注 float32 舍入）。
4. **测量升级**：设备层 I/O 用 `blktrace`/`iostat` 或显式 UNVERIFIED；计时用 REP≥3 + 冷页缓存协议（drop_caches 需授权）；容量扫描（C ∈ {8..64}）与 W 扫描用离线模型（4B-1 工具已可复用）先行。
5. **不建议**：直接上 100M（下载 ~92 GB、CPU 时间与 GT 成本失控）、多机、任何云支出。

---

## 附录：产物索引

- 数据：`gate5a/data/`（gz 前缀、bvecs、fbin、config、校准表、GT、端点/校准 id、冻结 R1 分桶）
- Oracle：`gate5a/oracle/`（`sample_gt_endpoints.py`、`gt_calib.cpp`、`v0diag.cpp`、`run_gate5a.sh`、`analyze_gate5a.py`）
- 运行：`gate5a/runs/`（v0、r1–r6、r1t_timing）；日志 `gate5a/logs/`；结果 `gate5a/results/`
- 补丁：`gate5a/patches/gate5a_prefetch_guard.diff`（F1 诊断守卫；源树已恢复并 sha256 复核）
- 构建：`gate5a/build/{normal,asan,asan_g,asan_patched}` + `policy_test{,_asan}`
