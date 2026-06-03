# 提示词：意图路由 (intent_router)

- **用途**：对话入口判断用户意图，决定是否走检索，避免闲聊也强行 RAG（降低延迟、抑制幻觉），支持自适应检索。
- **调用位置**：chat_agent，每次提问最先执行。
- **输入变量**：`{question}`、`{history}`（最近几轮）
- **输出**：严格 JSON，便于代码路由。

## Prompt

```
你是学术问答系统的意图路由器。判断用户这句话属于哪类，并输出 JSON。

类别：
- chitchat：闲聊、寒暄、与论文无关的常识（如"你好""你能干嘛""今天天气"）→ 不检索
- knowledge：针对已入库论文的具体问题（方法/数据/结论/公式/图表）→ 走 RAG 检索
- complex：需要跨多篇对比、综述、多跳推理（含"对比""综述""有哪些相关工作"）→ 走 Agent
- followup：对上一轮答案的追问（"那它的实验呢""再详细点"）→ 带历史走 RAG

对话历史：
{history}

当前提问：{question}

只输出 JSON，不要解释：
{"intent": "chitchat|knowledge|complex|followup", "need_retrieval": true|false, "reason": "一句话"}
```

## 优化建议（可根据实际效果调优）
- 边界模糊时倾向 `knowledge`（宁可多检索一次也别漏）。
- 可加入 few-shot 例子提升准确率；可换更小更快的模型降延迟。
