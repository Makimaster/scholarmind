# ScholarMind 任务 1-5 完整实现对照文档

## 前置说明

项目骨架已完成：路由文件、Schema、worker 入口、config、MySQL/PG 建表 SQL 均已就位，但全部是 Mock 数据。
任务 1-5 的工作就是**把 Mock 替换成真实实现**。

告诉 AI 时的通用格式：
> "你是 ScholarMind 项目的后端工程师。项目内容见用 CLAUDE.md。
>  当前文件 XXX 是 Mock 实现，请按以下要求改为真实逻辑，不要改动文件结构和路由路径。"

---

## 任务 1：解析服务对接

### 目标文件
```
backend/services/parsing/parser.py          ← 核心（已创建骨架）
backend/app/routers/papers.py               ← upload 接口需接入真实 DB + RQ
backend/app/worker/main.py                  ← 需分发 parse 任务到 parsing.parser
```

### 现状
- `papers.py` upload 接口把文件存到内存 MOCK_PAPERS，没有写 MySQL，没有上传 MinIO，没有入 RQ 队列
- `parser.py` 骨架已写（MinerU + LLM 参考文献 + VLM），但 `_call_mineru` 是 HTTP stub，需要对接真实 MinerU SDK
- `worker/main.py` 只启动了 RQ worker，没有 job handler

### 要告诉 AI 的内容

**papers.py upload 接口**：
```
请修改 backend/app/routers/papers.py 的 upload_papers 函数：
1. 接收上传的 PDF 文件，用 xxhash64 计算 file_hash（16位hex）
2. 检查 MySQL papers 表是否已有 (user_id, file_hash) 记录，有则跳过（幂等）
3. 将 PDF 上传到 MinIO，bucket=papers，key={user_id}/{paper_id}/original.pdf
4. 向 MySQL 写入 papers 记录（status=pending），ingest_batches 记录，ingest_tasks 记录（stage=queued）
5. 把 parse 任务入 RQ ingest 队列，payload = {user_id, paper_id, pdf_key, task_id}
6. 返回 {batch_id, tasks}

依赖：
- common/clients/minio.py（MinIO 上传）
- common/clients/redis.py（RQ 队列）
- common/db/mysql.py（AsyncSession）
- user_id 从 JWT 中间件注入（当前 Mock 写死 999，暂时保持）
```

**worker/main.py job handler**：
```
请在 backend/app/worker/main.py 中添加 job handler 函数 handle_ingest_job：
1. 接收参数 user_id, paper_id, pdf_key, task_id
2. 更新 ingest_tasks.stage = parsing, progress = 10
3. 调用 services/parsing/parser.py 的 parse_paper(user_id, paper_id, pdf_key, db)
4. 解析完成后更新 ingest_tasks.stage = indexing, progress = 50
5. 调用 services/indexing（待实现），完成后 stage=done, progress=100
6. 异常时 stage=failed, error_msg=str(e)
把这个函数注册为 RQ 队列的 job function。
```

**MinerU 对接（parser.py 的 _call_mineru）**：
```
请修改 backend/services/parsing/parser.py 中的 _call_mineru 函数：
使用 mineru-kie-sdk 的 MineruKIEClient：
1. 上传 PDF bytes 到 MinerU
2. 轮询获取解析结果（带超时，最多等 300s）
3. 解析结果转换为 Block 列表：
   - type=text → Block(block_type='text', content=..., page_num=..., bbox=...)
   - type=table → Block(block_type='table', content=HTML字符串, ...)
   - type=figure → Block(block_type='figure', image_key=..., content=caption, ...)
   - type=formula → Block(block_type='formula', content=LaTeX, ...)
每个 Block 必须带 page_num 和 bbox，不能丢。
```

### 数据契约关键字段
- `papers`：file_hash CHAR(16)，status: pending|done|failed，pdf_key VARCHAR(256)
- `doc_blocks`：block_type, content, page_num, bbox(JSON), image_key
- `citations`：src_paper_id, dst_title, raw_ref
- MinIO bucket `papers`：key = `{user_id}/{paper_id}/original.pdf`
- MinIO bucket `figures`：key = `{user_id}/{paper_id}/{block_id}.png`

---

## 任务 2：切分与向量化入库

### 目标文件
```
backend/services/indexing/chunker.py        ← 新建：智能切分器
backend/services/indexing/enricher.py       ← 新建：双语增强（LLM 生成中文摘要）
backend/services/indexing/vectorizer.py     ← 新建：embedding + 写 Milvus
backend/services/indexing/__init__.py       ← 新建：暴露 index_paper(ParseResult)
```

### 要告诉 AI 的内容

**chunker.py**：
```
请新建 backend/services/indexing/chunker.py，实现 chunk_blocks(blocks: list[Block]) -> list[Chunk]：
Chunk 数据类包含：content_en, block_type, page_num, bbox, block_id, image_key, section

切分规则：
1. block_type=table/figure/formula：整块不切，直接作为一个 Chunk
2. block_type=text：按章节语义切分，目标 512 token，重叠 15-20%（约 80 token）
3. 切分用 LlamaIndex 的 SentenceSplitter，chunk_size=512，chunk_overlap=80
4. 每个 Chunk 记录来源 block_id（→ MySQL doc_blocks.id，用于小-大检索）
5. 章节标题识别：text 块首行全大写或 ## 开头的视为 section header，记录到 section 字段
```

**enricher.py**：
```
请新建 backend/services/indexing/enricher.py，实现 enrich_chunks(chunks: list[Chunk]) -> list[Chunk]：
1. 对 block_type=text 的英文 chunk，调用 LLM 生成中文摘要+关键词，写入 chunk.content_zh
2. 使用 prompts/enrich_zh_summary.md 中的提示词
3. 批量并发处理（asyncio.gather），每批 8 个，避免并发过高
4. 非英文 chunk 或 table/figure/formula：content_zh = content_en（直接复用）
5. figure block：content_zh 用 VLM 生成的描述（已在 parser 阶段写入 block.content_zh）
```

**vectorizer.py**：
```
请新建 backend/services/indexing/vectorizer.py，实现 vectorize_and_store(chunks, user_id, paper_id, folder_id)：
1. 调用 common/clients/llm.py 的 embed_texts() 批量获取 dense 向量（维度=EMBEDDING_DIM）
2. sparse 向量用 BM25 / BGE-M3 sparse 输出（如 embedding provider 不支持 sparse，用 llama_index 的 BM25Retriever 本地计算）
3. 每个 chunk 的 Milvus 写入字段：
   id = xxhash64(content_en + str(paper_id))  ← 幂等去重
   dense_vec, sparse_vec
   content_en, content_zh
   user_id, paper_id, folder_id
   chunk_type, section, page_num, bbox, block_id, image_key
4. 用 Milvus 的 insert() 批量写入（batch 256）
5. 写完后更新 MySQL papers.chunk_count += len(chunks)
依赖 common/clients/milvus.py。
```

### 数据契约关键字段
- Milvus `scholarmind_chunks`：dense_vec(1024), sparse_vec, content_en, content_zh, user_id(partition_key), paper_id, folder_id, chunk_type, section, page_num, bbox, block_id, image_key
- id = xxhash64，幂等去重
- HNSW 索引：M=16, efConstruction=200；sparse：SPARSE_INVERTED_INDEX

---

## 任务 3：混合检索服务

### 目标文件
```
backend/services/retrieval/query_optimizer.py   ← 新建：改写+翻译+HyDE（并发）
backend/services/retrieval/searcher.py          ← 新建：Milvus 混合检索 + RRF
backend/services/retrieval/reranker.py          ← 新建：调 Rerank API + Corrective RAG
backend/services/retrieval/__init__.py          ← 新建：暴露 retrieve(query, scope) -> list[Chunk]
```

### 要告诉 AI 的内容

**query_optimizer.py**：
```
请新建 backend/services/retrieval/query_optimizer.py，实现 optimize_query(question, conversation_history) -> QueryBundle：
QueryBundle 包含：original, rewritten, translated_en, hyde_doc

并发执行（asyncio.gather）：
1. 查询改写：prompts/query_rewrite.md，补全代指词和上下文
2. 中→英翻译：prompts/query_translate.md
3. HyDE：prompts/hyde.md，生成假设性英文答案段落

settings.ENABLE_QUERY_REWRITE / ENABLE_QUERY_TRANSLATION / ENABLE_HYDE 控制开关，
关闭时直接用原始 question。
```

**searcher.py**：
```
请新建 backend/services/retrieval/searcher.py，实现 hybrid_search(query_bundle, scope, top_k) -> list[ScoredChunk]：
scope 包含：user_id, folder_id=None, paper_ids=None

三路检索（asyncio.gather 并发）：
1. 英文检索：embed(translated_en) → Milvus dense 检索 content_en
2. 中文检索：embed(rewritten) → Milvus dense 检索 content_zh
3. HyDE 检索：embed(hyde_doc) → Milvus dense 检索 content_en

所有检索必须带 user_id 过滤：
  单篇：user_id=={uid} && paper_id in {paper_ids}
  文件夹：user_id=={uid} && folder_id=={fid}
  全局：user_id=={uid}

三路结果用 RRF 合并，公式：score = Σ 1/(k+rank_i)，k=60，返回去重后的 top_k。
```

**reranker.py**：
```
请新建 backend/services/retrieval/reranker.py，实现：
1. rerank_chunks(question, chunks, top_n) -> list[ScoredChunk]
   调用 common/clients/llm.py 的 rerank()
   settings.ENABLE_RERANK=False 时直接返回前 top_n 个

2. corrective_grade(question, chunks) -> list[ScoredChunk]（仅 ENABLE_CORRECTIVE_RAG=True 时生效）
   用 prompts/corrective_grade.md 对每个 chunk 打分（0-1）
   过滤低于 0.5 的，不足 3 个时触发查询改写重检（递归一次，不循环）
```

---

## 任务 4：对话与 Agent 综述

### 目标文件
```
backend/app/routers/chat.py                 ← Mock 替换为真实实现
backend/app/routers/advanced.py             ← Mock 替换为真实实现
backend/services/chat_agent/agent.py        ← 新建：意图路由 + RAG 生成 + SSE
backend/services/chat_agent/memory.py       ← 新建：PostgreSQL 会话记忆读写
backend/services/chat_agent/reviewer.py     ← 新建：LlamaIndex Agent 综述
```

### 要告诉 AI 的内容

**memory.py**：
```
请新建 backend/services/chat_agent/memory.py，实现：
1. get_history(conversation_id, limit=10) -> list[dict]
   从 PostgreSQL messages 表读取最近 N 条，格式 [{role, content}]
2. save_message(conversation_id, role, content, citations=None)
   写入 PostgreSQL messages 表，citations 序列化为 JSONB
3. get_or_create_conversation(user_id, title, folder_id, paper_ids) -> int
   PostgreSQL conversations 表 upsert，返回 conversation_id

数据库连接用 common/db/pg.py 的 AsyncSession。
```

**chat.py query 接口**：
```
请修改 backend/app/routers/chat.py 的 chat_query 接口，替换 SSE mock 为真实实现：

流程：
1. 从 PostgreSQL 读取 conversation 最近 10 条历史（memory.get_history）
2. 意图路由（prompts/intent_router.md）：
   - 闲聊/常识 → 直接 LLM 回答，跳过检索
   - 知识问题 → RAG 流程
   - 复杂综述/对比 → 转 Agent
3. RAG 流程：
   a. optimize_query(question, history) → QueryBundle
   b. hybrid_search(query_bundle, scope) → chunks
   c. rerank_chunks(question, chunks) → top_n_chunks
   d. 构造 prompt（prompts/answer_with_citation.md），流式生成
4. SSE 输出格式：
   event: cite  data: {paper_id, paper_title, page_num, bbox, chunk_type, content, image_key}
   event: token data: {delta: "..."}
   event: done  data: {latency_ms: ...}
5. 生成完成后写 PostgreSQL messages 表（SSE done 之后才写，防截断落库）
6. 写 MySQL query_logs 表（question, latency_ms, prompt_tokens, completion_tokens）
```

**reviewer.py（Agent 综述）**：
```
请新建 backend/services/chat_agent/reviewer.py，实现 generate_review(topic, scope, user_id) -> AsyncGenerator[str]：

用 LlamaIndex ReActAgent 实现：
1. 把 hybrid_search 封装为 LlamaIndex QueryEngineTool
2. Agent 收到 topic 后自动分解为 3-5 个子问题
3. 对每个子问题调用检索工具获取 chunks
4. 用 prompts/review_generation.md 提示词整合生成综述
5. 流式 yield，cite 事件先于 token 事件发出

在 advanced.py 的 /review/generate 接口调用，替换 mock。
```

---

## 任务 5：前端页面与 API 联调

### 目标文件
```
frontend/src/api/index.ts（或 request.ts）  ← Axios 封装 + JWT 拦截器
frontend/src/stores/auth.ts                 ← 真实登录/注册流程
frontend/src/pages/Chat.vue                 ← SSE 流解析 + 引用溯源渲染
frontend/src/pages/Observability.vue        ← 真实接口数据
```

### 要告诉 AI 的内容

**Axios 封装**：
```
请在 frontend/src/api/ 中创建统一 Axios 实例：
1. baseURL = http://localhost:8008/api
2. 请求拦截器：从 localStorage 取 token，自动加 Authorization: Bearer <token> 头
3. 响应拦截器：401 时跳转登录页
4. 把所有 mock 调用替换为真实接口，接口路径见 docs/api.md
```

**Chat.vue SSE 流解析**：
```
请修改 frontend/src/pages/Chat.vue 的问答流程：
1. 用 fetch + ReadableStream 读取 POST /api/chat/query 的 SSE 响应（不用 EventSource，需要带 POST body）
2. 解析事件：
   event: cite → citations 数组存储，等文本中 [N] 角标出现时关联
   event: token → delta 追加到消息文本，实时渲染
   event: done → 停止流
3. 点击 [N] 角标或底部引用卡片时，右侧 Preview 区展示：
   chunk_type=text → 原文段落
   chunk_type=table → 渲染 HTML 表格
   chunk_type=figure → 显示图片（URL = http://localhost:9000/figures/{image_key}）
   chunk_type=formula → KaTeX 渲染 LaTeX
```

---

## 实现优先级

```
第1天：任务1（upload接口+RQ入队）+ 任务2（chunker+vectorizer）= 数据能入库
第2天：任务3（混合检索）+ 任务4 memory + chat RAG流程 = 能问答
第3天：任务4 reviewer（Agent综述）+ 任务5（前端联调）= 完整闭环
```

---

## 现有文件速查

| 需要用到 | 文件位置 | 状态 |
|---------|---------|------|
| LLM/Embedding/Rerank 调用 | `backend/common/clients/llm.py` | ✅ 已实现 |
| 解析入口 | `backend/services/parsing/parser.py` | ✅ 已实现骨架 |
| 配置 | `backend/common/config.py` | ✅ 已实现 |
| 提示词 | `backend/prompts/*.md` | ✅ 全部已有 |
| API Schema | `backend/app/schemas/*.py` | ✅ 全部已有 |
| 路由骨架 | `backend/app/routers/*.py` | ⚠️ 全部 Mock，待替换 |
| MySQL Session | `backend/common/db/mysql.py` | ❌ 待创建 |
| PG Session | `backend/common/db/pg.py` | ❌ 待创建 |
| Milvus 客户端 | `backend/common/clients/milvus.py` | ❌ 待创建 |
| MinIO 客户端 | `backend/common/clients/minio.py` | ❌ 待创建 |
| Redis/RQ 客户端 | `backend/common/clients/redis.py` | ❌ 待创建 |
| 数据契约 | `docs/data-contracts.md` | ✅ 字段定义真相源 |

---

## 踩坑预防（必读）

1. **所有 DB/Milvus 查询必须带 user_id 过滤**，没有等于多租户泄露
2. **EMBEDDING_DIM=1024** 与 Milvus dense_vec 维度必须一致，建 collection 前确认
3. **大表/公式/图不切碎**，整块存 doc_blocks，chunk 里只存摘要+block_id 指针
4. **解析任务只在 RQ worker 里跑**，不在 FastAPI 请求线程同步执行
5. **xxhash64 幂等**：同一 (user_id, file_hash) 不重复入库；同一 chunk_id 不重复写 Milvus
6. **SSE done 事件之后才写 messages 表**，流中断不落库截断内容
7. **Chat.vue 不能用 EventSource**，因为 SSE 需要 POST body，必须用 fetch + ReadableStream
