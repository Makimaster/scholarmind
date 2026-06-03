# 提示词：查询翻译 (query_translate) — 跨语言核心

- **用途**：中文提问翻译成英文，用英文 query 检索英文原文（英↔英最稳），解决"中文搜英文"。
- **输入**：`{question}`
- **输出**：一行英文查询。

## Prompt
```
Translate the following academic question into precise English suitable for searching
English research papers. Keep technical terms accurate. Output only the English query, one line.

Question: {question}
```

## 优化建议
- 已是英文则原样返回（可先检测语言）。
- 与中文摘要检索路、跨语言路并行，三路 RRF 融合（见 rag-pipeline.md 跨语言策略）。
