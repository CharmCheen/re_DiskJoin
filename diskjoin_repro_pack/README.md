# DiskJoin — Single-Machine Minimal Reproduction Pack

**目标：从零开始，在 Linux 单机上理解并验证 DiskJoin 的核心机制，最终完成一轮小规模官方代码 Smoke Test。**

此包专门面向一个可读写本目录、可以执行 shell 命令的编码 Agent。它提供：研究约束、论文阅读路线、方法摘要、已审计的源码映射、固定提交、合成数据生成器、微型缓存实验、运行脚本和测试。

## 先看完整性（重要）

- **复现包自身已经生成且完成纯 Python 验证。** `scripts/micro_task_cache.py` 与 `scripts/make_toy.py` 可以离线运行。
- **外部参考内容需要在远程机上下载。** 当前打包环境无法访问 GitHub/arXiv，也无法从用户现有 Library PDF 获取原始字节，故未伪造或重建源码/PDF。运行 `bash scripts/fetch_sources.sh` 即可填充 `reference/DiskJoin/` 和 `paper/DiskJoin_arXiv_2508.18494v2.pdf`。这一步要求远程机有 GitHub/arXiv 网络访问。
- `paper/DiskJoin_arXiv_2508.18494v2.pdf` **是 arXiv v2（15 页）**，对应 2025-10-10 版本；**ACM 正式版（27 页）**请从 DOI 单独取得，保存为 `paper/DiskJoin_PACMMOD_2025_formal.pdf`。本包不会将两个版本混同。
- 参考仓库提交固定为 `aa86151f97527b1dcf9a032d523c1d67d892454a`，仓库与正式版本的对应关系仍须独立审查；不能仅凭运行成功宣称“论文完整复现”。

## 远程机上的最短路线

```bash
# 1. 解压后进入顶层（勿以 root 运行常规实验）
cd diskjoin_repro_pack

# 2. 环境检查；不会安装、下载或修改系统
bash scripts/check_env.sh

# 3. 一次性获取固定的源码和 arXiv PDF（需网络）
bash scripts/fetch_sources.sh

# 4. 离线机制演示和单元测试（不需要安装 Python 包）
python3 scripts/micro_task_cache.py
python3 -m unittest discover -s tests -v

# 5. 端到端最小实验（需要 g++/cmake/OpenMP；只跑 12k synthetic）
bash scripts/run_smoke.sh
```

如果没有 `g++`/`cmake`，请让 Agent **先提出依赖安装方案，待你授权后再安装**。作者 README 的 Ubuntu 依赖为：`g++ cmake libboost-dev libgoogle-perftools-dev`。这不是自动安装命令。

**不要直接运行上游 `scripts/run.sh` 或 `scripts/create_datasets.sh`。** 前者一次运行 16 组 100M 实验，后者下载两组 100M 数据。远程工作负载与储存资源应由用户批准。

## 主要文件

| 路径 | 用途 |
|---|---|
| `AGENTS.md` | Agent 必须遵循的工作边界、成功 Gate 和报告格式 |
| `docs/CORE_IDEA.md` | 论文背景、Bucket Graph、MECC、Gorder、Belady、Pruning |
| `docs/IMPLEMENTATION_AUDIT.md` | 公开仓库审计、潜在坑和可比较实验 |
| `docs/EXPERIMENT_PROTOCOL.md` | Hypothesis、baseline、指标、阶段、停止条件 |
| `paper/SOURCES.md` | 论文来源、正式版与 arXiv 版本区分 |
| `reference/SOURCES.md` | 代码来源、版本锁定、许可证与来源不确定性 |
| `scripts/micro_task_cache.py` | 可独立运行的缓存/访问顺序模型 |
| `scripts/make_toy.py` | 12,000 条 16 维 float32 synthetic `.fbin`，同时计算采样 GT |
| `scripts/run_smoke.sh` | 对冻结参考代码 out-of-tree 编译后运行 synthetic |
| `tests/` | 离线测试（不依赖外部 Python 包） |

`workspace/` 为运行时目录（含下载后的结果以外的生成数据、构建目录和日志），已被包内 `.gitignore` 规则排除。所有实验必须显式记录仓库提交、配置、机器、日志与时间。

## 单机资源建议

默认 synthetic `.fbin` 小于 1 MB，内存预算为 0.1 GiB，典型操作依赖 CPU 和本地文件系统。此最小规模用于功能验证，不具备 SSD I/O 性能意义。后续 10M/100M 规模需要单独建实验配置并重新计算 GT；不可照搬 100M 的 `gt`。

推荐使用你已有的 Linux CPU 服务器，默认 `OMP_NUM_THREADS=4`、`BUILD_JOBS=4`，控制对共享机器的影响。`nvidia-smi` 与 GPU 均非必需。

## 状态标签

- `VERIFIED_LOCAL`: 本包中 stdlib 机制测试和 synthetic 数据自检。
- `NOT_RUN_REFERENCE`: 官方 C++ 实现尚未在本包生成环境实际编译/运行（缺网络获取代码）。
- `UNVERIFIED_ACM_PARITY`: 公开仓库与 ACM Version of Record 的一致性待核对。

如无法联网下载源码与 PDF，应停在当前 Gate 并记录阻塞，不得自行虚构文件或编造运行结果。

## 当你需要一个真正包含论文和完整代码的离线 ZIP

本压缩包首先充当网络可用时的 **bootstrap pack**。在远程单机上成功运行 `bash scripts/fetch_sources.sh` 后，执行：

```bash
python3 scripts/build_filled_bundle.py
```

会在**本目录的上一级**产生 `DiskJoin_Private_Filled_Offline_Bundle.zip`，内含完整工作树中的参考代码、原封不动的 arXiv v2 PDF 和本包的 Agent 约束/实验脚本；如果你手动放入 ACM 正式 PDF，也会一并纳入。脚本拒绝覆盖已有归档，排除 `.git` 与 `workspace/`，并检查参考仓库原 SHA。此归档供私人学术研究使用，分发给第三方前需核对仓库和论文的版权限制。
