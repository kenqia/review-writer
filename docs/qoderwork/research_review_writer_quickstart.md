# 科研综述专家：QoderWork CN 首次运行

这是 QoderWork CN 内置“写作工作台”的原生 v0 流程。它使用一个通用专家插件和本地动态仪表盘；没有自定义 Workbench SDK，也没有直接 Provider/API 回退。

## 1. 维护者：打包并上传专家套件

在仓库根目录执行：

```bash
make qoderwork-plugin-package
```

该命令生成仓库内已忽略的 `build/research-review-writer.qoder-plugin.zip`。也可用相对路径覆盖：`make qoderwork-plugin-package OUTPUT_ZIP=build/<文件名>.zip`。打包前会校验 manifest、根目录库存、符号链接、凭据式文件名和本地绝对路径；若目标是无关的既有文件会拒绝覆盖。将此 ZIP 在 QoderWork CN 的 **Extensions -> Expert Kits** 上传；插件内部名为 `research-review-writer`，显示名称为“科研综述专家”。

官方上传与市场规范：

- https://help.aliyun.com/zh/lingma/qoderwork-cn/user-guide/expert-kit
- https://docs.qoder.com/zh/qoderwork/skill-marketplace-guidelines

## 2. 科研用户：在 QoderWork CN 创建一次写作任务

1. 在 QoderWork CN 中打开维护者准备好的 review-writer 仓库工作区；工作区已包含专家套件需要的受维护命令。
2. 模型选择 **Qwen3.7-Max**。
3. 选择专家套件“科研综述专家”。
4. 用普通科研语言说明主题即可。专家套件会默认核对尚缺、且会改变结果的关键范围，最多询问 12 项，然后在工作台中等待你确认 Review Brief；不上传密钥或私人历史。

Brief 确认后，专家套件会在付费处理前一次性检查工作目录、MinerU 配置与网络、PDF/DOCX/图片依赖、可用 Agent 和 Credits 余量；缺失时会在花费 Credits 前停止，不会中途静默降级。界面等待最长 12 小时，来源与风险决策最长 24 小时；超时后项目仍会保存，在 QoderWork 发送“继续当前综述项目”即可恢复。

专家套件在同一个任务中运行本地仪表盘、来源获取与导入、MinerU 解析、逐研究证据提取、对抗审查、综合写作和质量/发布判断。科研用户不运行这些命令。模型只能基于提供的来源写作；候选来源、冲突和高风险解释会保留为待核验项。

若部分全文无法自动合法获取，系统会一次性展示缺失来源及下载链接。请按页面给出的文件名保存这些来源，全部下载后上传一个 ZIP；无需逐篇回复，也无需填写映射表。系统会自动导入、复核并继续处理，只有仍缺失或文件身份不唯一的来源会保留在同一页面中。

## 3. 科研用户：审阅并完成交付

来源和证据处理完成后，科研用户集中审阅 Scientific Risk Packet。系统随后生成原创的证据比较图和带 claim lineage 的正文工作台；点击科学表述可查看原文摘录、页码和审查结论，修改科学内容会进入待复核状态。科研用户可继续编辑并下载最终 DOCX。正常流程中的人工动作只有确认 Review Brief、必要时在工作台上传一个 ZIP、审阅 Scientific Risk Packet、编辑并下载最终 DOCX。

仪表盘由专家套件在同一个任务内启动和维护；科研用户无需打开终端、查看 manifest，或理解 JSON、Prompt、Agent 与 Git。

## 维护者：验收边界

唯一仍需人工完成的运行时验收是：在真实 QoderWork CN UI 中上传 Expert Kit ZIP、选择上述工作台/模型/专家并说明一次综述需求，确认插件可加载并产生项目状态。此仓库的确定性检查不调用 Qoder、Qwen 或其他付费 Provider，也不能替代该 UI 验收。

当前限制：公开/本地均未发现可用的 QoderWork Workbench SDK 包，因此本版本没有创建或声称支持自定义 Workbench；未来若官方 SDK 可用，可包装现有插件、项目状态与仪表盘契约，无需重设计数据边界。

## 维护者专用诊断/恢复：来源路线的三个本地命令

以下命令仅供维护者在诊断或恢复时使用，不是正常产品操作。正常运行时由专家套件在同一个任务内调用，科研用户不需要查看内部 manifest 或命令行。

1. `scripts/acquisition/acquire_public_corpus.py`：对冻结的来源清单运行一次确定性 public-direct 获取；ZIP 导入后对同一清单加 `--verify-only` 复核，不发起网络请求。
2. `scripts/acquisition/import_manual_archive.py`：将研究者上传的一个 ZIP 按 `download_id`、目标文件名和安全显式别名确定性导入；不覆盖既有文件。
3. `skills/mineru-precise-parse-review-writer/scripts/parse_review_writer_pdfs.py`：在已确认 full-PDF egress 授权后，以项目 source/output 目录运行，默认增量处理，不使用 `--force`。
