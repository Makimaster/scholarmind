---
name: implement-chat-agent
description: chat_agent 对话服务开发规范（意图路由 + SSE 流式 + 带引用生成 + PG 记忆 + LlamaIndex Agent 综述/对比 + 引用图谱）。当在 backend/services/chat_agent 下实现对话、记忆、Agent、SSE 时使用。
---

# chat_agent 对话服务开发规范

开发前先阅读 `docs/api.md` (SSE 格式说明) 与 `backend/services/chat_agent/CLAUDE.md`。

## 实现要点
1. **意图路由**：通过 `intent_router` 提示词对提问分类 —— 闲聊 (`chitchat`) 直答不触发检索；一般提问 (`knowledge`) 走 `retrieval` 检索；复杂分析 (`complex`) 走 Agent 链路；追问 (`followup`) 结合上一轮对话上下文进行检索。
2. **带引用生成**：使用 `answer_with_citation` 提示词，通过 SSE 协议流式推送 Token 响应；当答案中引用了特定 Chunk 时，推送 `cite` 事件（包含 `paper_id`, `page`, `image_key` 等元数据）。
3. **对话记忆管理**：对话历史与消息数据持久化写入 **PostgreSQL** (`conversations` / `messages` 表)；短期多轮对话上下文缓存至 Redis (`sess:{conv_id}`)。
4. **Agent 多步推理**：利用 LlamaIndex Agent 框架，将复杂查询分解为多个子查询，执行跨多篇论文的并行检索，最后进行 `review_generation` 跨论文对比和汇总。
5. **引用图谱接口**：查询 MySQL 中 `citations` 表的关联关系，返回用于可视化的节点与边数据。
6. **日志记录**：每次对话均向 MySQL `query_logs` 中记录问答明细、耗时及 Token 消耗。

## 验收标准
- [ ] 闲聊意图分类正确，确认不触发 RAG 检索（通过日志验证）
- [ ] SSE 推送的引用角标格式正确，前端可解析出对应页码和图片 key
- [ ] 多轮对话上下文生效，大模型能够正确理解代词指代
- [ ] 综述与跨论文对比生成时，产出带引用标注的结构化中文报告
- [ ] 对话记忆数据仅写入 PostgreSQL，不写入 MySQL 业务库
