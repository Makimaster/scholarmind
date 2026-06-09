# ScholarMind（文渊）— 跨语言学术文献智能调研系统

学术文献智能调研 Copilot：支持双栏 PDF、公式及图表深度解析，提供精准的中文溯源问答，并基于引用网络实现跨文献对比与自动化综述生成。

## 能力

- 多论文问答 + 角标溯源（定位页码 / 回显原图）
- 单篇深读（讲清方法 / 解释公式 / 看懂图表）
- 跨论文对比（多跳，基于引用图谱）
- 自动文献综述（Agentic，带引用）
- 多轮对话 + 记忆
- 意图识别：闲聊不走检索，知识问题走 RAG，复杂走 Agent

## 技术栈

| 类别 | 技术 |
|------|------|
| 后端 | Python 3.11 + FastAPI (async) + SQLAlchemy + RQ |
| RAG | LlamaIndex（IngestionPipeline + MilvusVectorStore + Agent）|
| 模型 | Qwen3 系列（LLM / Embedding / Reranker / VL），OpenAI 兼容接口 |
| 解析 | Docling（正文/公式/表/图，本地开源解析）+ GROBID（论文元数据/参考文献结构化）+ MinerU（可选回退）|
| 向量库 | Milvus 2.5（HNSW 索引 + user_id 分区）|
| 业务库 | MySQL 8.0 |
| 记忆库 | PostgreSQL 16 |
| 缓存/队列 | Redis 7（缓存 + RQ 任务队列）|
| 对象存储 | MinIO（PDF / 图片）|
| 前端 | Vue 3 + Vite + Pinia + Vue Router |

## 快速开始

### 前置条件

- Docker & Docker Compose
- Node.js >= 18
- 一个 OpenAI 兼容的 API Key（推荐阿里云通义千问 DashScope）

### 步骤

```bash
# 1. 复制环境配置文件并填写 API Key
cp backend/.env.example backend/.env

# 2. 启动基础设施与后端 API
docker compose up -d --build

# 3. 安装前端依赖并启动
cp frontend/.env.example frontend/.env
cd frontend && npm install && npm run dev
```

### 访问地址

- 后端 API：http://localhost:8008/docs
- 前端 UI：http://localhost:5173
- MinIO 控制台：http://localhost:9001

## 系统架构

```
用户 → 前端(Vue3) → FastAPI → 意图路由
                                 ├── 闲聊 → 直接 LLM 回复
                                 ├── 知识 → 混合检索 → 重排 → RAG 生成
                                 └── 复杂 → Agent 多步检索 → 综述生成
```

详细的架构说明见 [docs/architecture.md](docs/architecture.md)。

## 核心流程

1. **PDF 解析** — Docling 本地解析双栏论文（正文/公式/表格/图片，保留页码和 bbox），GROBID 抽取论文元数据与参考文献，LLM 作为引用抽取降级方案
2. **向量化入库** — 智能切分 + 中文摘要增强 + Embedding 写入 Milvus（含 HNSW 索引）
3. **混合检-重排** — Query 改写 + 翻译 + HyDE → Dense/Sparse 双路召回 → RRF 融合 → Reranker 重排
4. **对话生成** — 意图路由 → 检索/Agent → SSE 流式生成 → 角标溯源 → 持久化记忆

详细的 RAG 链路设计见 [docs/rag-pipeline.md](docs/rag-pipeline.md)。

## 数据契约

所有表结构、Milvus Schema、Redis Key 设计的唯一真相源： [docs/data-contracts.md](docs/data-contracts.md)。

## API

完整的 API 文档见 [docs/api.md](docs/api.md)，部署指南见 [docs/deploy.md](docs/deploy.md)。

## 项目状态

核心 RAG 链路已开发完成并经过集成测试：
- PDF 解析与向量化入库 ✅
- 混合检索与重排 ✅
- 流式问答与溯源 ✅
- Agent 综述生成 ✅
- 多租户鉴权 ✅
- 前端真实 API 联调 ✅

## License

MIT
