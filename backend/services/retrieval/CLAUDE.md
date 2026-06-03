# retrieval — 检索服务

给定 query + 作用域，返回重排后的高质量 chunk。决定"查得准/查得全"。

## 流程（对应 rag-pipeline.md 在线链路 ①-⑦）
1. 查询理解：query_rewrite + query_translate + hyde（**并发执行**降延迟）。
2. 作用域：按 `paper_id/folder_id/acl` 构造 Milvus 过滤；大范围→两阶段文档路由（先粗筛 Top-N 篇）。
3. 混合检索：dense + sparse，带过滤表达式，走 HNSW 索引 + user_id 分区。
4. 多路 RRF 融合（英文路/中文摘要路/跨语言路）。
5. 重排：reranker → Top-N（`RERANK_TOP_N`）。
6. CorrectiveRAG：corrective_grade 打分，不足→改写重检/拒答。
7. 后置：去重 + 上下文压缩。

## 关键约定
- **绝不全库扫**：必带 user_id + 作用域过滤；几万篇靠两阶段路由收窄。
- **缓存**：检索结果/重排结果进 Redis（key 见 data-contracts.md），命中直接返回。
- 跨语言不裸跑单模型，必走翻译 + 中文摘要双通道。
- top_k、dense 权重、是否启用 HyDE/Corrective 全读 `.env`，不硬编码。

## 接口
- `retrieve(user_id, query, scope, top_k) -> list[Chunk]`：返回带 score 的 chunk（含 page/image/block_id）。

## 待开发任务 (TODO)
- 混检 + RRF 实现；reranker 对接；CorrectiveRAG 判级与重试；缓存层；两阶段路由。
