# Controlled Hello Qwen Runbook

## Conclusion

Phase 4b allows only one minimal hello Qwen request through the Alibaba OpenAI-compatible endpoint. It is not a RAG test, not a paper upload test, not a Bailian knowledge base test, and not an image generation test.

## Offline First

Always run the dry-run check first:

```bash
make qwen-hello-dry-run
python tests/test_hello_qwen_safety.py
```

Dry-run does not require keys, does not call network, and does not print secrets.

## Temporary Environment

Set variables only in the current terminal. Do not send the key to AI chat and do not write it to `~/.zshrc`, `~/.bashrc`, PowerShell profile, `.env`, or repo config files.

```bash
export DASHSCOPE_API_KEY='paste your key locally, not into chat'
export BAILIAN_WORKSPACE_ID='your WorkspaceId'
export BAILIAN_REGION='cn-beijing'
export BAILIAN_MODEL='qwen-plus'
```

Supported regions:

```text
cn-beijing
ap-northeast-1
ap-southeast-1
```

## Real Call Command

Only after the user explicitly replies:

```text
allow hello qwen
```

Run exactly one request:

```bash
python scripts/hello_qwen_openai_compatible.py \
  --allow-network \
  --output-json /tmp/qwen_hello_real.json \
  --output-md /tmp/qwen_hello_real.md
```

The prompt is fixed:

```text
Reply with exactly: QWEN_HELLO_OK
```

The script uses a small `max_tokens` value and does not read repo file contents, upload files, create knowledge bases, or call image APIs.

## Error Classification

- `missing_dependency`
- `missing_env`
- `auth_error_401`
- `rate_limit_or_quota_429`
- `timeout`
- `server_error_5xx`
- `network_error`
- `unexpected_error`

## Reporting Rules

Report only:

- status
- model
- region
- error classification
- whether the response exactly matched `QWEN_HELLO_OK`

Do not print the API key. Do not print a full non-matching model response.

## Later Phases

Future work can consider:

- connecting the provider adapter into the orchestrator
- moving Bailian placeholder toward real RAG
- moving image placeholder toward a controlled image call

Each requires separate explicit approval.
