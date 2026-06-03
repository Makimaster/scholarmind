# 提示词：CorrectiveRAG 检索质量打分 (corrective_grade)

- **用途**：评估检索到的片段是否足以回答问题。不够则触发改写重检 / 降级拒答，避免拿垃圾资料硬答。
- **调用位置**：retrieval，重排后、生成前。
- **输入**：`{question}`、`{context}`
- **输出**：JSON 评级。

## Prompt
```
判断下列【参考资料】是否足以准确回答【问题】。

【问题】：{question}
【参考资料】：
{context}

评估并只输出 JSON：
{"grade": "sufficient|partial|insufficient",
 "reason": "一句话",
 "action": "answer|rewrite_retry|reject"}
说明：sufficient→answer；partial→可答但提示不完整；insufficient→rewrite_retry 或 reject。
```

## 优化建议
- `insufficient` 时：先 rewrite_retry 一次，仍不行则 reject（"知识库中未找到相关内容"）。
- 阈值可调；可结合 reranker 分数双重判断。
