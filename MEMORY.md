# MEMORY.md

> 跨会话的关键洞察与已知陷阱。任务开始前先读，结束后有新发现就追加一行。
> 格式：`- [类型] 结论 —— 为什么 / 怎么做`

## 已知陷阱（必读）

- [坑] **图片/页码绝不能在入库时丢** —— 前身项目 `process_items` 重建 dict 时漏拷 `image/page_num`，导致图搜不到、无法溯源到页。本项目每个 chunk 强制带 `page_num/bbox/block_id/image_key`。
- [坑] **单一 embedding 跨语言不可靠** —— 实测中文搜英文召回差。解法：Query 翻译(中→英) + 入库时每块生成中文摘要，两条同语言通道 + 跨语言兜底，RRF 融合。
- [坑] **维度必须三方一致** —— `.env` 的 `EMBEDDING_DIM` == Milvus `dense_vec` 维度 == 模型实际输出维度，不一致直接报错或召回乱。
- [坑] **Milvus 必须建索引并 load** —— 没建 HNSW = FLAT 暴力扫，几百万 chunk 卡死。建完确认 index built + collection loaded。
- [事实] **HNSW 是 ANN，不是全库扫** —— 分区内几百万向量也是亚线性图搜索，速度不是瓶颈；相关性收窄靠 `paper_id/folder_id/acl` scalar 过滤 + 大范围时两阶段文档路由，不是靠分区。
- [坑] **大表别塞一个 chunk** —— 一张大表→一个向量语义被稀释。走小-大检索：摘要入库，命中后按 `block_id` 取 `doc_blocks` 整表喂 LLM。
- [坑] **批量上传别用 BackgroundTasks** —— 进程重启任务丢、不能限并发。用 RQ：状态进 `ingest_tasks`，可关页面、可重试、可恢复。
- [坑] **项目不能放在 exFAT / Removable 盘** —— Docker Desktop WSL2 后端只把 NTFS 固定盘挂进 `docker-desktop` distro，exFAT/Removable 盘会被跳过，所有 host bind mount 静默回退成空目录（`backend/` 容器内只剩残片，mysql/pg/etcd/minio init 全炸）。且 exFAT 无 POSIX 权限/inode/symlink，即使强挂 DB 数据目录也会坏。**项目必须放 NTFS 固定盘**（如 `C:\` 或 `D:\` 内置 SSD）。诊断命令：`wsl -d docker-desktop -- mount | grep 9p` 看有哪些盘被挂；`Get-Volume -DriveLetter <X>` 看 `DriveType`/`FileSystem`。

## 设计决策

- [决策] 关系库双库：MySQL 存业务(用户/论文/引用图/日志)，PostgreSQL 存对话记忆 —— database-per-service，chat_agent 独占 PG。
- [决策] 队列用 RQ 不用 Celery —— 项目已引入 Redis，RQ 是其延伸，并且心智与维护成本较低；架构留了换 Celery 的余地。
- [决策] 意图路由是对话入口 —— 闲聊→直接 LLM 不检索；知识问题→RAG；复杂→Agent。省延迟、抑制幻觉（Self-RAG/自适应检索）。
- [决策] 模型全走 OpenAI 兼容接口 + `.env` 配版本 —— 可一键切 Qwen3/DeepSeek/vLLM/Ollama，版本不绑死代码。
- [决策] Docling 作为默认 PDF 解析 Provider，MinerU 仅保留显式配置回退 —— MinerU 云端 Pipeline 易受服务侧配置影响；Docling 本地解析优先恢复 `doc_blocks -> indexing -> chat` 链路，首版图像块可先保留 caption/page_num/bbox，`image_key` 后续按实际导图能力增强。

## 开发与协作规范

- [规范] **即时 Git 提交以防破坏代码** —— 每次实现或更新完需求后，必须立即进行 Git 提交以防止后续迭代引入 Regression。提交说明必须使用中文，描述要足够详实、具体，能够清晰追溯改动目的和解决的问题。
