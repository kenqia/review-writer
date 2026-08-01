# MVP 三论文综述 QA Contract

本协议只覆盖第一条可复用的三论文内部综述闭环，以及直接阻塞该闭环的
P0/P1 回归。它不是旧版 19 checkpoint / restart/history 协议的替代执行清单，
也不把旧协议的重启、浏览器历史或复杂恢复步骤设为 MVP 硬门。

## 硬门

一个 fresh、non-overwriting project 必须同时闭合：

| 输入合同 | 最小要求 |
| --- | --- |
| MAIN source | 3 个已验证、按 study/source identity 绑定的主文 PDF |
| SI | 3 个与对应 study 绑定的补充材料；缺失只能保持显式 `BLOCKED`/`PARTIAL` |
| Chemical Paper | 3 个正式 preflight → confirm → import 的 Chemical ZIP；不手工解压真实 ZIP |
| Generic Parse | 3 个 current、同一主文 PDF 绑定的 Generic Parse 结果 |

任何输入缺失、重复、stale、跨 study 或 hash 不匹配，都必须 fail closed，且
失败请求不得写入权威项目状态。

## 科学和下游边界

- 科学状态只有 `CONFIRMED`、`AI_PROVISIONAL`、`BLOCKED`。
- `CONFIRMED` 需要原始 PDF locator 和 researcher confirmation。
- `AI_PROVISIONAL` 必须保留 PDF locator、confidence、provenance，不能当作
  confirmed fact。
- `BLOCKED` 必须保持 `value=null` 和非空 `gap_reason`；未知不得压成零。
- 不猜 SMILES，不从 AI candidate 伪造 `CONFIRMED`，不输出伪 `READY`。
- Evidence 只能消费当前、同 study、已关闭或明确 PDF 仲裁的双层 binding；
  Synthesis 只能消费 approved Evidence，不能越过 Evidence 边界。

## 可见流程和导出

Dashboard 主流程必须能展示当前 source / Generic / Chemical / completion /
reconciliation / Evidence / Synthesis 边界、唯一 next action 和 blocker，并且
Researcher-safe projection 不泄露绝对路径、raw JSON、MolBlock、token、session
或内部 digest。

内部 DOCX/PDF 导出只能来自当前 authoritative manuscript；最终 artifact audit
必须验证内容与 release snapshot 一致、DOCX integrity 通过、PDF/页面产物存在且
不是旧稿重打包。科学 blocker 仍然优先于导出完成。

## 独立性和报告

每轮使用新的项目目录，不覆盖旧项目；测试只使用 synthetic `tmp_path` 数据，
不读取或解压真实论文/ZIP。合同测试应保留失败原因和 zero-write 证据；不得把
旧重启/history checkpoint 重新升级为 MVP 硬门。
