# 提示词：参考文献提取 (extract_references) — LLM 解析模式

- **用途**：当 REFERENCE_PARSER_PROVIDER=llm 时，用 LLM 从论文文本中提取结构化参考文献列表，替代 GROBID。
- **调用位置**：parsing/parser.py，parse_paper 流程末尾。
- **输入**：`{references_text}` — 论文 References 章节原文
- **输出**：JSON 数组，每项含 title / authors / year / raw_ref

## Prompt

```
你是学术文献解析助手。以下是一篇论文的参考文献章节原文，请提取所有参考文献条目，输出 JSON 数组。

参考文献原文：
{references_text}

输出格式（严格 JSON，不要加任何解释）：
[
  {{
    "title": "论文标题",
    "authors": ["作者1", "作者2"],
    "year": 2023,
    "raw_ref": "原始参考文献字符串"
  }}
]

规则：
- title/authors/year 尽量从原文中提取，无法确定则留空字符串或 null
- raw_ref 保留原始引用字符串，不做修改
- 只输出 JSON 数组，不要输出任何其他内容
```
