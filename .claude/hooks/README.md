# Hooks — 质量门（强制执行层）

CLAUDE.md 里的规则是"请记住"，Hook 是"你必须"。配置在 `.claude/settings.json`。

## 已配置
- **PostToolUse (Edit|Write)**：Python 文件保存后自动 `ruff format` + `ruff check --fix`，保证风格统一。

## 建议补充（开发人员按需开启）
- 改 `backend/common/auth/` 后自动跑 `pytest backend/tests/auth`（安全红线模块）。
- 改 `docs/data-contracts.md` 后提醒同步 `common/db/*.sql` 与 Milvus 建表代码。
- 提交前跑 `ruff check` + `pytest`，不过不允许提交。

> 注意：hook 命令在本机执行，路径/工具需本机可用（ruff、pytest）。
