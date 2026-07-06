# Phase 4a Alibaba Adapter Skeleton PR

## PR Title

`feat: add alibaba adapter skeleton`

## Summary

This PR adds offline-first adapter skeletons for LLM, retrieval, and image providers. It prepares Alibaba/Qwen/Bailian/Wan integration without making real API calls, reading real paper bodies, uploading files, or requiring keys.

## Changed Files

- `review_writer/providers/*`: text provider base classes plus offline, OpenAI-compatible, and DashScope placeholders.
- `review_writer/retrieval/*`: retrieval base classes plus local registry and Bailian placeholders.
- `review_writer/image/*`: image base classes plus source-figure and Alibaba image placeholders.
- `review_writer/config/load_providers.py`: standard-library parser for the example config subset.
- `scripts/check_providers.py`: offline provider safety checker.
- `tests/test_provider_adapters.py`: direct Python tests for disabled/no-network behavior.
- `config/providers.example.yaml`: offline-default provider example.
- `.env.example`: documented variable names only.
- `Makefile`: adds `provider-check`.
- `docs/providers/alibaba_adapter_design.md`: adapter boundary and Phase 4b prerequisites.

## Implemented Gates

- Offline provider returns deterministic content.
- Alibaba OpenAI-compatible provider is disabled by default.
- DashScope provider is disabled by default.
- Bailian retrieval is disabled by default and does not create knowledge bases.
- Alibaba image provider is disabled by default and does not upload or generate images.
- Provider checker verifies no secret-like values in provider config.
- Provider checker verifies `.env` is not tracked by Git.

## Placeholder Scope

- No real DashScope request.
- No real compatible-mode request.
- No Bailian knowledge base creation.
- No paper upload.
- No Wan/Qwen-Image generation.

## Validation Commands

```bash
make smoke
make quality-check
make qoderwork-check
make provider-check
python tests/test_provider_adapters.py
python scripts/check_providers.py \
  --config config/providers.example.yaml \
  --output-json /tmp/provider_check.json \
  --output-md /tmp/provider_check.md \
  --strict
```

## Risks

- The config parser intentionally supports only the small YAML subset used by the example file.
- Local registry retrieval is metadata-only and not a semantic RAG implementation yet.
- Provider result schemas may need extension once real API responses are connected.

## Not Included

- No real API calls.
- No global QoderWork install.
- No Alibaba adapter live authentication.
- No PDF or markdown upload.

## Recommended Next Stage

Phase 4b should perform a single controlled hello-Qwen call only after explicit approval. It should use a temporary environment variable, avoid printing keys, and keep the offline provider gate as the default fallback.
