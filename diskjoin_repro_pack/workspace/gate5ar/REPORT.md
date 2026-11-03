# Gate 5A-R 本地工程报告

日期：2026-11-03（Asia/Shanghai）。验证级别：本地 correctness regression；Linux realdata pilot 待验证。

## 结论

本地修复及回归完成。此前 76.49% Recall 和 Wilson 区间未在本轮恢复为有效结论。服务器尚未运行，Gate 5A-R 整体验收待定，Gate 5B 保持 NO-GO。全部新增产物位于 `workspace/gate5ar/`；2,071 个既有文件内容哈希不变，已有 tracked 文件无 diff。无 commit、push、reset、clean、远程操作、下载或依赖安装。

## 修复与证据

- Oracle：记录头在加载层剥离，calib 与 gt 共用 payload。旧距离函数的真实源码被单独编译，末四维反例重现错误距离 0；新 Oracle 与独立范数/点积实现一致，真实反例距离 260,100。随机小样本、严格阈值、截断/非法输入、重复端点及输出覆盖保护通过。
- 采样：校准种子 2026110301、评估种子 2026110302，2,000/200 端点互斥，0 单列。清单包含版本和哈希，评估器复核哈希及固定设计。
- 统计：邻居加权 Recall、非空端点平均 Recall、端点 incidence Precision；端点 bootstrap 5,000 次，种子 2026110303。报告空分母、无定义 replicate 和退化 CI；不使用 pair-level Wilson。条件总体及统计限制见 README。
- HNSW：17 个预取块归入受检 helper，覆盖六类调用路径；有效索引边界、空表、lookahead、非法 ID/degree、visited 尾部均有回归。另修复本地 UBSan 实际暴露的标签指针对齐问题，日志保留。见 PREFETCH_AUDIT。
- 服务器脚本：使用已有 BigANN100K，固定 m=272、128 维、1000 桶、K=24、eb=0.1、缓存配置 5,120,000 B；三构建/历史 dump 回归、独立 GT 检查及每运行 RSS，输出至新的唯一运行目录。不会改旧配置的数据/输出路径。

## 本地命令及结果

```bash
bash workspace/gate5ar/scripts/run_local.sh
python3 -B workspace/gate5ar/scripts/check_static.py
```

环境：Darwin arm64，`clang++`，Python3；HNSW 使用 `NO_MANUAL_VECTORIZATION`、`-fsanitize=address,undefined -fno-sanitize-recover=all`。

结果：10/10 单元与 CLI 测试 PASS；C++ 标量 HNSW sanitizer 回归 PASS；digest=12385809373267807141；Python AST、Bash 语法、预取静态检查 PASS；2,071 个既有文件哈希一致；4 个 patch 的 `git apply --check` 通过。

主日志：`logs/local_validation_complete.log`、`logs/static_final.log`、`logs/patch_checks_final.log`、`logs/linux_platform_guard_mac.log`。

失败记录：`logs/hnsw_build_mac.log` 为初始 harness 参数签名错误；`logs/local_validation_01.log` 是 alignment UB 的实测失败。修复后日志 02/03/final 通过。失败材料未删除，也未写回旧 Gate。

补丁检查最初受父 Git 仓库路径前缀影响，出现 skipped patch；检查器现显式拒绝跳过。首轮实际检查又发现累计补丁的 EOF 换行标记缺失（`logs/patch_checks_verified.log`），已修复。最终日志逐文件显示 Checking patch，四个补丁全部通过。

## 尚未验证

Linux SSE/AVX2/FMA、OpenMP、O_DIRECT、BigANN100K 新 GT/校准密度/Recall/Precision/区间、原生 SIMD sanitizer、历史 dump 等价性、服务器资源峰值均待服务器执行。物理 SSD I/O、总内存 10% 对齐、修复性能影响与正式 VoR 对齐也未完成。

## 下一步与边界

README 提供完整 Linux 命令、3–15 分钟/0.5–2 GiB 磁盘/预计低于 2 GiB RSS 的资源估计、逐步骤 600 秒及整体长步骤 1,800 秒限制，以及成功/停止条件。估计没有替代实测。任何 GT 不一致、FP、非法/重复 pair、sanitizer、输出变化或资源异常均停止并保留证据。

本轮到此停止，等待用户检查和批准提交；不自动执行服务器验证或进入 Gate 5B。
