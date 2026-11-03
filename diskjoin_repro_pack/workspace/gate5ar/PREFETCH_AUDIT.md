# HNSW Prefetch 审计与修复范围

基线：`workspace/gate5a/instrumented/DiskJoin/lib/hnswlib/hnswalg.h`。该文件含 17 个 `USE_SSE` 预取块。其余 hnswlib 头文件仅有注释掉的 prefetch 示例。固定原版位置与新逻辑映射如下。

| 函数 | 原始相关位置 | 覆盖方式 |
|---|---|---|
| `searchBaseLayer` | 253–275 | 构建阶段 layer 0/高层；degree 按层检查，首/次邻居和下一邻居按逻辑长度检查。 |
| `searchBaseLayerST` | 336–362 | 1-based 遍历转为 `data+1` 的 0-based helper；下一邻居索引为 j。 |
| `rangeSearchBaseLayer` | 411–434 | 空/单邻居安全，lookahead 下标为 j+1；消费 ID 在标签读取前检查。 |
| `knnSearchBaseLayer` | 481–504 | 同上；满 level-0 表不会将随后向量位模式解释为预取 ID。 |
| `repairConnectionsForUpdate` | 1144–1151 | 高层首邻居/下一邻居边界检查；更新操作和高层遍历的消费 ID/degree 检查。 |
| `searchAll` | 1423–1447 | 与 ST 相同的 1-based→0-based 映射，包含候选队列提示。 |

`prefetchNeighbor` 先验证 index<count，再读取 ID；`prefetchNode` 先验证 id<cur_element_count，再构造数据与 visited 地址；visited+64 必须仍落在分配的 max_elements 范围。全部 3 个底层 `_mm_prefetch` 指令集中于该 helper。非法 speculative ID 跳过提示；实际消费非法 ID/degree 时抛错并归还已借出的 visited list。辅助高层遍历也在解引用前验证 ID。

`GATE5AR_DISABLE_PREFETCH` 仅关闭提示指令，保留所有检查和距离向量化，用于服务器输出回归及后续受控性能测量。

新增的标签写入修复：本地 UBSan 指出 `memcpy(getExternalLabeLp(cur_c),...)` 的 typed pointer 对齐问题；改用已有 `setExternalLabel(cur_c,label)`，通过字节地址执行相同拷贝。失败日志见 `logs/local_validation_01.log`。复制布局、标签值及磁盘格式均不改变。

本地证据：HNSW harness 在真实类中构造空表、85-byte 高层满表、包含末尾向量数据的 level-0 满表、非法 ID 和非法 degree；还执行随机确定图的构建、标准搜索、knn/range 搜索、更新修复、searchAll 和 visited 尾部。Mac 标量 ASan+UBSan 通过。Linux SSE 分支和 BigANN100K 的三构建回归待执行。

边界：此补丁处理预取操作数及相关邻接遍历；它不宣称任意损坏的序列化索引、缺失 label、任意并发调用、所有分配溢出或 DiskJoin I/O 错误都安全。新异常路径用于停止损坏输入；有效图上的输出等价仍需服务器回归确认。提示数量与检查开销改变，性能影响待独立测量。
