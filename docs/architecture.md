# 架构总览

## 分层

```
┌────────────────────────────────────────────────────────────┐
│                 Vue 3 前端 (本地 npm)                         │
│  鉴权 · 论文库/上传 · 对话(SSE+溯源+图回显) · 可观测页 · 设置  │
└───────────────────────────┬────────────────────────────────┘
                            │ HTTP / SSE
┌───────────────────────────▼────────────────────────────────┐
│              FastAPI 网关 (app/main.py)                       │
│   JWT鉴权 · user_id隔离中间件 · 限流 · 访问日志 · SSE         │
└──┬──────────────┬──────────────┬──────────────┬─────────────┘
   │ parsing      │ indexing     │ retrieval    │ chat_agent
   │              │              │              │
┌──▼──────────────▼──────────────▼──────────────▼─────────────┐
│                       common (公用)                          │
│   配置 · DB客户端 · Milvus/MinIO/Redis 客户端 · 模型适配     │
│   鉴权 · 日志 · 异常 · schema(pydantic)                       │
└──┬──────────────┬──────────────┬──────────────┬─────────────┘
   │              │              │              │
┌──▼───┐ ┌────────▼───┐ ┌────────▼──┐ ┌─────────▼─┐ ┌─────────┐
│Milvus│ │MySQL(业务) │ │PG(记忆)   │ │Redis      │ │MinIO    │
└──────┘ └────────────┘ └───────────┘ └───────────┘ └─────────┘

  worker(RQ): 消费 rq:queue:ingest，跑 parsing→indexing 全链路
  外部解析: GROBID(8070) · MinerU(8001)   推理: embedding(8080) · reranker(8081)
```

## 服务边界（单体多模块 + 独立 worker）

一个 FastAPI 应用，内部按 4 个 service 包划分清晰边界（便于将来拆微服务）：

| 服务 | 输入 | 输出 | 依赖 |
|---|---|---|---|
| **parsing** | PDF (MinIO) | doc_blocks + 论文元数据 + 引用边 (MySQL)，图片 (MinIO) | MinerU, GROBID, VLM |
| **indexing** | doc_blocks | Milvus chunks（双语+向量） | embedding 模型, Milvus |
| **retrieval** | 用户 query + 作用域 | 重排后的 chunk 列表 | Milvus, reranker, LLM |
| **chat_agent** | query + 会话 | 流式答案 + 引用 + 记忆 | retrieval, PG, LLM |
| **worker** | RQ 任务 | 驱动 parsing→indexing | Redis(RQ) |

## 两大业务阶段

- **离线预处理**：上传→解析→双语增强→向量化→入库（走 worker，异步，不阻塞）。
- **在线推理**：意图路由→查询优化→混检→重排→后置→生成→溯源（SSE 实时）。

## 数据流向

1. **入库**：前端上传 → backend 存 MinIO + 建 `ingest_tasks` + 入 RQ 队列（秒级响应）→ worker：MinerU/GROBID 解析 → 图入 MinIO、元数据/引用/父块入 MySQL → indexing：中文摘要 + 向量化 → 写 Milvus → 更新任务状态。
2. **问答**：前端提问 → 意图路由（闲聊直接答 / 知识走 RAG）→ retrieval（作用域过滤 + 混检 + RRF + 重排 + CorrectiveRAG）→ chat_agent 组装上下文 + LLM 流式生成 + 角标溯源 → 写 query_logs + PG messages。

详见 [rag-pipeline.md](rag-pipeline.md)、[data-contracts.md](data-contracts.md)。
