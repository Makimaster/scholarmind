# chat_agent — 对话 / Agent 服务（独占 PostgreSQL）

对话入口：意图路由 → 检索/直答/Agent → 流式生成 + 溯源 + 记忆。

## 流程
1. **意图路由**（intent_router）：闲聊→直接 LLM 不检索；knowledge→retrieval；complex→Agent 综述/对比；followup→带历史检索。
2. 知识问题：调 `retrieval.retrieve()` → answer_with_citation 流式生成 → 角标溯源。
3. 复杂问题：Agent（LlamaIndex）多步：子查询分解 → 多篇检索 → review_generation / 跨论文对比。
4. （可选）self_rag_reflect 自检有无出处。
5. 记忆：会话/消息写 **PostgreSQL**（conversations/messages）；短期窗口缓存 Redis `sess:{conv_id}`。

## 关键约定
- **记忆只用 PG**，不写 MySQL（database-per-service）。
- SSE 流式：按 api.md 的 event 格式推 token/cite/done/error。
- 每次问答写 `query_logs`（MySQL，可观测页用）。
- 引用必须可点击溯源：cite 事件带 paper_id/page/chunk_id/image_key。

## 接口
- `POST /api/chat/query`（SSE）；`POST /api/review/generate`（SSE，Agent 综述）。

## 待开发任务 (TODO)
- 意图路由；SSE 生成；多轮记忆读写；LlamaIndex Agent 综述/对比；引用图谱查询。
