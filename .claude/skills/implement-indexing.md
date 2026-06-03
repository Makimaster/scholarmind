---
name: implement-indexing
description: indexing 索引服务开发规范（切分 + 双语增强 + 混合向量化 + 写 Milvus）。当在 backend/services/indexing 下实现切分、embedding、Milvus collection/索引、双语摘要时使用。
---

# indexing 索引服务开发规范

开发前先阅读 `docs/data-contracts.md` (关于 Milvus collection 的定义) 与 `backend/services/indexing/CLAUDE.md`。

## 实现要点
1. **智能切分**：读取 `doc_blocks` 内容，文本块按章节/语义进行切分（保持 15-20% 重叠度），表格与公式块作为整体保留，不进行切分。
2. **双语增强**：英文文本块使用 `prompts/enrich_zh_summary.md` 提示词，表格使用 `table_summary.md`，图片使用 `figure_caption.md`，以此生成中文摘要内容 (`content_zh`)，以增强跨语言检索效果。
3. **混合向量化**：通过 `common/clients/llm` 调用 Embedding 接口，同时生成稠密向量 (Dense Vector) 与稀疏向量 (Sparse Vector)。
4. **Milvus 集合管理**：通过 `common/clients/milvus` 模块初始化 Milvus 集合。配置为 Dense 向量采用 `HNSW` (COSINE 相似度)，Sparse 向量采用 `SPARSE_INVERTED_INDEX`。以 `user_id` 作为 Partition Key，创建完毕后执行 Load。
5. **批量写入**：采用 Bulk Insert 批量写入 Milvus，Chunk ID 使用 `xxhash(content_en + paper_id)`，必须携带 `user_id`, `paper_id`, `folder_id`, `page_num`, `block_id`, `image_key` 等标量字段。

## 验收标准
- [ ] 确保 `EMBEDDING_DIM` 配置与 Milvus 字段维度及模型输出维度一致
- [ ] 确认向量索引构建完成且 Collection 成功加载（避免全库暴力扫）
- [ ] 确认 `content_en` 与 `content_zh` 双语内容均已写入
- [ ] 大表格采用“小-大检索”策略：中文摘要写入 Milvus，完整 HTML 表格保留在 `doc_blocks`
- [ ] 保证写入操作的幂等性：重复入库时不产生重复 Chunk
