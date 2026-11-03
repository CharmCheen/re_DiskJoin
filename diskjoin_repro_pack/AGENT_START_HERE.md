# Paste this message to your remote coding Agent

请以本目录为项目根目录，开展 DiskJoin 的**从零开始最小复现**，遵守 `AGENTS.md` 的所有限制。

第一步读 `README.md`、`docs/CORE_IDEA.md`、`docs/IMPLEMENTATION_AUDIT.md`、`docs/EXPERIMENT_PROTOCOL.md`。然后先运行只读的 `scripts/check_env.sh`。核对源文件和论文来源，审计 source pin SHA，执行离线 `micro_task_cache.py` 和单元测试。如果远程机可以联网并且我授权获取依赖，执行 `scripts/fetch_sources.sh` 下载固定提交与 arXiv v2；若我已将 ACM 正式版放在 `paper/`，优先读正式版。不要混同两种论文版本。

只有环境与依赖具备时，运行 `bash scripts/run_smoke.sh`，在 12k × 16d synthetic dataset 上编译/执行。检查 toy 的 fbin、GT、日志、Build time、Join time、sampled Recall，失败时记录原始报错并分析。不得自动执行上游的 100M 数据下载/16 组完整实验脚本。不得删除或覆盖已有文件、不得修改 reference 原件、不得在未授权时执行 sudo/apt/付费调用/重负载实验。

在 `workspace/REPORT.md` 输出（1）论文 Insight 是否理解；（2）运行了什么命令；（3）SHA、数据和环境；（4）全部结果和日志位置；（5）PASS/FAIL/未验证；（6）当前能够主张的结论；（7）下一阶段 Gorder、Belady、Pruning 消融的可执行小步计划与预估成本。实测证据和推断分开写，严禁以编译通过或 toy 的采样 Recall 宣称论文级复现。
