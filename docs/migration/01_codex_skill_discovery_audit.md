# Codex Skill Discovery Audit

## 结论

当前仓库原本是“项目内 workflow 文档结构”，不是完整 Codex 原生 repo-scoped skill 结构。已按确认方案增加 `.agents/skills -> ../skills` symlink，作为最小 repo-scoped discovery 修复。

## 证据

- 审计时 repo 内不存在 `.agents/skills/<skill>/SKILL.md`。
- repo 内 `skills/<skill>/SKILL.md` 齐全。
- 全局 `~/.codex/skills` 存在同名 skills。
- 除 `review-draft-merge-polish` 外，repo/global 同名 `SKILL.md` hash 均不同，属于漂移。

## 风险

- 全局 skill 与 repo skill 同名时，调用来源可能不透明。
- 如果继续复制到全局，repo 迭代后容易再次漂移。
- symlink 对部分非 POSIX 工具可能需要兼容性检查。

## 推荐修改

1. repo source of truth 保持在 `skills/`。
2. `.agents/skills` 使用 symlink 指向 `../skills`。
3. 全局 `~/.codex/skills` 不再作为 review-writer 的唯一来源。
4. 后续如需全局安装，使用显式 dry-run installer，并要求人工确认。

## 验收标准

- `test -L .agents/skills` 为真。
- `readlink .agents/skills` 指向 `../skills`。
- repo 内每个 `skills/*/SKILL.md` 都能通过 `.agents/skills/*/SKILL.md` 访问。
- 不修改 `~/.codex/skills`。
