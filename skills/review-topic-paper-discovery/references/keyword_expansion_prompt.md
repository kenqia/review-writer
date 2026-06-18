# Keyword Expansion Prompt

Given a review topic and user-provided keywords, generate a concise keyword set for literature discovery.

Rules:

- Keep the user's original keywords unless clearly irrelevant.
- Add synonyms, substrate classes, catalyst classes, reaction types, and product classes.
- Do not create too many broad generic keywords.
- Prefer search-useful terms over prose phrases.
- Classify each keyword as one of:
  - `core_topic`
  - `substrate`
  - `product`
  - `reaction_type`
  - `catalyst_or_method`
  - `mechanism`
  - `application`
  - `background`
- Mark source as `user`, `agent`, or both.

Expected output shape:

```json
{
  "user_topic": "...",
  "user_keywords": ["..."],
  "agent_keywords": [
    {"keyword": "...", "category": "...", "reason": "..."}
  ],
  "merged_keywords": [
    {"keyword": "...", "category": "...", "source": ["user", "agent"], "keep": true}
  ]
}
```
