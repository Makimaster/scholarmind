# RAG 全链路与意图路由设计

## 一、入库链路（离线预处理 / LlamaIndex IngestionPipeline）

```
PDF上传 → MinIO存原文 → 建 ingest_task → 入 RQ 队列 (秒级响应,可关页面)
  worker 消费:
  ① MinerU 解析: 双栏正文 + 公式→LaTeX + 表→HTML + 抠图
  ② GROBID 解析: 标题/作者/摘要/章节/参考文献 → MySQL(papers, citations)
  ③ 图片: 存 MinIO → Qwen3-VL 生成图片描述
  ④ 切分: 按章节/语义; 表格/公式整块不切碎; 15-20% 重叠
  ⑤ 父块入库: 大表/图/公式完整内容 → MySQL doc_blocks (小-大检索的"大")
  ⑥ 双语增强: 每块 → LLM 生成中文摘要 + 关键词 (content_zh)
  ⑦ 向量化: embedding(dense + sparse)
  ⑧ 写 Milvus: 向量 + content_en/zh + user_id/paper_id/folder_id/page_num/block_id/image_key
  ⑨ 更新 ingest_task: done / failed(可重试)
```

## 二、在线推理链路（含意图路由）

```
用户提问
  → ⓪ 意图路由 (intent_router): 闲聊/常识 → 直接 LLM 回答, 不检索 (省延迟,抑幻觉)
                                知识问题 → 进 RAG; 复杂(综述/对比) → Agent
  → ① 查询理解: 改写 + 中→英翻译 + HyDE  (并发跑,降延迟)
  → ② 作用域确定: paper_id/folder_id/acl 过滤; 大范围→两阶段文档路由(先粗筛Top-N篇)
  → ③ 混合检索: dense + sparse, 带作用域过滤  (Milvus, 走 HNSW 索引+分区)
  → ④ RRF 融合多路结果
  → ⑤ 重排: reranker → Top-N
  → ⑥ CorrectiveRAG: 检索质量打分; 不够→改写重检/降级拒答
  → ⑦ 后置: 去重 + 上下文压缩
  → ⑧ 生成: LLM 流式 + 角标引用 + 命中原文/原图溯源
  → ⑨ (可选) Self-RAG: 自检每句有无出处, 无依据则标注
  → 写 query_logs + PG messages; 命中缓存则秒回
```

## 三、缓存加速（Redis，应对多优化带来的延迟）

- 嵌入缓存、**语义答案缓存**（相似问秒回）、检索/重排缓存、热点元数据缓存；
- 查询改写/翻译/HyDE **并发执行**（asyncio.gather），不串行。

## 四、跨语言策略（中文问英文论文）

不赌单一 embedding 跨语言。三路召回 + RRF：
1. **英↔英**：query 翻译成英文 → 检索 `content_en`；
2. **中↔中**：中文 query → 检索 `content_zh`（入库时生成的中文摘要）；
3. **跨语言兜底**：多语言 embedding 直接中文 query 检索。

## 五、系统优化点与落地映射

| # | 优化点 | 落地位置 | 优先级 |
|---|---|---|---|
| 5 | 文档分块优化 | 入库④ 按章节/语义,表格公式整块 | 🟢核心 |
| 6 | 文档增强 | 入库⑥ 中文摘要+关键词 | 🟢核心 |
| 1 | 查询重写 | 在线① + intent_router | 🟢核心 |
| 2 | 查询扩展 MultiQuery | 在线① multi_query | 🟢核心 |
| 3 | HyDE | 在线① hyde | 🟢核心 |
| 4 | 子查询分解 | Agent 综述/对比拆问题 | 🟡进阶 |
| 7 | 混合检索 | 在线③ dense+sparse | 🟢核心 |
| 8 | 多路召回 | 在线② 三路(英/中/跨语言) | 🟢核心 |
| 9 | 多向量 ColBERT | embedding colbert 输出(可选) | 🟡进阶 |
| 10 | 稀疏向量 | embedding sparse 输出 | 🟢核心 |
| 11 | 向量库索引优化 | Milvus HNSW/IVF 调参 | 🟡进阶 |
| 12 | 上下文压缩 | 在线⑦ | 🟡进阶 |
| 13 | 去重过滤 | 在线⑦ | 🟢核心 |
| 14 | 重排+TopK | 在线⑤ reranker | 🟢核心 |
| 15 | 提示工程 | answer_with_citation 提示词 | 🟢核心 |
| 16 | 引用溯源 | 在线⑧ page_num+image_key | 🟢核心 |
| 17 | Self-RAG | ⓪意图路由 + ⑨自检 | 🟡进阶 |
| 18 | Corrective RAG | 在线⑥ | 🟡进阶 |
| 19 | RAG-Fusion(RRF) | 在线④ | 🟢核心 |
| 20 | 自适应检索 | ⓪路由 + ②两阶段(简单轻/复杂深) | 🔵选做 |

> 覆盖约 18/20。embedding 一个模型同时产出 dense+sparse(+colbert)，一口气覆盖 7/9/10。
