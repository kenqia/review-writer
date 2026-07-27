# Review Writer 全流程动态工作台 E2E 设计

日期：2026-07-27  
状态：交互设计已批准，待用户审阅规格

## 1. 产品判断标准

任何新增文件或机制必须至少满足一项：

1. 直接提高综述质量；
2. 减少科研用户操作；
3. 支持真实规模。

目标用户是化学科研人员。用户无需理解 Agent、Prompt、JSON、Git、hash、schema、Provider receipt、运行日志或本地路径，只需用普通科研语言提出主题，并在少量必要科学检查点完成一份证据可追溯、可编辑、值得继续完善的综述。

本轮只修复完整新项目 E2E 暴露出的图形界面缺口。不重做 discovery、acquisition、MinerU、evidence extraction、Qoder runtime、项目状态或正文模型，不建设第二套平台。

## 2. 成功路径

唯一产品路径为：

```text
QoderWork 自然语言建项
→ localhost 自动发现项目
→ Review Brief 确认
→ 来源清单与一次 PDF ZIP 上传
→ 自动处理进度
→ Scientific Risk Packet
→ 自动写作
→ 正文工作室与 evidence locator
→ 科学修改待复核/恢复
→ DOCX 导出
```

最终验收必须由用户本人完成。自动化浏览器只能作为补充工程 smoke，不能替代人工体验，也不能把 `ENGINEERING_SMOKE=PASS` 表述为 `FULL_NEW_PROJECT_E2E=PASS`。

## 3. 项目入口

### 3.1 唯一建项入口

用户在 QoderWork 中：

1. 打开当前版本的干净 Windows-native `review-writer` 文件库；
2. 使用 `/research-review-writer` 专家套件；
3. 输入一条普通科研语言需求。

自然语言必须包含综述主题；年份、篇数、纳排边界、比较维度、语言和交付偏好均为可选信息。专家套件只追问缺失且会实质改变科学范围的信息。

localhost 不新增第二套“新建项目”表单。没有项目时，现有 `/review` 页面仍可正常启动，显示“等待 QoderWork 创建科研综述”，并轮询现有 `/api/projects`。QoderWork 创建项目与 Review Brief 后，页面自动进入该项目的 Brief 确认状态。

### 3.2 Review Brief

页面以科研语言显示主题、研究问题、年份、目标研究数、纳入/排除标准、比较维度、输出语言和交付物。用户可以：

- 确认 Brief；
- 返回 QoderWork 用自然语言修改范围。

浏览器确认继续调用既有 Review Brief 状态接口。确认动作本身不触发检索或 Provider；同一 QoderWork 任务观察到 `BRIEF_CONFIRMED` 后继续后台流程。

## 4. 单一自适应工作台

继续扩展现有：

- `view/serve_review_dashboard.py`；
- `view/assets/dashboard/review.html`；
- 既有 dashboard CSS/JavaScript；
- `00_brief/review_state.json` 及现有阶段产物。

不创建第二个 server、SPA framework、项目数据库、事件总线或通用作业平台。所有用户可见 payload 都从既有项目状态与权威产物派生，不复制内部状态。

页面保持一个 localhost URL 和统一布局：

- 顶部：项目名称、当前科学阶段和当前必要操作；
- 左侧：项目阶段、章节目录和证据健康度；
- 中央：当前阶段的主要科研工作；
- 右侧：当前 evidence、冲突或科学风险上下文；
- 显著位置：唯一推荐下一步。

视觉沿用已批准的深绿/纸白、科研出版风格，避免通用 SaaS 卡片堆砌。

## 5. 阶段界面

### 5.1 无项目

- server 在不存在 `review-projects/` 或项目列表为空时保持运行；
- 页面显示等待状态、QoderWork 建项的三步说明和自动发现提示；
- 每隔数秒刷新项目列表；发现项目后自动加载，不要求用户刷新或选择路径。

### 5.2 Brief 阶段

- 默认中央区显示 Review Brief；
- 只提供“确认研究范围”这一推荐动作；
- 确认后显示后台正在建立来源清单。

### 5.3 来源清单与 PDF ZIP

页面从现有 acquisition manifest/receipt 派生并显示：

- 已识别研究和 MAIN/SI 角色；
- 已获得、缺失、重复或无法匹配的来源；
- 合法下载链接或明确的人工获取说明；
- 一个 PDF ZIP 拖放区。

用户只准备并上传一个 ZIP，不填写路径、映射表或内部 ID。浏览器把 ZIP 以固定项目路由上传；server 在项目目录内原子保存为：

```text
00_sources/manual_upload/inbox/source_bundle.zip
```

该固定 inbox 是 QoderWork 专家套件与工作台之间的本地交接点，不是新的项目状态。QoderWork 的同一后台任务观察该文件并调用现有 `scripts/acquisition/import_manual_archive.py` 和 verify-only acquisition 流程。

上传接口不负责重新实现来源匹配或解压逻辑。它只负责有界接收、ZIP 基本有效性检查和原子发布；真正的路径、成员、格式、manifest alias、重复与容量校验继续由现有 `review_writer.acquisition.manual_archive` 完成。

ZIP 发布成功后立即显示“已接收，正在核验来源”并进入自动进度视图，不再要求用户点击“继续处理”。若确定性导入发现问题，页面回到同一来源视图，只显示一条具体纠正建议和相关论文，不泄露内部路径。用户明确选择重新上传时，才允许原子替换未通过的 inbox ZIP。

### 5.4 自动处理进度

进度视图从现有 `review_state`、acquisition receipt、parse 输出、evidence cards、exception queue、risk packet 和 manuscript 产物派生，按科研语言显示：

- 整理文献来源；
- 解析全文与补充信息；
- 提取逐研究证据；
- 核对原文与页码；
- 汇总科学风险；
- 撰写与最终检查。

显示纳入研究数、全文覆盖、已审查研究、activation mode 覆盖和逐研究完成状态。不得显示 Agent 名称、Prompt、JSON、hash、Git、Provider receipt 或底层日志。

页面自动刷新。单篇 exception 不阻塞其他研究；真正阻塞时停止在当前阶段，并显示唯一可执行下一步。

### 5.5 Scientific Risk Packet

Risk Packet 使用既有 `risk_packet.json` payload 和 `/risk-decisions` 接口，在中央区逐项展示：

- 拟使用的科学表述；
- 研究与原文摘录；
- 页码、图表或 source locator；
- 审查结论、冲突和建议动作。

每项只能选择：

- 批准；
- 改写；
- 排除；
- 暂缓。

“改写”在当前项内展开一个文本框。用户一次提交所有科学决定。尚有暂缓项、缺失决定或非法改写时，不进入 Writer，并在界面中标出未闭合项。内部 digest 由现有接口自动携带，用户不可见。

### 5.6 正文工作室

正文存在且项目进入 drafting/final review 时，默认进入已有 manuscript studio：

- 左侧显示章节目录和证据健康度；
- 中央编辑唯一 authoritative manuscript；
- 点击带 lineage 的主张，右侧显示“主张 → 研究 → 原文摘录 → 页码/图表 → 审查结论”；
- locator 可打开项目内真实 PDF 的对应来源；
- 普通文案修改可直接保存；
- 数字、化学结构、机制、结论、引用或 lineage-bound 主张的修改进入“需要证据复核”；
- 保留已验证文本，可恢复，不能静默覆盖；
- 待复核状态与原因对用户可见。

### 5.7 DOCX 导出

继续使用现有 authoritative manuscript、质量 gate 和 DOCX exporter。页面提供：

- 导出 DOCX；
- 导出完成后直接下载当前 DOCX；
- 失败时显示可执行原因。

存在未闭合科学决定或待复核科学修改时，不把导出物宣称为已验证终稿；允许的 preview 必须明确标注状态。

## 6. API 与数据流边界

现有项目/API 保持兼容。最小增量为：

1. 允许 dashboard 在零项目时启动；
2. 提供来源清单与处理进度的 researcher-safe payload，优先扩展现有 cockpit/review-state payload；
3. 增加一个项目级 ZIP 上传 route，将请求体有界、原子地写入固定 inbox；
4. 在主页面补齐 stage-aware 渲染、Risk Packet 表单与自动轮询；
5. 更新当前 Expert Kit 的既有自动阶段，使同一 QoderWork 任务等待并消费固定 inbox；
6. 复用已有 Brief、draft、source locator、risk decision 和 DOCX API。

上传请求使用单个 ZIP 二进制请求体即可，不引入 multipart 依赖。文件名不参与目标路径决策。server 只接受当前已知项目 ID，使用现有项目路径校验，限制 Content-Length 和实际读取字节，写入同目录临时文件并 `fsync` 后原子替换/发布。任何失败都清理临时文件，不留下半个可见 ZIP。

QoderWork 仍是后台智能引擎和流程编排者；localhost 是科研用户界面。浏览器不直接调用 Provider，不复制 Expert Kit 的科学状态机，也不启动第二套后台作业。

## 7. 安全与错误处理

### 7.1 ZIP 边界

- 不信任扩展名、Content-Type 或原始文件名；
- 拒绝超出既有 importer hard ceiling 的请求；
- 上传阶段确认 ZIP container 可读，导入阶段继续执行现有成员数、成员大小、总解压大小、路径穿越、绝对路径、盘符、链接/特殊文件、格式签名、重复目标和 manifest alias 校验；
- ZIP 内容只能发布到当前项目的固定 inbox；
- 不接受 URL 下载、浏览器登录、绕过访问控制或任意目标路径；
- 真实 PDF、ZIP 和项目产物继续位于 Git ignored 项目数据区。

### 7.2 用户可见错误

每次只显示一个具体、可执行的主要纠正动作，例如：

- “压缩包不是有效 ZIP，请重新导出后上传”；
- “还缺少研究 X 的补充信息”；
- “文件 Y 无法与来源清单匹配，请保留 DOI 或清单中的建议文件名”；
- “两项科学风险仍为暂缓，完成决定后才能写作”；
- “该科学修改需要证据复核，可恢复已验证文本”。

不向普通用户展示异常堆栈、绝对路径、内部文件名或命令。高级诊断视图不属于本轮。

### 7.3 Provider 与流程失败

- 不自动重试，不使用 fallback model；
- Provider 无输出、结构失败或证据失败时，项目停在相应科研阶段；
- 单篇失败进入现有 exception queue，其余研究继续；
- 只有范围变化、来源缺失、预算/授权、集中科学决定或最终质量错误等真实阻塞才要求用户介入。

## 8. 验收与测试

### 8.1 最小自动测试

只补直接覆盖本轮行为的测试：

- 零项目 server 启动与等待 payload；
- 项目出现后的自动选择与阶段路由；
- Brief 确认继续使用现有接口；
- 来源清单 payload 不泄露内部字段；
- ZIP 正常上传、大小限制、无效 ZIP、路径边界、原子发布和明确替换；
- 上传成功后 stage/progress payload 可观察；
- Risk Packet 四种决定、改写校验与 unresolved 阻塞；
- claim → evidence → locator 展开；
- 科学修改待复核、恢复已验证文本；
- DOCX 导出与下载。

优先扩展现有 `tests/test_qoderwork_native_review_writer.py`、dashboard tests 和 `tests/test_manual_archive_import.py`；不为本轮创建新的通用测试框架。

### 8.2 工程 smoke

启动真实 localhost，用合成或隔离测试数据完成浏览器 smoke：

```text
零项目等待
→ Brief
→ ZIP 拖放
→ 进度
→ Risk Packet
→ 正文
→ locator
→ 科学修改待复核/恢复
→ DOCX
```

同时检查窄屏与常见桌面尺寸，正文和右侧证据面板不得被裁切。工程 smoke 只标记：

```text
DEMO_V0_ENGINEERING_SMOKE=PASS|FAIL
```

### 8.3 用户 E2E

在代码、Expert Kit 和干净 Windows-native 测试环境准备完成后，由用户本人从新的 project ID 开始：

1. 在 QoderWork 发送普通科研需求；
2. 在 localhost 确认 Review Brief；
3. 上传一次真实三研究 PDF ZIP；
4. 查看处理进度；
5. 完成 Risk Packet；
6. 阅读正文并打开 evidence locator；
7. 修改科学内容并看到待复核，再恢复；
8. 导出并打开 DOCX。

任一阶段没有用户可见界面，立即记录：

```text
FULL_NEW_PROJECT_E2E=FAIL
FAILURE_CLASS=UX_GAP_<阶段>
```

只允许修复该真实阻塞，废弃失败测试项目并使用新 project ID 从头验收。只有用户完成界面审阅并确认 DOCX 可打开后，才允许记录：

```text
FULL_NEW_PROJECT_E2E=PASS
```

## 9. 明确不做

- 浏览器新建项目表单；
- 第二套项目状态、正文或 evidence 模型；
- QoderWork 运行日志、Prompt 或 Agent 控制台；
- 自动浏览器代替用户 E2E；
- 自动重试、模型 fallback 或 Provider framework；
- 账户、多用户协作、云端存储、部署、analytics、全局证据图或动画；
- 为潜在风险提前建设通用 infrastructure；
- 远程 push、PR、部署或发布。

## 10. 权威资料与采用理由

本设计在本地优先复用既有 `review_writer.acquisition.manual_archive`。其已具备容量上限、ZIP member 路径与类型校验、格式签名、manifest alias、staging、原子发布和回滚测试，因此不另写 ZIP 解压器。

限时核对资料：

- Python `zipfile` 文档：<https://docs.python.org/3/library/zipfile.html>。用于确认 ZIP container 读取与成员元数据边界；不把 `extractall()` 当作可信输入校验。
- OWASP File Upload Cheat Sheet：<https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html>。采用允许列表、大小限制、不信任文件名/Content-Type、独立存储和安全处理原则；拒绝为 localhost 产品新增云端扫描或账户体系。

两项资料均只影响上传边界，不扩大产品范围。
