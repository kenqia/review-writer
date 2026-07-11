# Bailian RAG Data Policy

Phase 6a is a no-upload preflight only.

Allowed inputs:

- clean draft paper identifiers
- title, year, journal, DOI draft
- short claim drafts
- short figure-note drafts
- warning strings that preserve uncertainty

Blocked inputs:

- PDFs
- raw images
- raw MinerU markdown
- full PDF text
- local absolute paths
- API keys, tokens, cookies, auth files, or session material

Trust boundary:

- The clean 3-paper pack is acceptable for engineering preflight.
- It is not trusted for final scientific review quality.
- Every item must remain `needs_human_review: true`.
- Every item must remain `trusted_for_scientific_quality: false`.

Real Bailian knowledge-base creation is out of scope until the user explicitly authorizes a later pilot.

