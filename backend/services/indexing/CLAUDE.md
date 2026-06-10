# indexing — 索引服务

把解析出的 block 变成可检索的 Milvus chunk（双语 + 向量）。

## 流程
1. 读 `doc_blocks` → 智能切分（按章节/语义，表格/公式整块，15-20% 重叠）。
2. 大表/图：用 table_summary / figure_caption 提示词生成中文摘要，原件留 `doc_blocks`（小-大检索）。
3. 普通文本：用 enrich_zh_summary 生成 `content_zh`（中文摘要+关键词）。
4. 向量化：`clients/llm` 调 embedding（dense_vec/content_en + dense_vec_zh/content_zh 合批一次请求 + sparse）。
5. 写 Milvus（collection `scholarmind_chunks`），字段见 data-contracts.md。

## 关键约定
- **每个 chunk 必带**：`user_id/paper_id/folder_id/page_num/block_id/image_key`。
- **维度一致**：向量维度 == `EMBEDDING_DIM` == Milvus dense_vec 维度。
- **collection/索引**：启动时确保已创建 HNSW 索引 + sparse 索引 + `user_id` partition_key 并 load。
- **幂等**：chunk id = `xxhash(content_en + paper_id)`，重复入库覆盖不重复。
- 批量入库用 Milvus bulk insert，别逐条。

## 接口
- `index_paper(user_id, paper_id, blocks)`：切分+增强+向量化+写 Milvus，回填 `papers.chunk_count`。

## 当前状态与后续优化
- 切分、双语增强、向量化和 Milvus 写入链路已接入；后续重点是切分策略调优、大表摘要质量和批量入库性能。
