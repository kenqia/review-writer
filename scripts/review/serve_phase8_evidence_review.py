#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.phase8.schemas import REVIEW_ACTIONS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the local Phase 8A evidence review UI.")
    parser.add_argument("--root", type=Path, default=Path("local/phase8_evidence"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Refusing non-localhost bind")
    root = args.root.resolve()
    if "phase8_evidence" not in root.parts:
        raise SystemExit("Root must be the Phase 8 evidence workspace")
    handler = make_handler(root)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"phase8-review-ui: http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


def make_handler(root: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Phase8EvidenceReview/0.1"

        def log_message(self, format: str, *args):  # noqa: A003
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                return self._html(render_index(root))
            if parsed.path == "/api/queue":
                return self._json(load_queue(root))
            if parsed.path == "/api/file":
                query = parse_qs(parsed.query)
                rel = query.get("path", [""])[0]
                safe = safe_path(root, rel)
                if not safe or not is_allowed_read(root, safe):
                    return self._error(403, "forbidden")
                return self._json(json.loads(safe.read_text(encoding="utf-8")))
            return self._error(404, "not found")

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/api/decision":
                return self._error(404, "not found")
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            action = payload.get("decision")
            if action not in REVIEW_ACTIONS:
                return self._error(400, "invalid decision")
            record = {
                "review_item_id": payload.get("review_item_id"),
                "original_ai_record_hash": payload.get("original_ai_record_hash"),
                "decision": action,
                "edited_value": payload.get("edited_value"),
                "note": payload.get("note"),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "previous_decision_id": payload.get("previous_decision_id"),
            }
            out = root / "review_decisions" / "reviewer_1.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
            fd = os.open(out, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
            return self._json({"status": "appended"})

        def do_PUT(self) -> None:
            return self._error(405, "append-only decisions; AI records are immutable")

        def _json(self, data, status: int = 200) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _html(self, text: str, status: int = 200) -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str) -> None:
            self._json({"error": message}, status=status)

    return Handler


def safe_path(root: Path, rel: str) -> Path | None:
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return None
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def is_allowed_read(root: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    if rel.parts[0] not in {"review_queue", "inventories", "reports"}:
        return False
    if path.suffix not in {".json", ".jsonl", ".md", ".csv"}:
        return False
    return path.exists() and path.is_file()


def load_queue(root: Path) -> dict:
    path = root / "review_queue" / "core_review_queue.json"
    if not path.exists():
        return {"items": []}
    return json.loads(path.read_text(encoding="utf-8"))


def render_index(root: Path) -> str:
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Phase 8A Evidence Review</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;color:#202124;background:#f7f7f4}
main{max-width:1120px;margin:0 auto;padding:24px}
table{width:100%;border-collapse:collapse;background:white}
th,td{border-bottom:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}
button{margin:2px;padding:6px 8px}
.muted{color:#666}
</style>
</head>
<body>
<main>
<h1>Phase 8A Evidence Review</h1>
<p class="muted">Blinded-first queue. AI confidence and rationale are hidden until after a decision.</p>
<table id="queue"><thead><tr><th>Item</th><th>Candidate</th><th>Locator</th><th>Evidence</th><th>Decision</th></tr></thead><tbody></tbody></table>
</main>
<script>
async function load(){
  const data=await fetch('/api/queue').then(r=>r.json());
  const body=document.querySelector('tbody');
  for(const item of data.items){
    const tr=document.createElement('tr');
    const locator=item.source_locator||{};
    tr.innerHTML=`<td>${item.review_item_id}</td><td>${item.candidate_value}</td><td>${locator.source_document_id||''} p.${locator.printed_page_label||''}</td><td>${item.short_evidence||''}</td><td></td>`;
    const td=tr.lastChild;
    for(const d of ['accept','reject','edit','cannot_verify','defer','add_note']){
      const b=document.createElement('button'); b.textContent=d;
      b.onclick=()=>fetch('/api/decision',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({review_item_id:item.review_item_id,original_ai_record_hash:item.ai_record_hash,decision:d,note:''})});
      td.appendChild(b);
    }
    body.appendChild(tr);
  }
}
load();
</script>
</body>
</html>"""


if __name__ == "__main__":
    raise SystemExit(main())
