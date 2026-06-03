# 提示词：HyDE 假设文档 (hyde)

- **用途**：让 LLM 先虚构一段"标准答案"，用高质量假想文档去检索，提升短问句的语义匹配。
- **输入**：`{question}`（学术英文论文库，建议生成英文假设文档以匹配 content_en）
- **输出**：一段假设性答案文本。

## Prompt
```
You are a research assistant. Write a concise, factual hypothetical answer paragraph
(3-5 sentences) to the following question, as if it came from an academic paper.
Use precise academic terminology. Do not say "I don't know"; produce a plausible answer
to be used as a retrieval probe.

Question: {question}

Hypothetical answer:
```

## 优化建议
- 英文论文库 → 生成英文假设文档命中 `content_en` 更准。
- 仅作检索探针，不直接给用户看；可与原 query 向量加权融合。
