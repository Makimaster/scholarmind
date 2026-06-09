# ScholarMind 当前实现对照文档

> 本文用于快速核对当前项目状态，替代早期 Mock 阶段的任务拆解说明。若与代码冲突，以 `CLAUDE.md`、`docs/data-contracts.md` 和实际代码为准。

## 当前状态

ScholarMind 已完成从 Mock 骨架到真实服务链路的主体迁移：

- 上传入口写 MySQL / MinIO / RQ，不在请求线程内执行解析。
- RQ worker 执行 `parse_paper` → `index_paper`，并回写 `ingest_tasks` / `ingest_batches`。
- PDF 解析采用 **Docling + GROBID**：Docling 负责版面块、页码和 bbox；GROBID 负责论文元数据和参考文献结构化。
- 入库 chunk 经过切分、中文摘要增强、Embedding 和 Milvus 写入。
- 检索链路包含查询改写、翻译、HyDE、混合检索、RRF、重排和可选 CorrectiveRAG。
- 对话链路包含意图路由、SSE 流式输出、引用事件、多轮记忆和 Agent 综述。
- 前端已接入真实 API，不再依赖 Mock 数据。

## 核心链路

```text
PDF 上传
  → FastAPI 校验文件并上传 MinIO
  → MySQL 写 papers / ingest_batches / ingest_tasks
  → RQ 队列
  → worker: parsing
      - Docling: 正文、表格、图片块、公式/数学内容、page_num、bbox
      - GROBID: title、authors、abstract、year、doi、references
      - VLM: 对有 image_key 的图片生成中文描述
  → worker: indexing
      - chunk_blocks
      - enrich_chunks
      - vectorize_and_store
  → Milvus + MySQL 状态更新
  → chat/retrieval 可检索问答
```

## 关键文件索引

| 模块 | 关键文件 | 说明 |
|---|---|---|
| 上传/论文库 | `backend/app/routers/papers.py` | 上传 PDF、文件夹、论文列表和删除 |
| 任务队列 | `backend/app/worker/main.py` | RQ worker，驱动解析和索引 |
| 解析 | `backend/services/parsing/parser.py` | Docling+GROBID 解析入口，写 `doc_blocks` / `citations` |
| 索引 | `backend/services/indexing/` | 切分、双语增强、向量化、写 Milvus |
| 检索 | `backend/services/retrieval/` | 查询优化、混合检索、重排和缓存 |
| 对话 | `backend/services/chat_agent/` | 意图路由、SSE、记忆、Agent 综述 |
| 公用配置 | `backend/common/config.py` | `.env` 配置唯一入口 |
| 数据契约 | `docs/data-contracts.md` | MySQL / PG / Milvus / Redis schema 真相源 |

## 配置要点

```env
DOCUMENT_PARSER_PROVIDER=docling
DOCUMENT_PARSER_FALLBACK_PROVIDER=none
REFERENCE_PARSER_PROVIDER=grobid
GROBID_BASE_URL=http://grobid:8070
```

- Docling 在 worker 容器内本地运行，模型/产物缓存挂载到 `./data/docling-cache`。
- GROBID 由 docker-compose 的 `grobid` 服务提供，用于元数据和参考文献 TEI 解析。
- 如 GROBID 不可用，代码会 fallback 到 LLM 参考文献抽取，避免整篇入库中断。

## 验证清单

1. `docker compose up -d backend worker grobid`
2. `curl http://localhost:8070/api/isalive`
3. 上传一篇 PDF，观察 `docker logs -f sm_worker`
4. 确认 `ingest_tasks.stage` 从 `queued` → `parsing` → `indexing` → `done`
5. 检查 `doc_blocks` 有 text/table/figure/formula，且多数块含 `page_num` / `bbox`
6. 检查 `papers` 元数据与 `citations` 引用边
7. 进入前端对话页测试 SSE 问答和引用溯源

## 后续优化方向

- Docling 输出结构适配可根据真实 PDF 样本继续细化，尤其是公式和图片裁剪。
- GROBID 启动较慢，首次拉取镜像也较大，CI/开发环境可按需切回 `REFERENCE_PARSER_PROVIDER=llm`。
- 大表、图像和公式的摘要质量仍需通过真实论文样本评估。
- 两阶段文档路由、引用图谱可视化和解析质量评测可作为下一阶段重点。
