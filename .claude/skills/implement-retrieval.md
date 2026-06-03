---
name: implement-retrieval
description: retrieval 检索服务开发规范（查询优化 + 混合检索 + RRF + 重排 + CorrectiveRAG + 跨语言 + 两阶段路由）。当在 backend/services/retrieval 下实现混合检索、重排、跨语言、缓存时使用。
---

# retrieval 检索服务开发规范

开发前先阅读 `docs/rag-pipeline.md` (在线链路定义) 与 `backend/services/retrieval/CLAUDE.md`。

## 实现要点
1. **查询优化**：并发执行 `query_rewrite`（查询改写）、`query_translate`（查询翻译）与 `hyde`（假设性文档生成）提示词逻辑（使用 `asyncio.gather`）。
2. **检索范围限制**：根据 `paper_id` / `folder_id` / `acl` 构造 Milvus 标量过滤表达式。大范围检索时采用两阶段路由策略：先基于文档标题/摘要粗筛出 Top-N 篇文档，然后在这 N 篇文档范围内进行 Chunk 级精细搜索。
3. **混合检索**：调用 Milvus 进行 Dense + Sparse 混合检索，并传入相应的标量过滤表达式。
4. **多路 RRF 融合**：使用互惠排名融合 (RRF) 算法合并英文检索路、中文摘要检索路与跨语言检索路的结果。
5. **重排过滤**：调用 Reranker 模块对融合后的结果进行重排，保留 Top-N 项（由 `RERANK_TOP_N` 参数决定）。
6. **CorrectiveRAG 机制**：使用 `corrective_grade` 评估召回文档的质量，若质量不足，则执行查询改写并重新检索一次；若依然不足则拒绝回答。
7. **多级缓存**：将检索与重排的中间结果缓存至 Redis（Key 规则参考 `docs/data-contracts.md`）。

## 验收标准
- [ ] 所有 Milvus 查询必须携带 `user_id` 和相关作用域过滤，严禁全库扫描
- [ ] 中文 Query 能够成功召回英文原版论文（双语通道与翻译生效）
- [ ] 命中 Redis 缓存时实现秒级响应
- [ ] CorrectiveRAG 能有效拦截并改写或拒绝“参考资料不足”的查询
