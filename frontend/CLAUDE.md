# frontend — Vue 3 门户（本地 npm run dev）

基本骨架（包含鉴权、布局、路由、API 客户端）已就绪，接下来需要实现核心业务功能逻辑。

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

## 开发任务列表 (TODO)
- 对话流式渲染 + 溯源交互；上传进度轮询/SSE；引用图谱可视化；可观测图表。
