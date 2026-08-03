# review-writer

review-writer 是一个面向化学研究者的、离线优先的综述工作台。它的核心
目标不是“让模型自由写一篇文章”，而是让用户清楚知道：输入了哪些来源、
哪些证据可以使用、哪些结论仍然需要人工判断，以及配置变化会影响什么。

## 当前可用版本

当前主线交付的是 **M0/PR A：最小案例中立项目契约**。它已经提供一个可
实际运行的本地第一步：创建项目、绑定用户提供的 MAIN/SI 文件、校验路径和
文件哈希，并在后续检查时发现配置或来源发生变化。

用户现在可以得到：

- 一个不依赖网络、模型或数据库的项目骨架；
- 明确的项目目标、范围和封闭语料边界；
- 对来源文件的路径安全检查和 SHA-256 记录；
- 配置变更不会悄悄覆盖历史结果的基础约束；
- 可复制的验证命令和结构化错误信息。

当前版本**不宣称**已经完成自动检索、自动写作、Dashboard、DOCX/PDF 导出
或领域专家确认。这些历史实现仍保留为内部证据或后续候选，但不再是用户的
默认入口。

## 五分钟开始

以下命令在仓库根目录执行。真实论文、SI 和项目输出建议放在仓库之外。

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

准备一个项目目录，并把文件放到 inputs/papers 下。例如：

```text
my-review/
└── inputs/papers/paper-1/
    ├── main.pdf
    └── si.pdf
```

用唯一入口初始化项目。每个 --source 都使用：
SOURCE_ID:PAPER_ID:MAIN|SI:相对于 inputs/papers 的路径。

```bash
python3 scripts/project.py init \
  --project-root ./my-review \
  --project-id visible-light-review \
  --project-title "可见光驱动烯烃双官能化综述" \
  --goal "比较所提供论文中的反应模式、条件和机制证据" \
  --scope "只使用本地提供的 MAIN 与 SI 文件，不进行开放检索" \
  --source P1_MAIN:P1:MAIN:paper-1/main.pdf \
  --source P1_SI:P1:SI:paper-1/si.pdf
```

初始化会创建 project.manifest.json、outputs/project-state 和 exports，
同时立即检查每个来源是否存在、是否位于项目目录内、每篇论文是否恰好有一
份 MAIN。已有 manifest 时命令会拒绝覆盖。

随后可以重复执行验证：

```bash
python3 scripts/project.py validate --manifest ./my-review/project.manifest.json
```

返回 status=VALID 才表示项目输入满足当前 M0 契约。返回码为 0 表示这次
检查通过，返回码为 2 表示输入需要修复；错误输出包含稳定的 error_code，
便于用户定位问题。

## 文档入口

- [用户使用说明](docs/用户使用说明.md)：按用户任务解释初始化、验证、改动后的
  复核、错误处理和限制。
- [项目规格](docs/项目规格.md)：说明当前版本保护什么、明确不做什么，以及
  后续功能进入主线前需要满足的条件。
- [收敛说明](docs/CONVERGENCE_2026-08-03.md)：记录为什么只保留 M0 主线。
- [收敛清理清单](docs/CONVERGENCE_INVENTORY_2026-08-03.md)：记录可恢复性和
  停车区，不把历史分支误当作当前产品。
- [产品北极星](docs/product/PRODUCT_NORTH_STAR.md) 与 [产品路线图](docs/product/PRODUCT_ROADMAP.md)：
  保留的长期产品契约。

## 数据和科学边界

M0 把 PDF、文本或其他来源当作需要保护的字节，不在 project init 或
project validate 中解读其科学内容。CLOSED_CORPUS 和 OFFLINE_ONLY 是
能力边界：当前命令不会联网、上传文件、调用模型，也不会把候选内容变成
已确认科学事实。

最终化学综述的目标文稿仍遵循现有产品契约的学术英语和数字引用约束；本仓库
面向用户的新说明和项目报告默认使用中文。

## 本地验证

开发者或维护者可以运行：

```bash
make smoke
make quality-check
make project-check
```

这些命令只做本地确定性检查，不调用 provider，也不需要真实 API key。完整历史
Makefile 目标属于回归/审计工具，不是当前用户入口。
