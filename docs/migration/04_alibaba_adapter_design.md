# Alibaba Adapter Design

## 结论

阿里云能力应通过 adapter 接入，而不是把 DashScope、百炼、Wan/Qwen-Image 调用散落到 skills 和脚本里。默认必须支持 offline smoke，API 不通时也能给出明确 warning/fallback。

## 证据

- 当前已有 OpenAI-compatible LLM/image 调用和 SciAtlas/Crossref retrieval。
- 配置尚未统一。
- 用户要求不接真实 API，仅设计 adapter。

## LLM Provider Adapter

```text
openai/current      OpenAI-compatible endpoint
dashscope/qwen      DashScope compatible-mode or SDK wrapper
local/open-source   local OpenAI-compatible server
```

统一接口：

```text
generate_text(messages, model, temperature, response_format)
judge_quality(task, rubric, inputs)
```

## Retrieval Adapter

```text
local library only
Alibaba Model Studio / Bailian knowledge base
optional MCP paper search
```

统一接口：

```text
search(query, filters, top_k)
fetch_document(doc_id)
```

## Image Adapter

```text
source figure extraction
redraw existing source figure
Alibaba Wan/Qwen-Image generation
no-op fallback
```

统一接口：

```text
resolve_source_figure(candidate)
redraw(source_image, prompt, style)
generate(prompt, constraints)
```

## Config

- `.env.example`
- `config/providers.example.yaml`
- no real keys in repo

## Failure Fallback

- API 不通：offline smoke 仍可运行。
- 无图：必须 warning，并阻止默认 final release。
- provider 未配置：输出 `provider_unconfigured`，不要静默跳过。

## 验收标准

- 未配置 key 时不发网络请求。
- provider 错误进入报告，不进入正文。
- 所有真实调用集中在 adapter 层。
- no-op image fallback 不能制造“已有图片”的假象。

## Phase 4a Skeleton Status

已落地 offline-first adapter skeleton：

```text
review_writer/providers/offline_provider.py
review_writer/providers/openai_compatible_provider.py
review_writer/providers/dashscope_provider.py
review_writer/retrieval/local_library.py
review_writer/retrieval/bailian_retrieval.py
review_writer/image/source_figure.py
review_writer/image/alibaba_image.py
scripts/check_providers.py
tests/test_provider_adapters.py
```

当前边界：

- `offline` provider 默认启用，并返回 deterministic mock response。
- Alibaba OpenAI-compatible / DashScope / Bailian / Alibaba image 默认 disabled。
- `local_library` 只读取本地 registry/metadata，不读取 PDF 正文。
- Bailian placeholder 不创建知识库，不上传文件。
- Alibaba image placeholder 不生图，不上传图片。

新增验收：

```bash
make provider-check
```

真实调用前仍需用户显式确认 `workspace_id`、`region`、`model`、临时 `DASHSCOPE_API_KEY`、是否允许网络调用。不得把 key 写入 repo 或 shell rc。
