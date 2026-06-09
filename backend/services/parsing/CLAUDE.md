# parsing — 解析服务

把 PDF 变成结构化内容：正文/公式/表/图 + 论文元数据 + 引用边。

## 职责与产物
| 步骤 | 工具 | 产物 |
|---|---|---|
| 版面解析 | Docling（默认，本地开源）/ MinerU（显式兼容回退） | 双栏正文、公式、表格、图片块，尽量保留页码与 bbox |
| 文献结构化 | GROBID（默认）/ LLM（失败降级） | 标题、作者、摘要、年份、DOI、参考文献列表 → MySQL `papers` / `citations` 表 |
| 图片描述 | VLM (clients/llm) | 图的中文描述（配合 figure_caption 提示词） |

写入：`papers`（元数据）、`citations`（引用边）、`doc_blocks`（表/图/公式父块）、MinIO `figures`（图片）。

## 关键约定（踩坑预防）
- **绝不丢页码/图**：每个 block 记录 `page_num/bbox`，图存 MinIO 并回填 `image_key`。
- **双栏**：信任 Docling/MinerU 的阅读序，不要自己按坐标硬拼。
- **大表**：整表 HTML 存 `doc_blocks`，不在这里切碎（切分在 indexing）。
- **幂等**：按 `file_hash` 去重，重复文件不重复解析。
- 解析是 CPU/GPU 重活，**只在 worker 里跑**，不在请求线程。

## 接口（被 worker 调用）
- `parse_paper(user_id, paper_id, pdf_key) -> ParseResult`：解析一篇，落库落 MinIO，返回 block 列表给 indexing。

## 当前状态与后续优化
- Docling 为默认版面解析 Provider；GROBID 为默认元数据/参考文献解析 Provider；MinerU 仅作为显式配置的兼容回退。后续重点是按真实 PDF 样本优化公式识别、图片裁剪与 bbox 质量。
