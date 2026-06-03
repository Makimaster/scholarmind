# worker — RQ 异步任务（批量解析索引）

消费 Redis 队列 `rq:queue:ingest`，跑 parsing → indexing 全链路。解决"批量上传不能干等、可关页面"。

## 职责
- 监听队列，取出任务执行：`parse_paper` → `index_paper`。
- 全程更新 `ingest_tasks`：stage(queued→parsing→indexing→done/failed) + progress + error。
- 聚合更新 `ingest_batches`（done/total/failed）。

## 关键约定
- **并发控制**：同时解析数 ≤ `INGEST_MAX_CONCURRENCY`（防打爆 GPU），其余排队。
- **失败重试**：单篇失败不影响整批；自动重试 N 次，仍失败标 failed 并存 error_msg。
- **断点续传**：任务持久化在 MySQL，worker 重启后未完成的继续。
- **幂等**：按 file_hash 去重，重复任务跳过。
- 在线时通过 Redis/SSE 把进度推给前端可观测页。

## 启动
`python -m app.worker.main`（compose 的 worker 容器命令）。

## 待开发任务 (TODO)
- RQ enqueue/worker 接线；任务状态机；重试与并发限制；进度回写。
