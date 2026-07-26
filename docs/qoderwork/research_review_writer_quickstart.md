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

1. 打开内置“写作工作台”。
2. 模型选择 **Qwen3.7-Max**。
3. 选择专家套件“科研综述专家”。
4. 选择一个 Windows 原生工作文件夹；将待用本地来源放入该项目边界内，不上传密钥或私人历史。
5. 用普通科研语言说明主题、目标读者、年份/对象范围、排除条件和已有本地来源；确认系统展示的 Review Brief。

专家会在同一个任务中依次完成简报、获取计划、逐研究证据提取、对抗审查、综合写作和质量/发布判断。模型只能基于提供的来源写作；候选来源、冲突和高风险解释会保留为待核验项。

若部分全文无法自动合法获取，系统会一次性展示缺失来源及下载链接。请按页面给出的文件名保存这些来源，全部下载后上传一个 ZIP；无需逐篇回复，也无需填写映射表。系统会自动导入、复核并继续处理，只有仍缺失或文件身份不唯一的来源会保留在同一页面中。

## 3. 维护者：打开动态仪表盘、编辑并导出

在工作文件夹对应的 review 根目录运行：

```bash
python view/serve_review_dashboard.py --review-root <REVIEW_ROOT>
```

打开浏览器中的 `/review`。首页显示简报、当前阶段/状态、来源/证据/主张计数、草稿和 DOCX 可用性、以及 blockers。需要修改正文时进入 `/draft`；确认终稿后在 `/review` 点击“导出 DOCX”，复用现有导出器写入 `05_final_audit/final_draft.docx`。

## 维护者：验收边界

唯一仍需人工完成的运行时验收是：在真实 QoderWork CN UI 中上传 Expert Kit ZIP、选择上述工作台/模型/专家并说明一次综述需求，确认插件可加载并产生项目状态。此仓库的确定性检查不调用 Qoder、Qwen 或其他付费 Provider，也不能替代该 UI 验收。

当前限制：公开/本地均未发现可用的 QoderWork Workbench SDK 包，因此本版本没有创建或声称支持自定义 Workbench；未来若官方 SDK 可用，可包装现有插件、项目状态与仪表盘契约，无需重设计数据边界。

## 维护者说明：来源路线的三个本地命令

这些命令由专家工作流维护者运行，科研用户不需要查看内部 manifest 或命令行。

1. `scripts/acquisition/acquire_public_corpus.py`：对冻结的来源清单运行一次确定性 public-direct 获取；ZIP 导入后对同一清单加 `--verify-only` 复核，不发起网络请求。
2. `scripts/acquisition/import_manual_archive.py`：将研究者上传的一个 ZIP 按 `download_id`、目标文件名和安全显式别名确定性导入；不覆盖既有文件。
3. `skills/mineru-precise-parse-review-writer/scripts/parse_review_writer_pdfs.py`：在已确认 full-PDF egress 授权后，以项目 source/output 目录运行，默认增量处理，不使用 `--force`。
