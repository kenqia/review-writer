# QoderWork CN 适配记录

## 结论

Review Writer 现在提供一个 QoderWork CN 宿主适配层，不把 QoderWork 的会话、Skill 或模型
状态当成综述事实源。QoderWork 只负责自然语言任务、授权目录和调用本地 adapter；每篇综述的
唯一 durable authority 仍是显式 project root 及其 `.review-writer/version_context`。

## 官方依据（2026-08-22 检索）

- [什么是 QoderWork CN](https://docs.qoder.cn/qoderwork/product-overview/what-is-qoderwork-cn)：本地文件操作、显式目录授权、Skill/Plugin/MCP 扩展。
- [Qoder CN 插件规范](https://docs.qoder.cn/qoder-plugins)：`.qoder-plugin/plugin.json`、`skills/`、`agents/`、`qoderwork.md` 和 ZIP 分发结构。
- [QoderWork CN Skills](https://docs.qoder.cn/qoderwork/user-guide/skills)：Skill 位于 `~/.qoderwork/skills/`，可从 GitHub 或界面安装。
- [QoderWork CN 专家套件](https://docs.qoder.cn/qoderwork/user-guide/expert-kit)：可在 Extensions/Expert Kits 上传插件包。

官方文档说明 QoderWork 会在本地执行文件操作，但供模型理解的相关文本可能发送给模型服务
商；用户应在 QoderWork 中自行确认账号、Credits、网络和隐私设置。本适配层不读取或保存任何
凭据。

## 适配映射

| QoderWork CN 能力 | Review Writer 落点 | 结果 |
| --- | --- | --- |
| `qoderwork.md` / Expert Kit | `qoderwork/plugins/review-writer-cn/` | 已适配 |
| Skill discovery | `skills/review-writer/SKILL.md` | 已适配 |
| 新建 review | `review_writer.agent.qoderwork_adapter.start_review()` → `FreshAgentBootstrap` | 已适配 |
| 冷恢复 | `resume_review()` → 同一 root 的 `VersionContext` + owned Dashboard | 已适配 |
| 科学判断 | Dashboard 的既有 public producer | 不旁路 |
| current/history/release | 项目根目录的既有 authority | 不复制 |

## 使用

在 QoderWork CN 中打开本仓库，安装 `qoderwork/plugins/review-writer-cn` 的 Expert Kit，或
直接把 `qoderwork/plugins/review-writer-cn/skills/review-writer/SKILL.md` 安装为 Skill。然后只
提供 topic、explicit project root 和 authorized PDF folder。Skill 会在人工闸门停下，并返回
真实 Dashboard URL；用户在 Dashboard 完成决定后，再说“继续同一个项目”。

## 明确限制

QoderWork CN 的真实 UI 登录、Credits、目录授权、模型版本和最终 HUMAN_ACCEPTANCE 不能由本地
单元测试代替。当前 adapter 验证的是入口契约和 fail-closed 边界；真实 QoderWork CN UI smoke
仍需在用户已安装并登录的客户端中执行。
