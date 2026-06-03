# common — 公用基础设施（被所有服务 import）

只放真正公用的东西，业务逻辑不进这里。

## 内容
| 文件 | 职责 |
|---|---|
| `config.py` | Pydantic Settings，读 `.env`（所有模型/库配置的唯一入口） |
| `db/mysql.py` | MySQL async engine + session（业务库） |
| `db/pg.py` | PostgreSQL async engine + session（记忆库，仅 chat_agent 用） |
| `db/mysql_init.sql` / `db/pg_init.sql` | 建表脚本（容器首启自动执行，与 docs/data-contracts.md 一致） |
| `clients/milvus.py` | Milvus 连接 + collection/索引创建 + 混合检索封装 |
| `clients/minio.py` | MinIO 客户端 + bucket 初始化 + 上传/下载 |
| `clients/redis.py` | Redis 连接 + 缓存助手 + RQ 队列 |
| `clients/llm.py` | OpenAI 兼容 LLM/Embedding/Rerank/VLM 适配（按 .env provider 切换） |
| `prompts.py` | 加载 `prompts/*.md` 并填充变量 |
| `auth/` | JWT、密码哈希、user_id 隔离中间件（见 auth/CLAUDE.md） |
| `logging.py` | 结构化日志（loguru） |
| `exceptions.py` | 统一异常 + FastAPI handler |
| `schemas/` | 跨服务共享的 Pydantic 模型（契约） |

## 规则
- 所有 DB/Milvus 查询封装在这里时**必须暴露 user_id 参数**并强制过滤。
- 模型调用统一走 `clients/llm.py`，业务代码不直接拼 HTTP，便于换模型/加重试。
- schema 改动必须同步 `docs/data-contracts.md`（真相源）。
- 维度一致性：`config.EMBEDDING_DIM` 在 `clients/milvus.py` 建 collection 时使用，确保三方一致。
