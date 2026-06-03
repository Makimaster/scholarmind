---
name: tune-rag-prompts
description: prompts 运行时提示词调优规范（针对查询改写/HyDE/答案生成/CorrectiveRAG 等提示词的优化流程）。当调整优化 RAG 各环节提示词时使用。
---

# 运行时提示词调优规范

运行时提示词集中存放在 `prompts/*.md`。在代码中，通过 `common/prompts.py` 动态加载并注入运行时变量。修改此目录下的文件即可调整模型输出行为，无需更改后端逻辑。

## 调优流程
1. **定位瓶颈环节**：
   - 检索召回偏低或偏置：重点优化 `query_rewrite.md`, `multi_query.md`, `hyde.md`, `query_translate.md` 等。
   - 答案生成幻觉或格式有误：重点优化 `answer_with_citation.md`, `corrective_grade.md` 等。
   - 闲聊误触检索：优化 `intent_router.md`。
2. **小步迭代与对比**：每次仅修改一个提示词，在预设的测试问题集上进行运行测试，结合 `query_logs` 分析生成效果。
3. **跨语言优化**：在中译英和摘要生成环节，重点优化 `query_translate.md`（翻译准确度）与 `enrich_zh_summary.md`（摘要质量）。
4. **提升忠实度**：在 `answer_with_citation.md` 中强化“对于未提及的信息，必须明确拒绝回答或说明未知”的硬性约束；可选用自检 (`self_rag_reflect`) 提示词校验结果。

## 验收标准
- [ ] 召回率/命中率 (Top-K hit) 较改动前有所提升
- [ ] 忠实度（有明确出处的比例）上升，模型幻觉率下降
- [ ] 闲聊误触检索率降低
- [ ] 每次提示词修改需附带基准对比测试报告（使用可观测日志中的真实问题作为评测依据）
