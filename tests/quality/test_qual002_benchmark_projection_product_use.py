from __future__ import annotations

import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


REPO_ROOT = Path(__file__).resolve().parents[2]
UI_PATH = REPO_ROOT / "view/assets/dashboard/review-audit.js"

NODE_PROBE = r"""
const fs = require("node:fs");
const [uiPath, currentPath, stalePath] = process.argv.slice(1);
const ui = require(uiPath);

class FakeNode {
  constructor(tag) {
    this.tag = tag;
    this.className = "";
    this.textContent = "";
    this.children = [];
  }

  append(...nodes) {
    this.children.push(...nodes);
  }

  replaceChildren(...nodes) {
    this.children = [...nodes];
  }
}

global.document = {
  createElement(tag) {
    return new FakeNode(tag);
  },
};

function treeText(node) {
  return [node.textContent, ...node.children.map(treeText)].filter(Boolean).join("\n");
}

function load(path) {
  return JSON.parse(fs.readFileSync(path, "utf8"));
}

function renderText(payload) {
  const root = new FakeNode("div");
  ui.renderAudit(root, payload);
  return treeText(root);
}

const current = load(currentPath);
const stale = load(stalePath);
const currentRoot = new FakeNode("div");
ui.renderAudit(currentRoot, current);
const staleRoot = new FakeNode("div");
ui.renderAudit(staleRoot, stale);

process.stdout.write(JSON.stringify({
  current: ui.buildAuditModel(current),
  stale: ui.buildAuditModel(stale),
  currentText: treeText(currentRoot),
  staleText: treeText(staleRoot),
  currentInput: current,
  staleInput: stale,
}));
"""


def _rubric() -> list[dict[str, object]]:
    return [
        {
            "dimension_id": dimension_id,
            "max_score": max_score,
            "score": score,
            "rationale": f"synthetic rationale {index}",
        }
        for index, (dimension_id, max_score, score) in enumerate(
            (
                ("scope_and_question_value", 10, 9),
                ("source_set_coverage", 15, 13),
                ("evidence_fidelity", 20, 18),
                ("synthesis_and_critique", 20, 18),
                ("structure_and_narrative", 15, 14),
                ("figure_information_value", 10, 9),
                ("citation_and_traceability", 10, 10),
            ),
            start=1,
        )
    ]


def _payload(benchmark: dict[str, object]) -> dict[str, object]:
    return {
        "parseQuality": {
            "status": "approved",
            "summary": {"studies": 1, "objects": 2, "needs_review": 1},
        },
        "synthesis": {
            "coverage": {
                "known_omissions": ["GAP: synthetic evidence boundary"],
                "axes": [],
            }
        },
        "final": {
            "evaluation": {
                "schema_version": "release-evaluation.v1",
                "project_id": "qual002-synthetic",
                "benchmark": benchmark,
            }
        },
    }


def test_qual002_projected_benchmark_renders_and_stale_binding_is_zero_write() -> None:
    binding = {
        "manuscript_sha256": "a" * 64,
        "release_sha256": "b" * 64,
        "chemical_paper_binding_digest": "synthetic-chemical-digest",
    }
    rubric = _rubric()
    current_benchmark = {
        "status": "available",
        "benchmark_status": "fail",
        "score": 91,
        "tier": "benchmark_internal",
        "rubric": rubric,
        "hard_fails": ["WRONG_SOURCE_BINDING"],
        "issues": ["SYNTHESIS_FIGURE_PENDING"],
        "expert_release_ready": False,
        "human_review_required": True,
        "disclaimer": "Regression score only; not scientific correctness or publication approval.",
        "release_binding": binding,
    }
    stale_benchmark = {
        "status": "stale",
        "reason_code": "BENCHMARK_RELEASE_STALE",
        "score": 100,
        "tier": "benchmark_internal",
        "rubric": rubric,
        "hard_fails": [],
        "issues": [],
        "expert_release_ready": True,
        "human_review_required": True,
        "disclaimer": current_benchmark["disclaimer"],
        "release_binding": {**binding, "release_sha256": "c" * 64},
    }

    with TemporaryDirectory(prefix="qual002-benchmark-projection-") as temporary_root:
        temporary_path = Path(temporary_root)
        current_path = temporary_path / "current_projection.json"
        stale_path = temporary_path / "changed_snapshot_projection.json"
        current_path.write_text(
            json.dumps(_payload(current_benchmark), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        stale_path.write_text(
            json.dumps(_payload(stale_benchmark), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        current_before = current_path.read_bytes()
        stale_before = stale_path.read_bytes()

        completed = subprocess.run(
            [
                "node",
                "-e",
                NODE_PROBE,
                str(UI_PATH),
                str(current_path),
                str(stale_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        current = result["current"]["evaluation"]
        assert result["current"]["parseQuality"]["status"] == "已闭合"
        assert len(current["dimensions"]) == 7
        assert [row["score"] for row in current["dimensions"]] == [
            "9",
            "13",
            "18",
            "18",
            "14",
            "9",
            "10",
        ]
        assert [row["rationale"] for row in current["dimensions"]] == [
            f"synthetic rationale {index}" for index in range(1, 8)
        ]
        assert current["score"] == "91"
        assert current["tier"] == "benchmark_internal"
        assert current["benchmarkStatus"] == "fail"
        assert current["hardFails"] == ["来源绑定与当前发布不一致"]
        assert current["issues"] == ["综合图仍待研究者完成"]
        assert current["expertReleaseReady"] is False
        assert current["humanReviewRequired"] is True
        assert current["disclaimer"] == current_benchmark["disclaimer"]
        assert current["releaseBindingDigest"] == binding["release_sha256"]
        assert current["releaseBinding"] == binding
        assert current["stale"] is False
        assert "总分：91" in result["currentText"]
        assert "benchmark_internal" in result["currentText"]
        assert "不构成发布批准或 B2 通过" in result["currentText"]
        assert current_benchmark["disclaimer"] in result["currentText"]

        stale = result["stale"]["evaluation"]
        assert stale["available"] is False
        assert stale["stale"] is True
        assert stale["reasonCode"] == "BENCHMARK_RELEASE_STALE"
        assert stale["score"] == "未提供"
        assert stale["tier"] == "未提供"
        assert stale["dimensions"] == []
        assert "总分：100" not in result["staleText"]
        assert "BENCHMARK_RELEASE_STALE" in result["staleText"]
        assert "评估绑定已过期" in result["staleText"]
        assert current_path.read_bytes() == current_before
        assert stale_path.read_bytes() == stale_before
        assert result["currentInput"] == _payload(current_benchmark)
        assert result["staleInput"] == _payload(stale_benchmark)
