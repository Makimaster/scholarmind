---
name: implement-parsing
description: parsing 解析服务开发规范（MinerU 双栏/公式/表/图 + GROBID 引用 + VLM 图描述）。当在 backend/services/parsing 下实现解析、对接 MinerU/GROBID、处理 PDF 双栏/公式/表格/图片时使用。
---

# parsing 解析服务开发规范

开发前先阅读 `docs/data-contracts.md` (关于 `doc_blocks`, `papers`, `citations` 的定义) 与 `backend/services/parsing/CLAUDE.md`。

## 实现要点
1. **MinerU 对接**：通过 HTTP 接口调用 `MINERU_BASE_URL`，输入从 MinIO 获取的 PDF 文件，获取正文块（包含阅读顺序）、公式（LaTeX 格式）、表格（HTML 格式）、图片（二进制及 BBox 坐标）。
2. **GROBID 对接**：通过 HTTP 调用 `GROBID_BASE_URL/api/processFulltextDocument`，解析 TEI 格式数据，抽取标题、作者、摘要、参考文献，并将其写入 `papers` 和 `citations` 表。
3. **图片处理**：将抠出的图片存储至 MinIO (`figures/{user_id}/{paper_id}/{block_id}.png`)，调用 VLM (使用 `figure_caption` 提示词) 生成中文描述。
4. **数据归一化**：将所有解析出的内容块统一转换为 `doc_blocks` 的 schema (`block_type`, `content`, `page_num`, `bbox`, `image_key`) 并持久化写入数据库。
5. **健壮性保障**：实现超时重试机制，解析失败时抛出明确异常供 Worker 标记任务状态为 `failed`。

## 验收标准
- [ ] 双栏论文正文顺序解析正确（确保不串行）
- [ ] 公式以 LaTeX、表格以 HTML 格式存入 `doc_blocks`
- [ ] 图片成功上传至 MinIO，且 `image_key` 正确回填
- [ ] 参考文献成功解析并写入 `citations`，保证引用图谱可用
- [ ] 确保 `page_num` 与 `bbox` 坐标数据完整不丢失
