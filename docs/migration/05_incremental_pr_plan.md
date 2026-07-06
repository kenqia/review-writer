# Incremental PR Plan

## 结论

迁移应拆成三阶段：安全瘦身与文档、质量 validators、QoderWork/阿里云 adapter。不要一次性把所有技能、UI、云 API、生成逻辑混成大改。

## PR 1: Safety And Migration Baseline

目标：

- repo clean-room 化
- 数据外置
- token 示例化
- Codex discovery symlink
- QoderWork skill source skeleton
- migration docs

验收：

```bash
make smoke
make quality-check
python3 scripts/install_qoderwork_skills.py
```

## PR 2: Chemistry Validators

目标：

- 新增 static validators
- 扩展 final audit
- 输出 `quality_scan.json/md`
- dashboard final 页面显示质量报告

验收：

- 引用乱序失败。
- 重复图注报告。
- broken/missing source image 报告。
- prompt leakage 示例被捕获。

## PR 3: Adapter And Export Expansion

目标：

- LLM/retrieval/image adapter
- DashScope/Qwen/Bailian/Wan no-op stubs
- PDF/LaTeX skeleton
- QoderWork installer apply path

验收：

- 无 key offline smoke 通过。
- 有 key 时只通过 adapter 调用。
- 不配置图像 provider 时终稿不能假装图文并茂。

## 风险

- PR 过大导致 review 困难。
- 全局 skill 安装造成漂移。
- LLM judge 无 deterministic fallback。
- 图像生成改变化学含义。

## 推荐修改

保持每个 PR 可独立验证；远端 push、全局安装、真实 API smoke 都必须人工确认。

## 验收标准

- 每个 PR 都有命令级验证。
- 每个 PR 都能在无真实 API key 环境下给出明确结果。
- 每个 PR 都不触碰 Codex/QoderWork 全局配置。
