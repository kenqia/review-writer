# review-writer 项目执行规则

本项目继承 `/home/kenqia/my_folder/AGENTS.md`。以下内容仅作 review-writer 的项目化落地，不能削弱父规则或任何安全边界；发生冲突时以父规则和更严格的安全约束为准。

## 组织模型

- **产品经理 / 根聊天**不做执行工程，只负责目标、范围、优先级和业务确认。
- **Leader**使用 `gpt-5.6-sol / xhigh`，只负责架构设计、任务拆分、依赖排序、风险与保护边界、验收标准、派工、接收执行小弟汇报和管理层汇总；Leader 不替小弟补执行。
- **执行小弟**使用 `gpt-5.6-luna / max`，负责改文件、检索、扫描、实验、验证和执行报告。所有 review-writer 开发执行必须先由 Leader 开小弟会话。
- **Canonical 产品管理面**：产品经理直接维护 canonical Backlog/index 与 PM task specs；Leader 只读消费，发现冲突或变更需求时提交 change request，不直接修改。
- **Leader 有界审查**：Leader 可做有界只读的 code/diff/architecture/evidence review；不得以审查名义实施、全量扫描、查资料、跑实验、改文件或生成执行交付。
- 若 `gpt-5.6-luna / max` 或所需权限实际不可用，必须立即报告，不得静默切换 `Terra` 或其他模型。
- 开发执行开始前，执行小弟必须核验并报告 `permission observation`；首个工具动作完成后必须再次报告实际 observation，至少等效于 `sandbox_mode=danger-full-access`、`approval_policy=never`、文件系统 `unrestricted`。
- 上述权限 observation 不授权秘密泄露、远端写、生产写或破坏操作；这些行为仍须遵守父规则中的确认与保护边界。
