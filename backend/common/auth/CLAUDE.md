# auth — 安全红线区（高风险，改动需谨慎）

## 安全红线
- 🚫 **绝不修改 JWT 校验/签发逻辑**，除非明确要求并跑通全部 auth 测试。
- 🚫 **绝不引入新认证方式**而不更新测试与文档。
- 🚫 **user_id 隔离中间件不可绕过**：所有受保护路由必须经过它；任何直接查库不带 user_id 的代码视为安全 bug。
- 🚫 密码只存 bcrypt 哈希，绝不明文/可逆加密；SECRET_KEY 只从 .env 读，不硬编码。

## 已知约定
- JWT 载荷含 `user_id`、`role`、`exp`；过期时间由 `ACCESS_TOKEN_EXPIRE_MINUTES` 控制。
- 隔离中间件从 JWT 解出 `user_id`，注入 request.state，供各服务强制过滤（DB + Milvus）。
- 多租户：Milvus 过滤 `user_id`；多人共享文档场景叠加 `acl` 字段过滤。
- 限流在中间件层用 Redis 滑动窗口（`ratelimit:{user_id}:{minute}`）。

## 变更要求
- 任何认证/权限改动，必须：① 更新本文件红线；② 跑 `pytest backend/tests/auth`；③ 说明影响面。
