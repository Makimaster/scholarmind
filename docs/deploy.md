# 部署与运行

## 一键起基础设施（全 Docker）

```bash
cp backend/.env.example backend/.env     # 填模型 API Key / 改密码
docker compose up -d --build
docker compose ps                         # 确认全部 healthy
```

启动的容器：mysql(3306) · postgres(5432) · redis(6379) · minio(9000/9001) · etcd · milvus(19530) · grobid(8070) · mineru(8001) · embedding(8080) · reranker(8081) · backend(8000) · worker。

## 前端本地跑（联调方便）

```bash
cp frontend/.env.example frontend/.env
cd frontend && npm install && npm run dev   # http://localhost:5173
```

## 初始化

- MySQL/PG：容器首次启动自动执行 `backend/common/db/*.sql` 建表。
- Milvus collection + 索引：backend 启动时检查并自动创建（见 indexing 服务）。
- MinIO bucket（papers/figures）：backend 启动时自动创建。

## 常用运维

```bash
docker compose logs -f backend        # 后端日志
docker compose logs -f worker         # 入库任务日志
docker compose restart backend        # 改代码后重启
docker compose down                   # 停止 (保留数据)
docker compose down -v                # 停止并清空数据卷(慎用)
```

## 模型切换

- 用云 API：把 `.env` 里 `EMBEDDING_PROVIDER/RERANK_PROVIDER` 改 `dashscope`，填 key，注释掉 compose 里 embedding/reranker 服务。
- 换本地模型：改 compose 里 embedding/reranker 的 `--model-id`，并保证 `EMBEDDING_DIM` 一致。

## 资源提示

- MinerU 有 GPU 快很多（compose 里有 GPU 配置注释，打开即用）。
- Milvus + ES 类组件吃内存，建议 Docker 分配 ≥ 8GB。
- 首次拉镜像 + 下模型较慢，耐心等。
