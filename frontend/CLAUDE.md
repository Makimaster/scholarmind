# frontend — Vue 3 门户（本地 npm run dev）

真实 API 联调已接入；后续优化重点是提升溯源预览、入库进度可视化和图谱交互体验。

## 技术栈
Vue 3 + Vite + TypeScript + Pinia + Vue Router + axios。基础设施在 Docker，前端本地跑打 `VITE_API_BASE`。

## 页面（src/views）
| 页面 | 内容 |
|---|---|
| 登录/注册 | JWT，登录后存 token，路由守卫 |
| 论文库 | 列表/文件夹/批量上传（拖拽，秒级返回，可关页面） |
| 对话 | SSE 流式答案 + 角标溯源（点击跳页码/看原图）+ 多轮 |
| 可观测 | 入库进度（实时）+ 查询历史 + 概览指标 |
| 设置 | 切换模型/参数 |

## 约定
- API 统一走 `src/api/`（axios 实例 + 拦截器：自动带 token、401 跳登录）。
- 状态用 Pinia（`src/stores/`）。
- SSE 用 EventSource/fetch 流式，按 api.md 的 event 渲染 token/cite。
- 溯源角标 `[n]` 可点击，弹出对应论文页码 + 原图（MinIO）。
- 审美：保持简洁专业，交互流畅；上传/解析有进度反馈。

## 后续优化方向
- 溯源角标与引用卡片的交互细节、上传进度实时性、引用图谱可视化、可观测图表可继续增强。
