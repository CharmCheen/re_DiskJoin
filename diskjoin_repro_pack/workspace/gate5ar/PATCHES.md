# Patch 清单

所有补丁已执行 `git apply --check`，仅检查可应用性，未将补丁应用到旧 Gate 或上游快照。

| 文件 | 基线与用途 |
|---|---|
| `patches/oracle_offset_and_validation.patch` | 对 Gate 5A `oracle/gt_calib.cpp` 的替换；完整 128 维 calib/GT、输入校验、100K 上限与输出覆盖保护。 |
| `patches/disjoint_sampling.patch` | 对 Gate 5A `oracle/sample_gt_endpoints.py` 的替换并重命名为 `sample_endpoints.py`；互斥采样、0 分离、种子/哈希清单。 |
| `patches/hnsw_safety.patch` | 对 Gate 5A `instrumented/DiskJoin/lib/hnswlib/hnswalg.h` 的增量；17 处预取块、degree/ID 边界、标签对齐修复。 |
| `patches/upstream_to_gate5ar.patch` | 相对固定 SHA `aa86151f97527b1dcf9a032d523c1d67d892454a` 源码快照的累计差异；包含此前 Gate 的必要 instrumentation/修复，便于完整重建，不能将全部累计改动归于本轮。 |
| `patches/bases.json` | 增量基线 hnsw SHA-256、固定上游 SHA 和累计修改文件清单。 |

累计源码差异涉及 `lib/{Cache,ClusterIO,DiskJoin,Gorder}.h`、`lib/hnswlib/hnswalg.h`、`oracle/policy_test.cpp`、`utils/heap.h`。本轮复制后实际改变的既有 C++ 源码文件仅为 `hnswalg.h`；其他六项继承 Gate 5A。

新 Bootstrap 评估器、独立验证器、回归测试、Linux/Mac 脚本及文档以完整新文件交付。整个隔离副本可直接用于构建；**不要向旧 Gate 目录实际应用这些补丁**。

核验命令（复现包目录，只读，自动处理父 Git 仓库的路径前缀并拒绝 skipped patch）：

```bash
python3 -B workspace/gate5ar/scripts/check_patches.py
```
