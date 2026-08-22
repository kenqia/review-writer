from __future__ import annotations

from pathlib import Path

import pytest

from review_writer.product_foundation import InvalidContextError
from review_writer.product_foundation.project_root import (
    resolve_project_root,
    version_context_root,
)


def test_resolve_project_root_accepts_explicit_absolute_directory(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    child = project_root / "child"
    child.mkdir()

    assert resolve_project_root(child / "..") == project_root.resolve()


@pytest.mark.parametrize("invalid_root", [None, "", "   ", Path("relative/project")])
def test_resolve_project_root_rejects_missing_or_relative_authority(
    invalid_root: object,
) -> None:
    with pytest.raises(InvalidContextError):
        resolve_project_root(invalid_root)  # type: ignore[arg-type]


def test_resolve_project_root_rejects_file_path(tmp_path: Path) -> None:
    file_path = tmp_path / "project-file"
    file_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(InvalidContextError):
        resolve_project_root(file_path)


def test_explicit_root_is_authoritative_over_cwd_and_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit_root = tmp_path / "explicit"
    fallback_root = tmp_path / "fallback"
    explicit_root.mkdir()
    fallback_root.mkdir()
    monkeypatch.chdir(fallback_root)
    monkeypatch.setenv("REVIEW_WRITER_PROJECT_ROOT", str(fallback_root))

    assert resolve_project_root(explicit_root / ".") == explicit_root.resolve()


def test_version_context_root_is_deterministic_and_does_not_write(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    before = tuple(sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")))

    expected = project_root.resolve() / ".review-writer" / "version_context"
    assert version_context_root(project_root / ".") == expected
    assert version_context_root(project_root) == expected

    after = tuple(sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")))
    assert after == before
    assert not expected.exists()
