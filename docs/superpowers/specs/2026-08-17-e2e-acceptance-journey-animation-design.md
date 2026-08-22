# E2E 验收旅程 HTML 动画设计

- 日期：2026-08-17
- 状态：已按用户指令采用推荐方向，直接实现
- 视觉方向：证据驾驶舱 × 谱系河流

## 目标

把用户给出的最终 E2E 验收标准，转换成一个无需后端、打开即能体验的单文件 HTML 动画。它不是产品能力证明，而是把“同一 authority 上的阶段推进、人工决策、版本谱系、故障闸门和 HUMAN_ACCEPTANCE 边界”演示成一条可暂停/继续/回退/故意触发故障的产品旅程。

## 体验结构

1. 顶部状态栏显示当前项目、current、revision、release 状态和整体进度。
2. 左侧阶段轨道分成七个叙事段：初始化、来源绑定、证据审核、Draft v1、用户回合、v2 与发布、恢复与验收。
3. 中央“谱系河流”持续绘制 `v1 → USER_EDITED → v2 → RELEASE → STALE → REGENERATE`，点击节点可展开证据摘要。
4. 右侧事件面板显示 Agent 动作、Dashboard 人工动作、写入目标和 fail-closed 结果。
5. 底部控制台提供 Play/Pause、上一步、下一步、重置和“触发 stale 409”演示按钮。
6. 末段只有完成用户回合、冷重启恢复和明确的人类确认后才点亮 `HUMAN_ACCEPTANCE`。

## 状态与数据

前端维护一个纯内存 `state`：`stepIndex`、`currentVersion`、`revision`、`releaseStatus`、`humanAccepted`、`events`。每个 step 是确定性对象，包含标题、actor、阶段、动作、证据写入、保护规则和可选错误结果。状态变化只更新展示，不伪造真实后端写入。

## 故障与安全表达

- stale revision 通过一次明确的 `409 / zero-write` 事件演示；current 和 revision 保持不变。
- wrong-source、wrong-role、digest mismatch、corrupt 都进入统一的红色 `FAIL-CLOSED` 通道，并显示“旧 current 未损坏”。
- v1 卡片永远标注 `IMMUTABLE / READ-ONLY`；用户编辑卡片标注 `CANONICAL INPUT`。
- release 状态由 `fresh → stale → regenerated` 转换，旧 release 保留 lineage 但下载被拒绝。
- 最终 CTA 只显示“达到 HUMAN_ACCEPTANCE 条件”，不显示 PROMOTE/B2。

## 动效与可用性

- 深色控制台底 + 米白信息卡，薄荷绿表示通过，酸橙表示人工确认，珊瑚红表示拒绝写入。
- 页面载入时阶段轨道、版本节点、事件卡片分层进入；切换 step 使用横向谱系推进和轻微数字滚动。
- 所有控制器都有可见文字状态，动画尊重 `prefers-reduced-motion`。
- 单文件、无外部依赖、桌面优先但在 900px 以下折叠为单列。

## 验证

- 用浏览器直接打开 HTML，点击 Play 走完全链；逐步检查 v1 immutable、用户编辑、v2 current、stale 409 zero-write、冷启动恢复和 HUMAN_ACCEPTANCE。
- 使用 `node --check`（若存在内联脚本则提取后检查）或浏览器控制台无错误作为基础 smoke。
- 不把动画 PASS 当作真实 PUBLIC_E2E、科学有效性或产品发布结论。
