from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / ".agents" / "skills" / "review-orchestrator"


def test_project_review_orchestrator_skill_is_discoverable_and_agent_owned() -> None:
    skill = SKILL_ROOT / "SKILL.md"
    metadata = SKILL_ROOT / "agents" / "openai.yaml"

    assert skill.is_file()
    assert metadata.is_file()

    skill_text = skill.read_text(encoding="utf-8")
    metadata_text = metadata.read_text(encoding="utf-8")

    assert skill_text.startswith(
        "---\nname: review-orchestrator\ndescription: "
    )
    assert "topic" in skill_text.lower()
    assert "project root" in skill_text.lower()
    assert "authorized local PDF folder" in skill_text
    assert "GeneratorSession" in skill_text
    assert "HUMAN_ACTION_REQUIRED" in skill_text
    assert "Do not ask the user to run generator-start" in skill_text
    assert "allow_implicit_invocation: true" in metadata_text
    assert "default_prompt: \"Use $review-orchestrator" in metadata_text
    assert "用户通过 `$review-orchestrator`" in (
        REPO_ROOT / "README.md"
    ).read_text(encoding="utf-8")
