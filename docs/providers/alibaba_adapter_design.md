# Alibaba Adapter Skeleton Design

## Conclusion

Phase 4a adds adapter skeletons and offline gates only. It does not call DashScope, Alibaba Model Studio, Bailian, Wan/Qwen-Image, or any real network API.

## Why Skeleton First

- Review writing must keep deterministic offline smoke tests even when no key is configured.
- Provider failures should be reported as structured status, not leak into review正文.
- Real paper PDFs and extracted markdown must not be uploaded until a later, explicit approval step.
- QoderWork skills should call repo scripts/adapters, not embed cloud-specific behavior in prompts.

## Adapter Boundaries

| adapter | file | Phase 4a behavior |
| --- | --- | --- |
| offline LLM | `review_writer/providers/offline_provider.py` | Returns deterministic mock responses with `network=not_used`. |
| OpenAI-compatible | `review_writer/providers/openai_compatible_provider.py` | Defaults disabled; refuses network unless a later phase explicitly enables it. |
| DashScope/Qwen | `review_writer/providers/dashscope_provider.py` | Defaults disabled; no SDK or HTTP call in Phase 4a. |
| local retrieval | `review_writer/retrieval/local_library.py` | Reads local registry metadata only; does not read PDF body. |
| Bailian retrieval | `review_writer/retrieval/bailian_retrieval.py` | Placeholder only; does not create knowledge bases or upload files. |
| source figure | `review_writer/image/source_figure.py` | Resolves local source figure paths only. |
| Alibaba image | `review_writer/image/alibaba_image.py` | Placeholder only; does not generate or upload images. |

## Config Contract

- `.env.example` documents variable names only.
- `config/providers.example.yaml` defaults to `default_provider: offline`.
- Alibaba OpenAI-compatible, Bailian retrieval, and Alibaba image providers are disabled by default.
- Real keys must not be committed, printed, or written to shell rc files.
- Smoke checks must pass without keys.

## Provider Check

Run:

```bash
make provider-check
```

This runs:

```bash
python tests/test_provider_adapters.py
python scripts/check_providers.py \
  --config config/providers.example.yaml \
  --output-json /tmp/provider_check.json \
  --output-md /tmp/provider_check.md \
  --strict
```

The report records:

- `network: not_used`
- `real_api: not_called`
- `keys_read: not_read`
- `paper_body_read: not_read`

## Real Call Prerequisites

Phase 4b must ask for explicit approval and collect:

- `workspace_id`
- `region`
- `model`
- temporary `DASHSCOPE_API_KEY`
- whether temporary environment variables are allowed
- whether one controlled network call is allowed

## Not Allowed

- Do not put keys in repo files.
- Do not write keys to `.zshrc`, `.bashrc`, or profile files.
- Do not upload papers, images, markdown, or metadata to Alibaba services.
- Do not create Bailian knowledge bases.
- Do not silently generate a final "illustrated" review when figures are missing.

## Acceptance

- `make provider-check` passes with no key and no network.
- Disabled providers return structured `status=disabled`.
- Offline provider returns deterministic mock content.
- Config examples contain no secret-like values.
