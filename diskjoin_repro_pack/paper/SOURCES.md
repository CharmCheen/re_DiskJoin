# 论文原文来源与版本

**首选**：ACM PACMMOD Version of Record（VoR）

- Title: *DiskJoin: Large-scale Vector Similarity Join with SSD*
- Authors: Yanqi Chen, Xiao Yan, Alexandra Meliou, Eric Lo
- Venue: *Proceedings of the ACM on Management of Data*, 3(6), Article 315, December 2025 (SIGMOD 2026)
- DOI: https://doi.org/10.1145/3769780
- ACM PDF: https://dl.acm.org/doi/pdf/10.1145/3769780
- 正式排版版：27 页（已在用户 Library 搜到）。
- 用户可将已下载/有访问权限的正式版原样拷贝至本目录：`DiskJoin_PACMMOD_2025_formal.pdf`。

**可自动下载**：arXiv 作者预印本

- arXiv: https://arxiv.org/abs/2508.18494
- 固定 v2 PDF: https://arxiv.org/pdf/2508.18494v2
- Version: 2025-10-10; 15 页。它包含论文的方法描述和图表，但与 ACM 27 页正式排版版分别对待。
- arXiv v2 页面给出的许可证：CC BY-NC-ND 4.0（https://creativecommons.org/licenses/by-nc-nd/4.0/）；保持原始 PDF 完整、不做改动、用于非商业研究，并保留署名和链接。

## 本包的现实限制

打包会话没有外部网络访问，而且无法获取用户 Library 中 PDF 的原始二进制字节，因而此 ZIP 暂不预装 PDF 本体。执行 `bash scripts/fetch_sources.sh` 时才会在远程机下载 arXiv v2。ACM 正式 PDF 要由你自行复制进来。禁止伪装成已在包内、禁止混淆论文版本。

## Agent 阅读优先顺序

1. Intro（I/O bottleneck、问题设定）；
2. System overview；
3. MECC / task orchestration（主要 insight）；
4. Gorder + Belady 的执行过程；
5. Bucketing / pruning；
6. Experiments 中的 Recall 与消融实验、资源配置。
