# DiskJoin Gate 2 报告 — 最小 C++ 端到端复现与执行路径验证

- 日期：2026-11-02
- 项目根：`/home/qch/DiskJoin/diskjoin_repro_pack`
- 参考 upstream：`https://github.com/iidyc/DiskJoin`
- 参考提交（固定）：`aa86151f97527b1dcf9a032d523c1d67d892454a`
- 论文版本：arXiv `2508.18494v2`（15 页；PACMMOD VoR DOI `10.1145/3769780`，正式版 PDF 仍缺失）
- **Gate 2 判定：PASS（smoke 级，记作 `PASS_SMOKE_ONLY`）**

证据标签约定（全文适用）：

- [论文]：论文文字主张，未在本轮验证；
- [源码已检查]：本轮直接读取固定 SHA 的源码行；
- [实验观察]：本轮实际命令/程序的输出（日志文件保留在 `workspace/` 下）；
- [推断]：基于观察的解释，尚未单独验证。

---

## 1. Executive Summary

在单台 Linux 机器上，于固定提交 `aa86151f97527b1dcf9a032d523c1d67d892454a` 完成了 DiskJoin 的最小 C++ 端到端复现（Gate 2），全部结论基于实际执行的命令与程序输出：

1. **参考源码锁定**：`reference/DiskJoin` 为固定 SHA 的克隆，`git rev-parse HEAD` 匹配、`git status --short` 为空，全程未被修改 [实验观察]。
2. **构建**：参考实现用 CMake 3.22.1 + g++ 11.4.0 一次编译通过（exit 0），仅有 `cmake_minimum_required(2.8)` 的弃用告警，无失败、无需修复 [实验观察]。
3. **输入**：12,000 × 16 维 float32 合成 toy（固定种子），文件头、大小、数值范围全部通过校验，无 NaN/Inf [实验观察]。
4. **运行**：12K toy 上参考二进制正常退出（exit 0），stdout 出现 `Build done`、`recall = 1`、`Join done`，stderr 0 字节；重复运行一致 [实验观察]。
5. **执行路径验证**：在隔离插桩副本（不触碰参考仓库）中确认全部关键模块实际执行：bucketization（120/120 非空桶、12,000 向量全部分配）、bucket graph（459 个非空候选任务）、Gorder（有效置换且非恒等）、Belady cache（完整 init/find/push 路径，339 命中/120 缺失/0 淘汰）、join 执行（约 3.59e6 次距离计算）、端到端正常结束 [实验观察]。
6. **采样 Recall 警示**：`recall = 1` 是参考代码 `id % 100000 == 0` 采样口径下的结果（12K 数据仅 ID 0 参与，GT=599）。它**不是**全量 Self-Join Recall，也不能证明论文级精度或性能 [源码已检查 + 实验观察]。

本轮没有发生任何需要"修复"的失败；所有已识别代码风险（`aligned_alloc`/`delete[]` 不匹配、O_DIRECT 读返回值未检查、空任务 `exit(0)` 路径等）仅记录，未修改参考源码。插桩只加了只读计数与打印，未改变任何算法决策（见 §9–§10）。

**Gate 2 PASS 的边界**：只表示最小端到端执行打通并被验证；不表示 join 结果正确性、Recall 统计正确性、与论文算法逐条一致，更不表示论文性能结论复现。

---

## 2. 环境与工具链信息

| 项目 | 观察值 | 来源 |
|---|---|---|
| 操作系统 | Ubuntu 22.04.5 LTS（kernel 6.8.0-40-generic） | [实验观察] |
| 架构 / 指令集 | x86_64；`avx2`、`fma` present | [实验观察] |
| CPU | Intel Xeon Silver 4310，24 逻辑 CPU | [实验观察] |
| 内存 | 62 GiB total / 约 58 GiB available | [实验观察] |
| 根文件系统 | `/dev/sda2` ext4，817 GiB 可用 | [实验观察] |
| `git` | 2.34.1（`/usr/bin/git`） | [实验观察] |
| `cmake` | 3.22.1（`/usr/bin/cmake`） | [实验观察] |
| 编译器 | g++ 11.4.0（GNU，`/usr/bin/g++`），C++11 模式 | [实验观察] |
| OpenMP | CMake `FindOpenMP` 报 4.5 | [实验观察] |
| `python3` | 3.10.12（`/usr/bin/python3`） | [实验观察] |
| O_DIRECT | ext4 上 Gate 0 阶段 `dd` 探针通过；本轮由参考代码实际调用（见 §8 I/O 证据） | [实验观察] |
| 资源统计 | `/usr/bin/time -v`（GNU time） | [实验观察] |

资源纪律：全部构建与运行使用 `OMP_NUM_THREADS=4`、`BUILD_JOBS=4`，直接运行加 `timeout 300`（远高于实际 0.1 s 量级耗时，未触发）；未使用 GPU；未占用额外大额磁盘。

---

## 3. 参考源码 SHA 和工作副本状态

参考仓库（只读）：

- 上游：`https://github.com/iidyc/DiskJoin`
- 固定提交：`aa86151f97527b1dcf9a032d523c1d67d892454a`（提交信息 `fix anonymous github issue caused by file names`，2025-06-08）
- `git -C reference/DiskJoin rev-parse HEAD` → `aa86151f97527b1dcf9a032d523c1d67d892454a`，与预期一致 [实验观察]
- `git -C reference/DiskJoin status --short` → 输出为空（clean）；在本轮所有构建/运行结束后复核仍为空 [实验观察]
- 交叉来源：Gate 0–1 阶段的固定提交 tarball（`workspace/source_snapshot/`）经 Git blob SHA-1 与提交 tree 42/42 文件比对一致 [实验观察]

构建/工作副本安排：

| 副本 | 路径 | 状态 |
|---|---|---|
| 参考源码（只读） | `reference/DiskJoin` | 全程未修改；构建为 out-of-tree（`workspace/build`） |
| 隔离插桩副本 | `workspace/instrumented/DiskJoin` | 由 `git archive HEAD` 从固定 SHA 导出（分支级干净基线），仅添加只读统计/打印；out-of-tree 构建 `workspace/build_instr` |
| 插桩补丁 | `workspace/patches/gate2_instr.patch` | 104 行 unified diff，覆盖 `lib/DiskJoin.h` 与 `lib/Kmeans.h` 两个文件（见 §10） |

---

## 4. C++ 实际执行流程

### 4.1 端到端调用链（均为固定 SHA 源码直接读取 [源码已检查]）

```
expr/main.cpp:4-13
  ConfigReader(argv[1])                        # 配置解析
  DiskJoin::build  (lib/DiskJoin.h:12-14)      # → one_level_kmeans
  timer.tuck("Build done")                     # stdout 打印 Build 耗时
  DiskJoin::search (lib/DiskJoin.h:16-157)     # → bucket 图 + Gorder + cache + join
  timer.tuck("Join done")                      # stdout 打印 Join 累计耗时
```

Input Data → Bucketization → Bucket Graph / Candidate Tasks → Gorder Reordering → Belady Cache → Join Execution 的实际代码路径如下。

### 4.2 模块 1：Bucketization（build 阶段）

入口 `one_level_kmeans`（`lib/Kmeans.h:165-219`）：

| 步骤 | 代码位置 | 说明 |
|---|---|---|
| 读 fbin 头 | `DataReader`（`lib/ClusterIO.h` / `utils`） | 取 n、d；分批读取（n/1000=12/批） |
| 采样初始化中心 | `lib/Kmeans.h:172-191` | `std::srand(283)` + `random_shuffle` 固定随机；取 120 个采样向量为中心 |
| 中心上建 HNSW | `lib/Kmeans.h:192-201` | `HierarchicalNSW(space, cluster_num, 20, 100)`；`saveIndex` 写 `toy.hnsw` |
| 2-choice 分配 | `Kmeans::add2choice`，`lib/Kmeans.h:127-146` | 每向量 HNSW top-2 候选；若第一名桶小于第二名桶且距离比 <1.2 则选较小桶（132-137 搜索，139-144 均衡规则） |
| 写桶文件 | `ClusterWriter::writeClusters`，`lib/ClusterIO.h:43-99` | `max_points` 统计(46-55)；按 mem_budget 分页缓冲(58)；各桶连续布局 `file_pos`(63-67)；`radii[i]=sqrt(...)`(97) |
| 写元数据 | `ClusterWriter::writeMetadata`，`lib/ClusterIO.h:101-114` | 顺序写 n、d、cluster_num、max_points、bucket_sizes、centroids、radii、各桶 assignment |

运行前提：`cluster_num ≤ n`；fbin 头与实际数据一致；输出路径可写；`mem_budget > 0`。

### 4.3 模块 2：Bucket Graph / Candidate Tasks（search 阶段前半）

`lib/DiskJoin.h:46-83` [源码已检查]：

- `#pragma omp parallel for` 对每个桶做 `graph->knnSearchBaseLayer(i, config.K)`（48），取 K=24 个近邻桶；
- 距离减半后经 `arcos` 反余弦查表转成角度（41-45, 49-55），按角度从小到大排序（56）；
- 角度和达到 `error_bound=0.1` 即截断（59-63）——候选对筛选依据是 **HNSW KNN + 角度概率截断**，并非论文 Eq.(1) 的三角不等式（已知 mismatch，Gate 3 必查）；
- 仅保留上三角（i ≤ j）形成任务列表（64-68），排序（69）；
- 若任务为空且存在非零距离候选则 `exit(0)` 静默退出（70-74）——风险路径，本轮 `empty_tasks=0` 未触发 [实验观察]；
- 统计 `task_num` 与 `max_task_num`（79-83），同时按 `max_points × d` 决定缓冲槽位大小（95）。

### 4.4 模块 3：Gorder Reordering

调用点 `lib/DiskJoin.h:96`：`order_gorder(shuffled_tasks, budget/4/length/config.K*2)`。

- 实现 `lib/Gorder.h:60-103`：UnitHeap 贪心排序，返回 rank 置换；主路径据此重排任务（`lib/DiskJoin.h:97-99`）。
- `move_window`（`lib/Gorder.h:9-58`）维护窗口内 sibling 度数增减；**注意**：第 15、44、50、53 行的父节点 `lazyIncrement` 被注释掉，与经典 Gorder 实现存在可审计差异 [源码已检查]。
- 窗口长度实测参数：`budget/4/length/K*2 = 5429/24×2 ≈ 452`（向零取整 `ul`）> `cluster_num=120`，因此 toy 上窗口"移出最旧节点"分支不会触发，Gorder 退化为全局贪心 [推断，基于 §8 观察到的容量参数]。

### 4.5 模块 4：Belady Cache —— 论文 Algorithm 1 对照框

论文 Algorithm 1 标题为 **“Cache Management via Belady’s Algorithm”**（arXiv v2 文本抽取行 1005；正文 1078-1095 说明：未来访问序列、索引数组 P、第 12 行淘汰、扫描 S）[论文 + 文本抽取]。实际代码映射：

| 论文 Algorithm 1 元素 | 实际代码（固定 SHA）[源码已检查] | 本轮观察 [实验观察] |
|---|---|---|
| 预计算未来访问序列 / P 索引数组 | `Cache::init`，`lib/Cache.h:30-42`：扫描 reordered_tasks 生成每桶未来访问序号表 `iters` 与游标 `ptr`；`address_table` 初始化 −1 | init 后 `capacity_slots=5429`（`size=budget/4/length`，`lib/Cache.h:22`；槽位=一组 `length=4944` float，实际内存 `4×length×size ≈ budget ≈ 107,363,904 B`） |
| 查找（命中/未命中） | `Cache::find`，`lib/Cache.h:44-52`：`total++`(45)；未命中 `address_table[id]==-1` → `false`(47)；命中 `hit++`(48)、更新 updateable_heap(49)、`memcpy` 回填(50) | `accesses=459 hits=339 misses=120`（计数器是参考代码原生态字段，`lib/Cache.h:13-15,45,48`） |
| 插入 | `Cache::push`，`lib/Cache.h:54-59` | `filled_slots=120` |
| Belady 淘汰（下次访问最远者） | `Cache::push`，`lib/Cache.h:60-65`：堆顶为"下次使用最远"，新桶下次访问更近时替换地址表 | **0 次淘汰**（filled 120 ≪ 5429） |
| 主路径调用点 | `lib/DiskJoin.h:105-106`（构造+init）、`117-119`（find → miss 则 O_DIRECT 直读 + push） | 120 次 miss 与 120 次直读一一对应 |

一致性初判 [源码已检查]：代码语义与"预计算未来访问、淘汰下次使用最远者"的 Belady 描述一致；但与论文的**任务粒度差异**（论文按"边的两个 bucket"描述，代码按"目标桶一次批量加载其全部候选桶"）留待 Gate 3 审计确认。`LRUCache`（`lib/Cache.h:74` 起）存在于源码但不在主执行路径上 [源码已检查]。

### 4.6 模块 5/6：Join Execution 与结束

`lib/DiskJoin.h:112-155` [源码已检查]：

- 任务主循环（112-121）：对 `order[i]` 的每个 neighbor 依次 `cache.find`；miss 时 `cluster_reader.posixDirectReadCluster`（`lib/ClusterIO.h:191-201`：O_DIRECT fd 于 154 打开，`aligned_alloc(PAGE_SIZE,…)` 页对齐缓冲 183，逐次 `lseek`/`read` 198-199，返回值未检查）+ `cache.push`；
- 空目标桶跳过（123）；
- Self-join（124-138）：`dist_l2`（平方 L2，`lib/ClusterIO.h:15` = `utils::L2Sqr`），`id2 >= id1` 去重（130），`dist < epsilon²` 判 `epsilon=sqrt(radius)`（17, 134）；
- Cross-bucket（140-153）：`vec1` 对所有候选桶向量计算；
- 采样计数：`id % 100000 == 0` 的端点累加（135-136, 149-150）；Recall 打印 `count / config.gt`（156）。

风险检查表（对应任务书 §2 的 8 项检查）：

| # | 风险 | 代码事实 [源码已检查] | toy 观察 [实验观察] | 状态 |
|---|---|---|---|---|
| 1 | cluster_num/K/规模约束 | K=24 < cluster_num=120 ≤ n=12000 | task_num=459, max_task_num=10 | 未触发 |
| 2 | 空桶/异常分配 | `add2choice` 均衡规则；无 kmeans 迭代（`train` 未被调用） | 120/120 非空，最小桶 3 | 未触发 |
| 3 | Gorder 窗口过长 | window ≈ 452 > 120 | 重排仍发生（首 8 项 6,10,29,42,46,54,76,84，非恒等） | 窗口退化但不影响 smoke |
| 4 | cache 预算/边界 | 容量 5429 槽 ≈ budget 字节 | filled=120，0 淘汰 | 容量充裕 |
| 5 | O_DIRECT 对齐 | 逐读 4096 对齐（`PAGE_SIZE`，`div_round_up`） | aligned 1,253,380 B vs effective 768,000 B（≈1.63× 放大） | 正常 |
| 6 | 维度/文件头 | fbin 头 n=12000, d=16；metadata 头一致 | 校验通过（见 §5） | 正常 |
| 7 | 未初始化/越界/退出路径 | `exit(0)`(73)、`aligned_alloc`/`delete[]` 不匹配(183/207)、`read` 未查返回值(199) | exit 0、stderr 0 B、无崩溃 | 未触发，UB 保留记录 |
| 8 | 小数据采样 recall 有效性 | 仅 ID 0 参与（12K 内 100000 倍数只有 0） | sampled_matches=599 == config.gt=599 → recall=1 | 只能作 smoke 判据，**非全量 recall** |

---

## 5. 数据集与实验配置

数据生成：`scripts/make_toy.py`（复现包自带，Gate 0–1 阶段已审查脚本内容后使用）[源码已检查 + 实验观察]：

| 参数 | 值 |
|---|---|
| 类型 | Synthetic（20 类高斯混合） |
| 向量数 n | 12,000 |
| 维度 d | 16 |
| 数据类型 | float32 |
| 随机种子 | 283（生成器固定） |
| ε | 0.25 |
| radius（= ε²） | 0.0625（config 字段 `radius`） |
| 采样 GT | 599（sample_ids=[0]，即仅 ID 0） |
| cluster_num | 120 |
| K | 24 |
| mem_budget | 0.1（GiB， toy 专用小预算；未复用 100M 数据集配置） |
| error_bound | 0.1 |
| gt | 599 |

`workspace/toy/toy.config` 全文 [源码已检查]：

```text
data_file        /home/qch/DiskJoin/diskjoin_repro_pack/workspace/toy/toy.fbin
radius           0.0625
cluster_num      120
cluster_file     /home/qch/DiskJoin/diskjoin_repro_pack/workspace/toy/toy.clusters
metadata_file    /home/qch/DiskJoin/diskjoin_repro_pack/workspace/toy/toy.metadata
hnsw_file        /home/qch/DiskJoin/diskjoin_repro_pack/workspace/toy/toy.hnsw
K                24
mem_budget       0.1
error_bound      0.1
gt               599
```

输入完整性检查（`python3` struct 解析，全部 [实验观察]）：

| 检查项 | 结果 |
|---|---|
| fbin 文件大小 | 768,008 B（= 8 B 头 + 12000×16×4 B） |
| fbin 头 | n=12000, d=16 |
| float 值 | 192,000 个；非有限值 0；min −3.062，max 3.034 |
| fbin SHA-256 | `a98328f1a0e6518decd66d5f6527ad37c559d6f46d828c7b5335487d24503c9d` |
| toy.config SHA-256 | `5bab39950881de79eec931b5dbfcf4579bd3d04dfd321d4c09c0bf581dd07b93` |
| metadata 头 | n=12000, d=16, cluster_num=120, max_points=309 |
| bucket_sizes | min=3, max=309, sum=12000, 非空 120/120 |
| radii | min 0.108636, max 0.166852, mean 0.128586 |
| 与 DataReader 一致性 | ClusterReader 解析成功并驱动了完整 join（见 §8） |

可重复性：种子固定；两次重复运行 `recall` 一致（§7）。注意 `one_level_kmeans` 中 `std::srand(283)` 也是源码内写死的（`lib/Kmeans.h:175`），与 toy 元数据记录的种子一致 [源码已检查]。

---

## 6. 编译命令、结果和退出码

参考构建（干净 out-of-tree，`scripts/run_smoke.sh` 内部步骤 19-20 [源码已检查脚本]）：

```bash
cd /home/qch/DiskJoin/diskjoin_repro_pack
OMP_NUM_THREADS=4 BUILD_JOBS=4 bash scripts/run_smoke.sh   # 总退出码 0
# 等价编译命令：
cmake -S reference/DiskJoin -B workspace/build
cmake --build workspace/build -j 4                          # 均 exit 0
```

- 编译器/选项 [实验观察 + 源码已检查]：GNU 11.4.0；CMAKE_BUILD_TYPE=Release；`-O3 -DNDEBUG -mtune=native -mavx2 -pthread -mfma ... -fopenmp -std=c++11`（`reference/DiskJoin/CMakeLists.txt:5,16-18`）；OpenMP 4.5。
- 告警：仅 CMake 2.8 兼容性弃用告警（`CMakeLists.txt:1`）；`-lboost` 出现在 compile definitions 但链接成功 [实验观察]。
- 二进制：`workspace/build/main`（ELF 64-bit x86-64，224,064 B）[实验观察]。

插桩构建（隔离副本，同样 out-of-tree）[实验观察]：

```bash
cmake -S workspace/instrumented/DiskJoin -B workspace/build_instr
cmake --build workspace/build_instr -j 4    # exit 0
# 完整日志：workspace/logs/instr/build_instr.log（无警告/错误退出码差异）
```

二进制：`workspace/build_instr/main`（232,408 B）。无编译失败，因此本轮无需任何构建修复；参考源码零改动（构建失败时的修复流程未启用）。

---

## 7. 运行命令、时间、资源及日志

四次运行（命令逐字 [实验观察]）：

| # | 命令 | 二进制 | 输出目录 | 退出码 |
|---|---|---|---|---|
| R1 | `OMP_NUM_THREADS=4 BUILD_JOBS=4 bash scripts/run_smoke.sh` | `workspace/build/main` | `workspace/runs/toy-jw4eXS/` | 0 |
| R2 | 同上（重复一致性检查） | `workspace/build/main` | `workspace/runs/toy-65b1dv/` | 0 |
| R3 | `OMP_NUM_THREADS=4 timeout 300 /usr/bin/time -v -o workspace/runs/gate2-ref-run1/time.log ./workspace/build/main workspace/toy/toy.config > …/stdout.log 2> …/stderr.log` | `workspace/build/main` | `workspace/runs/gate2-ref-run1/` | 0 |
| R4 | 同 R3，但 `./workspace/build_instr/main`，输出到 `workspace/runs/gate2-instr-run1/` | `workspace/build_instr/main` | `workspace/runs/gate2-instr-run1/` | 0 |

R1/R2（来自 `summary.json`，in-process Timer）：

| 项 | R1 | R2 |
|---|---|---|
| Build 耗时 | 0.0560715 s | 0.0557985 s |
| Join 累计耗时 | 0.0836922 s | 0.0964714 s |
| 采样 Recall | 1.0（GT 599） | 1.0 |
| 状态 | `PASS_SMOKE_ONLY` | `PASS_SMOKE_ONLY` |
| stderr | 0 B | 0 B |

R3/R4（GNU time -v，[实验观察]）：

| 项 | R3（参考二进制） | R4（插桩二进制） |
|---|---|---|
| Build/Join stdout | `[0.057198 s] Build done`、`recall = 1`、`[0.083429 s] Join done` | `[0.0580773 s] Build done`、`recall = 1`、`[0.0875891 s] Join done` |
| wall clock | 0:00.08 | 0:00.09 |
| user / sys | 0.28 s / 0.01 s | 0.29 s / 0.03 s |
| CPU 占比 | 348% | 351% |
| 最大 RSS | 9,508 KB | 9,508 KB |
| Major page faults | 0 | 0 |
| FS inputs / outputs | 2448 / 1784 | 2448 / 1784 |
| 退出状态 | 0 | 0 |

程序实际产出的文件（Build 阶段）[实验观察]：

| 文件 | 大小 |
|---|---|
| `workspace/toy/toy.clusters` | 768,000 B |
| `workspace/toy/toy.metadata` | 105,152 B |
| `workspace/toy/toy.hnsw` | 29,448 B |

关键日志路径（供审计）：

- `workspace/logs/gate2_run_smoke_console.log`（R1 完整控制台）
- `workspace/logs/gate2_run_smoke_repeat.log`（R2 完整控制台）
- `workspace/runs/gate2-ref-run1/{stdout.log,stderr.log,time.log}`
- `workspace/runs/gate2-instr-run1/{stdout.log,stderr.log,time.log}`
- `workspace/logs/instr/build_instr.log`（插桩构建）
- `workspace/runs/toy-jw4eXS/`、`workspace/runs/toy-65b1dv/`（脚本化运行快照：stdout/stderr、config.snapshot、reference_commit.txt、summary.json）

未发生超时、Segmentation Fault、内存分配失败或 I/O 错误；故障诊断流程未启用。

---

## 8. 各关键模块执行路径的验证证据

验证方法：在隔离插桩副本（`workspace/patches/gate2_instr.patch`）添加只读计数与打印后运行 R4。其中 `cache.total/hit/filled/size` 与 `cluster_reader.total/used` 均为**参考代码原生态计数器**（`lib/Cache.h:13-15,21-27,45,48`；`lib/ClusterIO.h:144-145,196-197`），插桩仅读取现成字段，不改变其行为 [源码已检查]。

R4 完整 stdout [实验观察]：

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

模块判定表：

| 模块 | 最小验证要求 | 证据 | 判定 |
|---|---|---|---|
| Bucketization | 实际生成 Bucket 和元数据 | 120/120 非空、12,000 全部分配、max 309；三个输出文件存在且可被 ClusterReader 解析 | **PASS** |
| Bucket Graph | 实际生成非空候选任务 | task_num=459、empty_tasks=0、max_task_num=10 | **PASS** |
| Gorder | 排序函数被调用并产生有效排列 | 置换无重复（dedup 检查 dup=0）且首 8 项 6,10,29,42,46,54,76,84 ≠ 恒等排序 | **PASS** |
| Belady Cache | 初始化、查找和插入路径得到执行 | init 完成；accesses=459、hits=339、misses=120、filled=120（insert 执行）；`priority` 堆路径可用（本次容量内未触发淘汰分支） | **PASS** |
| Join Execution | 实际执行有效的向量距离比较 | dist_comp≈3.594e6（>0）；sampled_matches=599 == config.gt | **PASS** |
| End-to-end | 构建和 Join 正常结束 | exit 0、`Build done`/`Join done`、stderr 0 B | **PASS** |

补充计量 [实验观察]：

- 处理的 bucket 数：120/120（`buckets_processed=120`）；
- 逻辑 bucket pair 数（任务）：459；
- cache hit/miss：339/120（0 次淘汰，`filled=120 < capacity=5429`）；
- O_DIRECT 读：120 次，与 120 个 miss 一一对应；对齐读 1,253,380 B，有效数据 768,000 B（=12000×16×4 B，说明全部向量的桶数据确实从盘上读出而不是凭空产生）；
- 距离计算：`dist_comp` 为 float 归约变量（`lib/DiskJoin.h:111,124`），打印值是浮点近似而非精确整数 [源码已检查]。

`UNVERIFIED`（不得写成已验证）：

- Gorder/ cache 行为的**收益**（重排是否减少 miss、淘汰是否改善 I/O）：本次 cache 装下全部桶、0 淘汰，无法度量任何收益 [推断 + 实验观察]；
- 淘汰分支（`Cache::push` 60-65 行）在 toy 上未执行，其正确性未验证 [实验观察]；
- SSD 物理读次数/字节数（页面缓存未旁路，`aligned` 只是程序请求量）；
- HNSW `knnSearchBaseLayer` 返回的确切邻居（未打印）。

两个非插桩运行（R3 的 `recall = 1` 与 R1/R2 一致）交叉确认：插桩未改变程序可观察行为（Build/Join 输出格式与 recall 一致）[实验观察]。

---

## 9. 发现的问题与最小修复

**未发生任何需要修复的失败。** 构建 0 次、运行 4 次全部成功。以下是本轮"发现 + 决策"清单（均为只读发现，未修参考源码）：

| # | 问题 | 证据 | 决策 |
|---|---|---|---|
| 1 | CMake 弃用告警（`cmake_minimum_required(2.8)`） | R1 输出 [实验观察] | 不修：非阻塞；不动参考仓库 |
| 2 | `ClusterReader::buffer` 以 `aligned_alloc` 分配（ClusterIO.h:183）却用 `delete[]` 释放（207） | [源码已检查] | 不修：UB 风险仅记录（本轮未崩溃）；隔离副本修复留给后续 gate |
| 3 | `lseek`/`read` 返回值未检查（ClusterIO.h:198-199），短读可能静默 | [源码已检查] | 不修（同上）；make_toy 校验对齐/文件头规则避免了本条件 |
| 4 | 候选为空且非零距离时 `exit(0)`（DiskJoin.h:70-74），可能静默无 recall 输出 | [源码已检查] | 不修；R4 显示 `empty_tasks=0` 未触发 |
| 5 | 候选过滤是 HNSW KNN+角度截断，非论文 Eq.(1) 三角不等式 | [源码已检查] + [论文] | 不修；属 Gate 3 论文-代码对齐审计项 |
| 6 | Gorder.h 内多处 `lazyIncrement` 被注释（15/44/50/53） | [源码已检查] | 不修；Gate 3 对照 Algorithm 2 |
| 7 | `recall` 采样口径（id%100000） | [源码已检查] + [实验观察] | 无需修复：行为如设计，但语义必须在报告中限定 |
| 8 | `dist_comp` 用 float 归约导致计数为近似值 | [源码已检查] | 仅记录；不影响 smoke 判定 |

插桩本身（隔离副本内新增，见 §10）：只读计数器（`empty_tasks`、`dup/seen`、`io_count`、`processed_buckets`）+ 6 条 `std::cout` 打印；不改变候选生成、排序、缓存决策或距离计算；唯一新增内存是 `seen` 计数向量与少量局部变量 [源码已检查 patch]。

---

## 10. Git Diff / 补丁路径

- 补丁文件：`workspace/patches/gate2_instr.patch`（104 行，unified diff）
- 生成方式 [实验观察]：

```bash
cd /home/qch/DiskJoin/diskjoin_repro_pack
diff -ruN --exclude=.git --exclude=datasets --exclude=configs \
     --exclude=scripts --exclude=utils --exclude=README.md --exclude=.gitignore \
     reference/DiskJoin workspace/instrumented/DiskJoin \
     > workspace/patches/gate2_instr.patch
```

- 覆盖面：仅 2 个文件——`lib/DiskJoin.h`（+3 段打印/计数：bucket_graph 统计、gorder 置换校验打印、cache/io/compute 汇总打印）与 `lib/Kmeans.h`（+1 段 bucketization 统计打印）。`lib/Cache.h`、`lib/ClusterIO.h`、`lib/Gorder.h` **未被修改**（统计直接读取参考代码既有字段）[实验观察 + 源码已检查]。
- 关系到基线：patch 的两侧为 `reference/DiskJoin`（固定 SHA，clean）与 `workspace/instrumented/DiskJoin`（由 `git archive HEAD` 导出的同一提交内容）。
- 参考仓库完整性复核（补丁生成与运行之后）：`git -C reference/DiskJoin rev-parse HEAD` = 固定 SHA；`git status --short` 为空 [实验观察]。

---

## 11. Gate 2 PASS / PARTIAL / FAIL / BLOCKED

**判定：PASS（smoke 级，`PASS_SMOKE_ONLY`）。验证等级：smoke，非 mechanism_ablation，非 paper_level。**

逐条对照判定条件：

| # | 条件 | 满足情况 | 证据 |
|---|---|---|---|
| 1 | 固定版本源码及所有必要修改可追溯 | 满足：固定 SHA clean；插桩以补丁形式可追溯 | §3, §10 [实验观察] |
| 2 | C++ 程序成功编译 | 满足：两次构建 exit 0 | §6 [实验观察] |
| 3 | 12K×16D 输入通过格式与完整性检查 | 满足：头/大小/数值/哈希 | §5 [实验观察] |
| 4 | Bucketization、候选任务、Gorder、Cache、Join 路径实际执行 | 满足：6 模块全部有专门插桩证据 | §8 [实验观察] |
| 5 | 有效向量距离计算，无静默跳过 | 满足：dist_comp≈3.59e6>0；sampled_matches=599=gt | §8 [实验观察] |
| 6 | 程序正常退出，无未解释错误 | 满足：4 次运行 exit 0，stderr 0 B | §7 [实验观察] |
| 7 | 保留完整命令、日志、退出码、配置 | 满足：命令逐字留档（§6–§7、HANDOFF §4） | [实验观察] |
| 8 | 可通过明确步骤重复执行 | 满足：见 §6–§7 + HANDOFF 附录 B；R1/R2 复现一致 | [实验观察] |

**PASS 不代表**：join 结果正确、recall 语义为全量、实现与论文完全一致或论文性能已复现。

重复实验（明确步骤）：

```bash
cd /home/qch/DiskJoin/diskjoin_repro_pack
python3 scripts/make_toy.py                       # 若 toy.fbin 不存在（幂等）
OMP_NUM_THREADS=4 BUILD_JOBS=4 bash scripts/run_smoke.sh          # 参考链路，run 目录自动生成
cmake -S workspace/instrumented/DiskJoin -B workspace/build_instr # 插桩链路
cmake --build workspace/build_instr -j 4
OMP_NUM_THREADS=4 timeout 300 ./workspace/build_instr/main workspace/toy/toy.config
git -C reference/DiskJoin status --short          # 应为空
```

---

## 12. 尚未验证的正确性问题

以下全部留给 Gate 3/4，不得声称已验证：

1. **全量 join 正确性**：未独立枚举输出对与 GT；采样 recall=1.0 只覆盖 ID 0 的对（代码采样口径 `id % 100000 == 0`，`lib/DiskJoin.h:135-136,149-150`）。在 n ≥ 100000 时，若一对的两个端点均为 100000 倍数会被**计数两次**——GT 生成器必须同口径，Gate 3 必查 [源码已检查 + 推断]。
2. **候选集完备性**（ε-邻域不被 KNN/角度截断漏掉）：未验证。空任务 `exit(0)` 路径正确性未验证 [源码已检查]。
3. **缓存淘汰分支正确性**：toy 容量装下所有桶，`Cache::push` 的替换分支未执行，正确性未验证；LRU/Belady 对比（消融）未做 [实验观察 + 推断]。
4. **自连接桶内数据来源断言缺失**：join 假定 `target_tasks[0]` 为目标桶自身，无断言；交叉桶比较假定邻居数据在缓冲槽 k 对应位置（`data + k*length`）[源码已检查]。
5. O_DIRECT 短读/非对齐路径的防御性行为（`read`/`lseek` 返回值未检查）[源码已检查]。
6. `aligned_alloc`/`delete[]` 释放不匹配的 UB 在更大/更碎的负载下是否成为实际缺陷 [源码已检查]。
7. 多线程归约正确性/确定性与 timing 完整性（仅 smoke 观察 recall 稳定；结果集未逐对比对）。
8. Gorder 对 miss 率/缓存行为的**收益**（窗口退化时的全局贪心是否有效）。
9. 参考代码与 arXiv v2 各章节（§3–§5、§6.5 消融及 Algorithm 1/2 细节）的逐条一致性；正式版 PACMMOD PDF（27 页）尚未取得。
10. 论文性能（50×–1000×）与 10M/100M/SPACEV1B 结果的可复现性。

---

## 13. Gate 3 的建议验证方案

性质：只读审计，不跑新的大作业（不看 10M/100M）。

范围：逐行对照 `reference/DiskJoin/lib/{DiskJoin,Gorder,Cache,Kmeans,ClusterIO,ConfigReader}.h`、`expr/main.cpp`、`CMakeLists.txt`、`lib/hnswlib/hnswalg.h`（仅审计被调用的 `knnSearchBaseLayer` / `searchBaseLayerST` 路径）与 arXiv v2 §3–§5、§6.5。

必答问题：

1. **Algorithm 1（Belady cache）**：论文的 P/Q/S 语义与 `lib/Cache.h:30-67` 是否逐条同构（本报告 §4.5 已给出初步映射，待逐行核对）；论文"每条边两个 bucket"与代码"目标桶批量加载全部候选"的差异对 cache miss 统计的影响。
2. **Algorithm 2（Gorder）**：`move_window` 中被注释的 `lazyIncrement`（Gorder.h:15/44/50/53）对结果分布的影响；窗口公式 `budget/4/length/K*2` 与论文描述是否一致。
3. **候选过滤**：代码的 HNSW KNN + 角度概率截断（`error_bound`）与论文 Eq.(1) 三角不等式的差异、以及二者对 recall 上界的理论影响。
4. **采样口径**：GT 生成与代码计数口径在 n≥100000 双端点采样时的重复计数问题；提出独立 GT 方案（理想：单独脚本全量枚举 12K 的 ε-邻居对，比对 recall）。
5. **UC 条目**：`aligned_alloc`/`delete[]`、未检查 `read`/`lseek`、`exit(0)` —— 给出"如果 Gate 4 需要修，如何在隔离副本中修"的最小补丁草案（不触碰参考仓库）。
6. 为消融（Gate 4）定义公平基线：固定数据、ε、bucketization、候选任务、线程亲和、测量口径；Gorder-off（用恒等置换替换 `perm`）、Belady→LRU（`LRUCache` 与主路径接口是否可平替）。

成功标准：输出一份 mismatch 清单（逐条含证据行号）、消融前所需的补丁草案和独立 GT 生成方案。

停止条件：源码与论文机制无法对齐处先报告 mismatch，不进入 Gate 4；任何消融改动仅允许在隔离副本 + patch；Gate 4 开始前需要用户**单独明确授权**。

---

## 附：与 HANDOFF/REPORT 的关系

- 本报告是 Gate 2 的完整技术记录；`workspace/REPORT.md` 是跨 gate 的阶段摘要；`workspace/HANDOFF.md` 在 Gate 0–1 内容基础上追加了 Gate 2 章节（含插桩证据索引）。
- 原始包完整性：`sha256sum -c SHA256SUMS` 22/22 OK（未修改既有文件）。
