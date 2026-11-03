# 官方候选仓库源码审计记录（先读再跑）

已检索 `iidyc/DiskJoin` 仓库，固定提交 `aa86151f97527b1dcf9a032d523c1d67d892454a`（2025-06-08）。审计针对所检查的公开源码，最终需在远程 checkout 后重核。

| 路径 | 作用/应观察内容 |
|---|---|
| `expr/main.cpp` | `build(config); search(config);`，时间打印 `Build done` / `Join done`（累计计时） |
| `lib/Kmeans.h` | `one_level_kmeans`：分桶、HNSW、双选桶分配；`batch_size = n/1000`，需 n>=1000 |
| `lib/ClusterIO.h` | 写入桶布局；读取采用 Linux `O_DIRECT` 与 4096 对齐缓冲区 |
| `lib/DiskJoin.h` | 候选任务生成、HNSW、剪枝、重排、缓存、距离比较、采样 Recall |
| `lib/Gorder.h` | `order_gorder` 与滑动窗口，返回 rank permutation |
| `lib/Cache.h` | `Cache` 使用 future-use 优先级堆；`LRUCache` 和模拟函数存在，但主路径用 `Cache` |
| `lib/ConfigReader.h` | 固定顺序读取 10 项配置，不解析常规带注释的复杂格式 |
| `scripts/run.sh` | 16 项 100M 级实验（不要用于最小阶段） |

## 关键风险

1. `DiskJoin.h` 对满足阈值的向量对，只在 `id1 % 100000 == 0` 或 `id2 % 100000 == 0` 时增加计数，最后用 `count / config.gt` 输出 `recall`。对于 12k toy 样本，仅 ID 0 被采样；对应 GT 需要按完全一致的采样标准生成。该输出无法代替全量 Join 对输出。
2. `search()` 中 `epsilon = sqrt(config.radius)`，最终比较 L2 **平方距离** 与 `epsilon*epsilon`。toy 中 `radius` 应填写 `epsilon²`；配置文字 `radius` 容易产生误会。
3. `mem_budget` 以 GiB 参与缓存分配，不能直接把上游 `M5/M15/M20` 文件名解释为确定的缓存比例。为比较公平必须记录可用物理内存与占用。
4. `main` 无单独的 `skip-build` 模式，每次运行都会尝试重新构建桶文件和 HNSW。计时是累计的，评估需要区分 Build 时间、Join 时间，以及磁盘缓存的冷/热状态。
5. 编译选项包含 AVX2/FMA、`-march=native`、OpenMP。Linux `O_DIRECT` 可能与网络盘、FUSE、overlay 等文件系统不兼容。Smoke 应尽量运行在本地 POSIX 文件系统上。
6. `ClusterReader` 的缓冲区分配/释放及 `posixDirectReadCluster` 缺少明显的系统调用返回值检查（来自源码检视）；若运行失败，先保留原始 stdout/stderr，检查读取长度、对齐和文件系统，禁止默默更改数据。
7. 上游使用 `std::random_shuffle` 和 C++11 编译标准；现代 C++/编译器兼容性变化需要实测。
8. 公开仓库根目录未见明确 LICENSE；不要默认为允许再分发或将原始代码混入另一个公开仓库。此包的 `fetch_sources.sh` 在用户机器上自行取得原始代码。
9. 上游不直接公开与论文所有消融图完全一一对应的运行入口。禁用 Gorder/替换 Cache/取消剪枝可能需要另建实验副本与人工插桩。

## 最小二进制运行的解释限度

成功退出 + 有限 Recall 表示基本运行通路可用；如果 Recall 偏低，先检查候选任务生成和 toy 的分布、K、抽样 GT、数据精度与配置顺序。不要把调大 K 或调阈值后的一个结果当作原实验可复现的证据。任何调整应保留原配置及新配置的独立日志。

## 10M 扩展 Gate

完成 toy 后，需先计算：可用 SSD 容量、全量浮点数据字节数、写桶空间、构建临时缓冲、CPU 时间上限；将 10M 的 `data_file`、`cluster_num`、`K`、`radius`、`mem_budget`、`gt` 全部单独校准。不可将 BigANN100M 配置文件简单改路径直接运行。
