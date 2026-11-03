# DiskJoin Gate 5A-R：本地修复与服务器验证包

状态：本地修复完成，Linux BigANN100K 验证待执行。当前没有修正后的真实数据 Recall，也没有 Gate 5B GO 结论。

## 范围及来源

所有新文件位于本目录。`instrumented/DiskJoin/` 从 Gate 5A 隔离副本复制；它继承此前的计数探针、缓存策略及堆/泄漏修复。此次只改变其中 `lib/hnswlib/hnswalg.h`。冻结上游 SHA 为 `aa86151f97527b1dcf9a032d523c1d67d892454a`；本机工作仓库起始 HEAD 为 `6d4a99565151911ac3ed41fa2f33e9faa8c398fb`。未改此前报告，未执行 Git commit/push/reset/clean。

`frozen_before.json` 记录修改前 2,071 个既有文件的 SHA-256；`scripts/check_static.py` 校验其内容保持不变。构建与临时文件均落在本目录的 `build/`，历史 Gate 的数据、源码和日志不作输出路径。

## 文件和修复

| 路径 | 作用 |
|---|---|
| `oracle/gt_calib.cpp` | 读取每条 LE uint32 维度头后，仅存储 128 字节载荷；calib/gt 均处理完整 128 维；严格 `< m²`，int32 距离最大 8,323,200；检查截断、维度、端点 ID、重复 ID 和输出覆盖。数据上限 100K。 |
| `oracle/sample_endpoints.py` | 固定不同种子；2,000 校准端点与 200 评估端点互斥；0 单独诊断；记录 Python 版本、种子、设计和文件哈希。 |
| `oracle/evaluate.py` | 验证 split/GT、全量输出 pair 的合法性和重复；按完整端点 bootstrap 5,000 次，输出三类指标和百分位区间；空 GT 端点的 FP 同样检查。 |
| `oracle/independent_check.py` | 从 fbin 独立解析；完整核对所有坐标的 bvecs→fbin 转换；以范数/点积公式核对 0 和三个评估端点的完整邻域。 |
| `instrumented/DiskJoin/lib/hnswlib/hnswalg.h` | 将 17 个预取块归入有界 helper；检查逻辑 degree、lookahead 下标、live ID 及 visited+64；消费非法邻居时停止；另修复本地 UBSan 暴露的标签对齐问题。 |
| `tests/test_correctness.py` | 10 个单元/CLI 测试，含旧 Oracle 缺陷重现、末四维反例、独立距离交叉验证、采样和统计边界。 |
| `tests/hnsw_regression.cpp` | 空表、level-0/高层满表、非法 ID/degree、visited 尾部、构建/查询/更新等回归。 |
| `scripts/run_local.sh` | Python/C++ 单测、静态检查与 Mac 标量 ASan+UBSan。 |
| `scripts/run_linux.sh` | Linux AVX2/FMA 预检、已有数据验证、GT、独立交叉核对和三个构建的有界回归。 |
| `scripts/validate_run.py` | 三种构建逐文件比对、历史输出回归、关键不变量、诊断计数、RSS 上限检查。 |
| `patches/` | Oracle、采样器、HNSW 增量补丁及冻结上游到完整隔离副本的累计补丁。见 `PATCHES.md`。 |

## 抽样与统计协议

1. 从 `{1,...,99999}` 无放回抽取 2,000 个校准端点，种子 `2026110301`。
2. 从校准补集无放回抽取 200 个评估端点，种子 `2026110302`。两个集合严格互斥。0 的 GT 和命中仅进入 `diagnostic_zero`。
3. 本次保持旧配置 `m=272, radius=73984, cluster_num=1000, K=24, eb=0.1, cache configuration budget=5,120,000 B`，隔离正确性修复。重新输出校准密度，**不自动选择新阈值**，不沿用“平均 100.46”的旧结论。若需重新选阈值，应另行冻结协议，不能通过查看评估 Recall 调参。
4. 对每个评估端点保存 `GT/TP/FP/predicted`。邻居加权 Recall 为 `ΣTP/ΣGT`；非空端点平均 Recall 为 `mean(TP_e/GT_e | GT_e>0)`；Precision 为 `ΣTP/Σpredicted`。同一 pair 被两个采样端点命中时保留两次 incidence，统一采用端点口径。
5. Bootstrap 种子 `2026110303`；每次有放回抽取 200 个完整端点，包含零邻居端点，再计算上述三个统计量。报告 2.5%/97.5% 百分位、未定义 replicate 数、区间退化标记。少于 95% replicate 有定义，或点估计未定义时停止。

区间属于条件近似：固定校准划分、阈值、数据和图；推断总体为非零校准补集。它不覆盖校准端点/0 的总体贡献、图构建随机性、数据集间变异或完整 join 的精确 Recall。重尾、端点间共享 pair 和有限端点数仍可能影响覆盖；没有 95% 有限样本保证，也未作有限总体校正。未观察到 FP 时 Precision 的退化 `[1,1]` 区间无法排除总体中的稀有 FP。详细限制随 JSON 输出保存。

## 本地验证

```bash
bash workspace/gate5ar/scripts/run_local.sh
```

已验证环境：Darwin arm64、Apple clang++、Python。最终结果见 `logs/local_validation_complete.log`：10/10 单测通过，静态检查通过，标量 HNSW ASan+UBSan 通过，digest `12385809373267807141`；所有 2,071 个既有文件哈希不变。

Mac 上定义 `NO_MANUAL_VECTORIZATION`，因此 SSE 指令分支、AVX2/FMA、OpenMP、Linux O_DIRECT 和 BigANN100K 端到端回归均**尚未验证**。`logs/linux_platform_guard_mac.log` 仅验证脚本在 Mac 拒绝启动。

失败证据保留：最初 harness 的 searchKnn 参数签名用错，编译日志为 `logs/hnsw_build_mac.log`；改正 harness 后，`logs/local_validation_01.log` 暴露标签写入的 alignment UB。使用已有 `setExternalLabel()` 字节地址写入后，02/03/final 回归通过。这些局部失败不代表 Linux 测试结果。

## Linux 服务器执行

从复现包目录 `diskjoin_repro_pack/` 执行，替换输入路径。服务器需已有 g++、CMake、OpenMP、GNU timeout、GNU time、Python3 和 BigANN100K；脚本不安装依赖、不下载数据、不改服务器设置。

```bash
bash workspace/gate5ar/scripts/run_linux.sh \
  /absolute/path/to/bigann100k.bvecs \
  /absolute/path/to/bigann100k.fbin \
  server_validation_01
```

默认历史 baseline 为 `workspace/gate5a/runs/r1_default/` 的 knn/tasks/pairs/trace。若保存在其他位置，用 `BASELINE_DIR=/absolute/path/to/r1_default` 指定。缺失 baseline 或已存在同名新运行目录时，脚本立即停止。

执行顺序：

1. Linux x86_64、原生 AVX2/FMA、工具、至少 2 GiB 空闲磁盘/可用 RAM 检查；验证已有 bvecs/fbin 的已记录 SHA-256；记录源码文件哈希。
2. 运行单测；编译修正 Oracle；生成新 split，输出完整维度校准表、评估 GT 和诊断 GT；独立检查全部转换及四个完整邻域。
3. 分别构建安全预取 normal、ASan+UBSan、`GATE5AR_DISABLE_PREFETCH` 版本；执行原生 SIMD HNSW harness 和 100K join。OMP=1，构建最多 4 jobs；Oracle 校准最多 4 线程。
4. 三种构建的四个 dump 和 clusters/metadata/hnsw 逐文件 SHA-256 相同；与历史 Gate 5A 的四个 dump 相同；检查不变量、0 诊断计数与 GT，以及每次 join RSS。任一异常立即停止，保留完整输出。
5. 对 normal 输出生成 `evaluation.json`，重新计算三个指标和端点 bootstrap 区间；最后复核输入数据哈希不变。

输出全部位于 `workspace/gate5ar/runs/server_validation_01/`：输入/源码清单、构建目录、编译命令与日志、每步骤 GNU time/RSS、split、校准表、GT、normal/asan/prefetch_off 各自配置和数据/日志、比较结果及 `evaluation.json`。

资源估计（待服务器实测）：网络 0；新增磁盘预计 0.5–2 GiB；实际 RSS 预计低于 2 GiB，join 后以 12 GiB 包络作失败检查，ASan 虚拟地址保留不等于 RSS。最大并发 CPU 为 4，join 为 1，无 GPU。校准约 `2000×100000×128=25.6×10^9` 个坐标比较，加 200 端点评估 GT、4 个独立邻域和 3 次 join。预计 3–15 分钟；单个长步骤上限 600 秒，调度的长步骤受全流程 1,800 秒截止时间约束。此为计划估计，不能作为已测性能。

## 成功条件与停止条件

Gate 5A-R 本地工程条件：反例与交叉实现通过；split 可复现且互斥，0 独立；统计空值/FP/重复和 CI 退化得到明确处理；所有活动预取块使用边界检查；既有资产保持不变。

服务器正确性条件：上述有界验证全部退出 0；完整转换和独立邻域与 C++ GT 一致；原生 SIMD harness 和 sanitizer 无报告；三种构建及历史 baseline 的输出相同，三种构建的分桶产物相同；评估及 0 诊断的 FP=0、所有 pair 合法且无重复；三个统计量有定义并记录有效区间、样本量和限制。Recall 允许低于 90%，不得以改阈值/更换评估样本规避结果。

立即停止：数据/源码对应关系不清、哈希或格式异常、GT 不一致、FP>0、重复/非法 pair、输出/任务/分桶变化、sanitizer 报告、超时、资源超限或指标无法定义。不要通过禁用 sanitizer 检查、忽略失败日志、重抽评估样本或自动调参继续验收。先保存证据并定位。

功能回归完成后，仍需单独评估预取修复的性能影响：固定输入、图、容量、任务、CPU affinity、线程、计时窗口和缓存状态；关闭 dump、分开报告构建/搜索及端到端时间，至少 3 次重复，同时报告总 RSS。safe vs prefetch_off 可测提示的边际效果；UB 原版无法充当有定义的通用正确性基准。当前插桩回归耗时不用于加速比，实际设备层 I/O 保持 UNVERIFIED，10% cache 配置也不等同于进程总内存上限。

本地修复完成即停止。服务器执行、真实性能验证、正式 VoR 对齐和 Gate 5B 决策均未完成；提交等待用户检查与批准。
