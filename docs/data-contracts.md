# 数据契约 (Data Contracts) — 唯一真相源

> 本文件是 ScholarMind 所有存储结构的唯一真相源。根 `CLAUDE.md` 只放指针，改 schema 必须改这里。
> 涉及：MySQL(业务) · PostgreSQL(对话记忆) · Milvus(向量) · MinIO(对象) · Redis(缓存/队列/限流)。
>
> **铁律**：所有业务/向量查询必须带 `user_id` 过滤（多租户隔离）；Milvus 必须走索引 + 分区，禁止全库扫。

---

## 1. MySQL — 业务库 `scholarmind`

字符集统一 `utf8mb4`，引擎 `InnoDB`，时间用 `DATETIME`。

```sql
-- 用户
CREATE TABLE users (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  username      VARCHAR(64)  NOT NULL UNIQUE,
  email         VARCHAR(128) NOT NULL UNIQUE,
  password_hash VARCHAR(128) NOT NULL,            -- bcrypt
  role          VARCHAR(16)  NOT NULL DEFAULT 'user',  -- user | admin
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 论文分组 / 知识库（多级文件夹，构建垂直库）
CREATE TABLE folders (
  id         BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id    BIGINT NOT NULL,
  name       VARCHAR(128) NOT NULL,
  parent_id  BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_folders_user (user_id)
);

-- 论文元数据
CREATE TABLE papers (
  id           BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id      BIGINT NOT NULL,                    -- 租户隔离
  folder_id    BIGINT NULL,
  title        VARCHAR(512) NOT NULL,
  authors      JSON NULL,                          -- ["A","B",...]
  abstract     TEXT NULL,
  year         INT NULL,
  doi          VARCHAR(128) NULL,
  arxiv_id     VARCHAR(64)  NULL,
  source       VARCHAR(16)  NOT NULL DEFAULT 'upload',  -- upload | arxiv
  lang         VARCHAR(8)   NULL,                  -- en | zh
  file_hash    CHAR(16)     NOT NULL,              -- xxhash64, 幂等去重
  pdf_key      VARCHAR(256) NOT NULL,              -- MinIO object key
  num_pages    INT NULL,
  chunk_count  INT NOT NULL DEFAULT 0,
  status       VARCHAR(16)  NOT NULL DEFAULT 'pending', -- pending|done|failed
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_user_filehash (user_id, file_hash),  -- 同用户同文件不重复入库
  INDEX idx_papers_user (user_id),
  INDEX idx_papers_folder (folder_id)
);

-- 论文内的“父块”：大表/图/公式的完整内容（小-大检索的“大”一端 + 溯源回显）
CREATE TABLE doc_blocks (
  id          BIGINT PRIMARY KEY AUTO_INCREMENT,
  paper_id    BIGINT NOT NULL,
  user_id     BIGINT NOT NULL,
  block_type  VARCHAR(16) NOT NULL,               -- text|table|figure|formula
  content     LONGTEXT NULL,                       -- 表→HTML，公式→LaTeX，图→caption
  page_num    INT NULL,
  bbox        JSON NULL,                            -- [page,left,top,right,bottom]
  image_key   VARCHAR(256) NULL,                    -- 图片在 MinIO 的 key
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_blocks_paper (paper_id)
);

-- 引用图谱边（GraphRAG 数据源，GROBID 抽取）
CREATE TABLE citations (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  src_paper_id  BIGINT NOT NULL,                   -- 施引论文（库内）
  dst_paper_id  BIGINT NULL,                       -- 被引论文（若已在库则关联）
  dst_title     VARCHAR(512) NULL,                 -- 被引论文标题（未入库时）
  raw_ref       TEXT NULL,                          -- 原始参考文献串
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_cit_src (src_paper_id),
  INDEX idx_cit_dst (dst_paper_id)
);

-- 批量上传批次
CREATE TABLE ingest_batches (
  id         BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id    BIGINT NOT NULL,
  total      INT NOT NULL DEFAULT 0,
  done       INT NOT NULL DEFAULT 0,
  failed     INT NOT NULL DEFAULT 0,
  status     VARCHAR(16) NOT NULL DEFAULT 'running', -- running|done
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_batch_user (user_id)
);

-- 上传→解析→向量化 全链路任务日志（驱动前端进度条，可重试/可恢复）
CREATE TABLE ingest_tasks (
  id          BIGINT PRIMARY KEY AUTO_INCREMENT,
  batch_id    BIGINT NULL,
  user_id     BIGINT NOT NULL,
  paper_id    BIGINT NULL,
  file_name   VARCHAR(256) NOT NULL,
  file_hash   CHAR(16) NOT NULL,
  stage       VARCHAR(16) NOT NULL DEFAULT 'queued', -- queued|parsing|indexing|done|failed
  progress    TINYINT NOT NULL DEFAULT 0,             -- 0-100
  error_msg   TEXT NULL,
  retry_count INT NOT NULL DEFAULT 0,
  started_at  DATETIME NULL,
  finished_at DATETIME NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_task_batch (batch_id),
  INDEX idx_task_user_stage (user_id, stage)
);

-- 用户查询日志（可观测页 + 评估数据来源）
CREATE TABLE query_logs (
  id                 BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id            BIGINT NOT NULL,
  conversation_id    BIGINT NULL,
  question           TEXT NOT NULL,
  rewritten_query    TEXT NULL,
  retrieved_chunk_ids JSON NULL,
  top_k              INT NULL,
  latency_ms         INT NULL,
  prompt_tokens      INT NULL,
  completion_tokens  INT NULL,
  feedback           TINYINT NULL,                 -- 1 赞 / -1 踩 / NULL
  created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_qlog_user (user_id),
  INDEX idx_qlog_time (created_at)
);

-- 接口访问日志
CREATE TABLE access_logs (
  id          BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id     BIGINT NULL,
  method      VARCHAR(8) NOT NULL,
  path        VARCHAR(256) NOT NULL,
  status_code INT NOT NULL,
  ip          VARCHAR(45) NULL,
  latency_ms  INT NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_alog_time (created_at)
);
```

---

## 2. PostgreSQL — 记忆库 `scholarmind_memory`（chat-agent 服务专属）

```sql
CREATE TABLE conversations (
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT NOT NULL,
  title      VARCHAR(256),
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX idx_conv_user ON conversations(user_id);

CREATE TABLE messages (
  id              BIGSERIAL PRIMARY KEY,
  conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role            VARCHAR(16) NOT NULL,            -- user | assistant | system
  content         TEXT NOT NULL,
  citations       JSONB,                            -- [{paper_id,page,chunk_id,image_key}]
  created_at      TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX idx_msg_conv ON messages(conversation_id);

-- 选做（进阶）：语义长期记忆，需启用 pgvector 扩展
-- CREATE EXTENSION IF NOT EXISTS vector;
-- CREATE TABLE memory_items (
--   id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
--   content TEXT NOT NULL, embedding vector(1024),
--   created_at TIMESTAMP NOT NULL DEFAULT now()
-- );
```

---

## 3. Milvus — collection `scholarmind_chunks`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | VARCHAR(主键) | `xxhash64(content_en + paper_id)`，幂等去重 |
| `dense_vec` | FLOAT_VECTOR(1024) | 稠密向量（与 `EMBEDDING_DIM` 一致） |
| `sparse_vec` | SPARSE_FLOAT_VECTOR | 稀疏向量（Qwen3/BGE-M3 输出），混合检索 |
| `content_en` | VARCHAR | 原文（英文） |
| `content_zh` | VARCHAR | 中文摘要+关键词（跨语言召回） |
| `user_id` | INT64 | **partition_key**，租户物理隔离（仅隔离，不负责相关性收窄） |
| `paper_id` | INT64 | scalar 过滤，限定到具体论文 |
| `folder_id` | INT64 | scalar 过滤，限定到某知识库/文件夹（按上下文收窄的主力） |
| `acl` | VARCHAR | 可见性/角色标签，多人场景做权限过滤 |
| `chunk_type` | VARCHAR | text \| table \| figure \| formula |
| `section` | VARCHAR | 所属章节 |
| `page_num` | INT64 | 溯源定位页码 |
| `bbox` | JSON | 高亮原文坐标框 |
| `block_id` | INT64 | → MySQL `doc_blocks.id`，取整表/原图（小-大检索） |
| `image_key` | VARCHAR | → MinIO，答案回显原图 |

**索引（必须建，否则全库暴力扫）**：
- `dense_vec`：`HNSW`，metric `COSINE`，`M=16`，`efConstruction=200`，查询 `ef=64`
- `sparse_vec`：`SPARSE_INVERTED_INDEX`，metric `IP`

**分区**：`partition_key_field = user_id`（仅做租户物理隔离；**不等于**把该用户全部文档一起搜）。

**检索作用域（关键：相关性收窄不靠分区，靠 scalar 过滤 + 两阶段路由）**：
1. **HNSW 是 ANN，非暴力扫**：分区内几百万 chunk 也是亚线性图搜索，速度不是瓶颈。
2. **Scalar 过滤（主力）**：按 UI 上下文限定范围 —
   - 单篇：`user_id=={uid} && paper_id=={pid}`
   - 某知识库：`user_id=={uid} && folder_id=={fid}`
   - 选中多篇：`user_id=={uid} && paper_id in {[...]}`
   - 多人权限：叠加 `acl in {user_roles}`
3. **两阶段检索（大范围/未指定时）**：先用标题+摘要做**文档级粗筛 Top-N 篇**（几万→几十），再 `paper_id in {topN}` 做 chunk 级精搜。对应自适应检索：简单问题锁文件夹轻检索，全库问题先路由再精搜。

→ **分区(隔离) + scalar作用域过滤 + 必要时文档路由**：几万篇也只在选定范围内搜，既不全扫、也不掺无关。`hybrid_search(dense + sparse)` 始终带上述过滤表达式。

---

## 4. MinIO — 对象存储

| Bucket | Key 规则 | 内容 |
|---|---|---|
| `papers` | `{user_id}/{paper_id}/original.pdf` | 上传原文 PDF |
| `figures` | `{user_id}/{paper_id}/{block_id}.png` | 抠出的图片 |

---

## 5. Redis — 缓存 / 队列 / 限流 / 会话

| 用途 | Key 模式 | 值 / TTL |
|---|---|---|
| 嵌入缓存 | `emb:{model}:{md5(text)}` | 向量 / 7d |
| **语义答案缓存** | `ans:{md5(norm_query+scope)}` | 答案JSON / 1h（相似问秒回） |
| 检索结果缓存 | `retr:{md5(query+filters)}` | chunk_ids / 10m |
| 重排缓存 | `rerank:{md5(query+ids)}` | 有序ids / 10m |
| 热点论文元数据 | `paper:{paper_id}` | metadata / 1h |
| **RQ 任务队列** | `rq:queue:ingest` | 解析索引任务 |
| 任务状态镜像 | `task:{task_id}` | {stage,progress} / 1d |
| 短期会话窗口 | `sess:{conversation_id}` | 最近N轮 / 30m |
| 限流 | `ratelimit:{user_id}:{minute}` | 计数 / 60s |

---

## 维度一致性检查清单（防踩坑）

- [ ] `EMBEDDING_DIM`(.env) == Milvus `dense_vec` 维度 == 实际模型输出维度
- [ ] 每个 chunk 入库必带 `user_id / paper_id / page_num / block_id`（页码和图别再丢）
- [ ] Milvus collection 创建后**确认索引已 build + load**，否则查询走暴力扫
- [ ] 所有 DB/Milvus 查询经 `user_id` 过滤中间件
