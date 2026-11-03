# 实验方案与 Gate

## H0/H1、指标与验证层级

**H1 (mechanism)**：在完全相同的 Bucket-Pair 任务集合与缓存容量下，使用偏好共享邻居的任务顺序相较原始顺序能降低 Bucket 缓存缺失和 SSD 读取次数。

**H2 (cache)**：在一个固定的 Bucket Access Sequence 和等大小缓存槽假设下，Belady 的 Miss 数不高于 LRU；如果相同，说明该序列没有体现它们的差异，不应因此推断缓存算法普遍无贡献。

**H3 (pruning)**：在相同数据与准确率测量方式下，概率剪枝能减少候选距离计算量并控制相似对遗漏率。

**H4 (end-to-end)**：在明确硬件、数据、Recall 目标与公平 Baseline 的条件下，核心优化能减小端到端 Join 耗时或 SSD 读取量。

## 阶段与成功 Gate

| Gate | 数据/代码 | 主指标 | 成功标准 | 失败解读 |
|---|---|---|---|---|
| G1 机制 | 4 Bucket、3 Pair；stdlib | Cache miss | 在给定例子上 Belady 5→4；测试通过 | 逻辑/模型实现错误，停止 |
| G2 Smoke | synthetic 12k、16d；冻结参考源码 | Exit、采样 Recall、日志 | 退出码 0；指标有限、在 [0,1]；配置 GT 重新计算 | 检查数据格式/ABI/O_DIRECT/源码，不得编造成功 |
| G3 正确性 | 小规模抽样 + 独立 GT | Precision/Recall 或采样 Recall | 能严格解释并复现数值 | GT 口径冲突则暂停性能比较 |
| G4 机制消融 | 固定输入、候选图、CPU、内存 | Cache miss、disk bytes、dist ops、秒 | 多次重复，收益方向稳定，统计波动可解释 | 没有稳定收益则报告负结果 |
| G5 论文级 | BigANN/Deep，论文同配置 | Recall、吞吐、I/O、构建/执行分离 | 实验设置与论文对齐后才能对比论文表格 | 资源/实现/评估差异则降级结论 |

## 实验控制

- 冻结输入随机种子、向量距离阈值、分桶/剪枝参数与候选任务列表。
- 记录 CPU 模型与线程数、Linux 内核、编译器/flags、内存限制、SSD 型号、磁盘挂载类型。
- 区分 build time、join time，避免热缓存/冷缓存混淆。要清理系统 Page Cache 时必须先获得用户授权，不得默认执行。
- 机制消融至少 3 次重复，逐次记录完整日志与增量指标；不要只报告最优的一次。
- 每次只改变一项机制；检查输出质量是否随之改变，不能在 Recall 不一致时直接比较纯性能。
- 不进行 Paper Benchmark 数据预处理和全量下载，除非先给出精确时间/磁盘/内存预估并得到用户确认。

## 停止条件

- 开源仓库 SHA、论文对应关系、源码 LICENSE 或 GT 口径无法核实：停在最小阶段并报告。
- `O_DIRECT` 持续失败：记录文件系统/系统调用证据，暂停扩大实验。
- toy 同配置重复运行不一致：先审计并行竞态、随机性和 I/O 错误。
- 正确性没有可信 GT 支撑：禁止报告算法级别 Recall 或性能胜出。
- 构建成本大到盖过 Join 优化或收益只在合成特殊数据中出现：把结果标为 exploratory。

## 输出要求

每次运行写独立目录：`config.snapshot`、`reference_commit.txt`、`stdout.log`、`stderr.log`、`summary.json`、`REPORT.md`，加上必要的宿主机配置记录。用 `PASS_SMOKE_ONLY` 与 `PAPER_REPRODUCED` 等区分状态；未经完整实验不得使用后者。
