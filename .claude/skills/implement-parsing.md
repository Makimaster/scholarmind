---
name: implement-parsing
description: parsing 解析服务开发规范（Docling 版面解析 + GROBID 元数据/参考文献 + VLM 图描述）。当在 backend/services/parsing 下实现解析、处理 PDF 双栏/公式/表格/图片、维护 doc_blocks/papers/citations 时使用。
---

# parsing 解析服务开发规范

开发前先阅读 `docs/data-contracts.md`（`papers` / `doc_blocks` / `citations` 契约）与 `backend/services/parsing/CLAUDE.md`。

## 当前解析职责拆分

1. **Docling 版面解析（默认）**：在 worker 内本地解析 PDF，输出正文、表格、图片/图注、公式/数学内容以及尽量完整的 `page_num` / `bbox`。统一转换为 `Block`，再写入 `doc_blocks`。
2. **GROBID 学术结构化（默认）**：调用 `GROBID_BASE_URL/api/processFulltextDocument` 解析 TEI XML，抽取标题、作者、摘要、年份、DOI 和参考文献，回填 `papers` / `citations`。
3. **LLM 引用降级**：GROBID 不可用或失败时，使用 `prompts/extract_references.md` 从 Docling 文本块中抽取参考文献，不能阻断整篇入库。
4. **VLM 图描述**：只有当 figure block 有 `image_key` 时，才调用 VLM 生成中文图像描述；无 `image_key` 的图块应保留 caption/page/bbox 并跳过 VLM。

## 关键实现约束

- 解析必须由 RQ worker 调用，禁止在 FastAPI 请求线程同步跑重解析。
- 保持 `Block` / `ParseResult` 契约稳定：`block_type/content/page_num/bbox/image_key/content_zh/block_id`。
- `block_type` 只使用 `text | table | figure | formula`，不要新增未同步 schema 的类型。
- 每个可解析 block 尽量保留 `page_num` 和 `bbox`；缺失要记录 warning。
- 大表、图片、公式父块整体写入 `doc_blocks`，切分和小-大检索由 indexing 阶段处理。
- MinerU 仅作为显式配置的历史兼容 Provider，不再作为默认方案。

## 验收标准

- [ ] Docling 能解析普通双栏论文，正文顺序不明显错乱。
- [ ] `doc_blocks` 中 content 非空，且 block_type 合法。
- [ ] 大部分 text/table/figure block 有 `page_num`，bbox 可 JSON 序列化。
- [ ] GROBID 成功时能回填 papers 元数据并写入 citations。
- [ ] GROBID 失败时能 fallback 到 LLM 引用抽取，不阻断整篇解析。
- [ ] worker 日志明确记录 parser provider、reference provider、block 类型统计和失败原因。
