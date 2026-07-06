# review-writer




必读：
你让 Codex 每个阶段结束后，都必须逐项打勾：

[ ] 没有修改 ~/.codex、~/.qoderwork、auth.json、config.toml、真实 API key
[ ] 没有打印 token、cookie、secret
[ ] 没有 hard-coded legacy absolute review-writer path
[ ] clean-room clone 能找到入口说明
[ ] repo 内有项目级 AGENTS.md
[ ] Codex repo-scoped skill discovery 有解释或 mirror
[ ] QoderWork skill pack 有独立 SKILL.md
[ ] QoderWork 安装脚本默认 dry-run，不覆盖
[ ] 主入口 skill 明确为 chem-review-scientist 或 review-writing-orchestrator
[ ] 人审 checkpoint 没被删
[ ] 无图时不会静默生成“图文并茂”终稿
[ ] figure manifest 记录源图、重绘图、生成图来源
[ ] 引用编号升序 validator 可运行
[ ] 图注重复 validator 可运行
[ ] 化学式上下标检查有 static/LLM/human 分层
[ ] prompt/workflow 思路泄漏检查可运行
[ ] Markdown 导出可用
[ ] DOCX 导出可用或有明确失败报告
[ ] PDF/LaTeX 导出有 skeleton 和失败回退
[ ] make smoke 通过
[ ] make quality-check 通过或报告明确
[ ] 本地 commit 完成
[ ] push 前暂停询问
