# QoderWork 入口说明（停车状态）

本文件保留历史 QoderWork 资产的定位，避免用户把它误认为当前默认入口。

## 当前结论

当前用户主流程是仓库内的确定性 CLI：

```text
bootstrap-corpus
-> bind-generic-parse
-> preflight-corpus-inputs
-> import-corpus-inputs
```

QoderWork 插件、旧 Dashboard、Provider 和 RAG 仍可能用于维护者回归或未来纵向
闭环，但本轮没有真实 UI 验收，因此不能宣称“用户打开插件即可得到已审阅综述”。

## 对用户意味着什么

- 现在不需要安装或上传 QoderWork Expert Kit 才能完成输入绑定；
- 不会因为插件可加载就把科学内容视为已确认；
- 如果未来启用 QoderWork，仍必须保留 MAIN/SI hash、Source Truth、Claim/Decision
  和 researcher checkpoint；
- 模型、Provider、插件加载状态都不能替代真实研究者决定。

## 维护者保留内容

插件源代码和打包脚本暂时保留，用于未来在明确批准模型、数据出境、预算、用户
checkpoint 和验收标准后恢复。恢复前不能：

- 默认调用外部 Provider；
- 上传真实 PDF 或敏感配置；
- 用 Dashboard/API/脚本代替用户的可见研究者决定；
- 把历史 QoderWork 运行报告搬到新的 20–40 篇项目上。

如果用户明确批准新的 QoderWork 运行，应先从当前项目的最新输入 provenance 和
hash-bound Core Contract 开始，而不是从旧插件报告恢复。
