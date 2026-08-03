#!/usr/bin/env python3
"""Build and validate a deterministic QoderWork Plugin ZIP using only stdlib."""

from __future__ import annotations

import argparse
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath


NORMALIZED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
REQUIRED_PATHS = (Path(".qoder-plugin/plugin.json"), Path("skills"))
MANIFEST_KEYS = {"name", "displayName", "version", "description", "descriptionZh", "author", "keywords", "skills"}
FORBIDDEN_PARTS = {".git", ".env", "__pycache__"}
FORBIDDEN_SUFFIXES = {".pdf", ".zip", ".pyc", ".key", ".pem"}
ABSOLUTE_PATH_RE = re.compile(r"(?:^|[\s`'\"])(?:/[A-Za-z0-9_.-]+){2,}")
SECRET_RE = re.compile(r"(?:api[_-]?key|access[_-]?token|secret)[\s:=]", re.I)


def plugin_files(plugin_dir: Path) -> list[Path]:
    if plugin_dir.is_symlink() or not plugin_dir.is_dir():
        raise ValueError(f"plugin directory must be a real directory: {plugin_dir}")
    for required in REQUIRED_PATHS:
        if not (plugin_dir / required).exists():
            raise ValueError(f"plugin layout is missing: {required.as_posix()}")
    files: list[Path] = []
    for candidate in plugin_dir.rglob("*"):
        relative = candidate.relative_to(plugin_dir)
        if candidate.is_symlink():
            raise ValueError(f"plugin packaging forbids symlinks: {relative.as_posix()}")
        if any(part in FORBIDDEN_PARTS for part in relative.parts) or candidate.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise ValueError(f"plugin inventory contains forbidden file: {relative.as_posix()}")
        if candidate.is_file():
            files.append(candidate)
    if not files:
        raise ValueError("plugin package has no files")
    return sorted(files, key=lambda path: path.relative_to(plugin_dir).as_posix())


def validate_plugin(plugin_dir: Path) -> list[Path]:
    files = plugin_files(plugin_dir)
    manifest_path = plugin_dir / ".qoder-plugin/plugin.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"plugin manifest is invalid JSON: {exc}") from exc
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
        raise ValueError("plugin manifest must contain the supported name, displayName, version, description, descriptionZh, author, keywords, and skills fields")
    text_keys = ("name", "displayName", "version", "description", "descriptionZh")
    if manifest.get("name") != plugin_dir.name or not all(isinstance(manifest.get(key), str) and manifest[key].strip() for key in text_keys):
        raise ValueError("plugin manifest name must match directory and text fields must be nonempty strings")
    if not manifest["description"].isascii():
        raise ValueError("plugin manifest description must be English ASCII text; put Chinese copy in descriptionZh")
    author = manifest.get("author")
    if not isinstance(author, dict) or set(author) - {"name", "url"} or not isinstance(author.get("name"), str) or not author["name"].strip():
        raise ValueError("plugin manifest author must be an object with nonempty name and optional public url")
    if "url" in author and (not isinstance(author["url"], str) or not author["url"].startswith(("https://", "http://"))):
        raise ValueError("plugin manifest author url must be an http(s) public URL when present")
    if not isinstance(manifest.get("keywords"), list) or not manifest["keywords"] or not all(isinstance(value, str) and value.strip() for value in manifest["keywords"]):
        raise ValueError("plugin manifest keywords must be a nonempty string array")
    skill_paths = {f"skills/{path.parent.name}" for path in (plugin_dir / "skills").glob("*/SKILL.md")}
    skills = manifest.get("skills")
    if not isinstance(skills, list) or set(skills) != skill_paths:
        raise ValueError("plugin manifest skills must exactly list relative skills/<name> paths")
    for raw_path in skills:
        if not isinstance(raw_path, str):
            raise ValueError("plugin manifest skills entries must be relative strings")
        relative = PurePosixPath(raw_path)
        if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 2 or relative.parts[0] != "skills" or not (plugin_dir / Path(*relative.parts) / "SKILL.md").is_file():
            raise ValueError("plugin manifest skills entries must be relative paths to packaged SKILL.md files")
    for path in files:
        if path.suffix.lower() not in {".json", ".md"}:
            raise ValueError(f"plugin inventory permits only manifest and Markdown: {path.relative_to(plugin_dir).as_posix()}")
        text = path.read_text(encoding="utf-8")
        if ABSOLUTE_PATH_RE.search(text) or SECRET_RE.search(text):
            raise ValueError(f"plugin text contains a local path or credential-like assignment: {path.relative_to(plugin_dir).as_posix()}")
    return files


def archive_belongs_to_plugin(output: Path, plugin_dir: Path) -> bool:
    try:
        with zipfile.ZipFile(output) as archive:
            manifest = json.loads(archive.read(".qoder-plugin/plugin.json").decode("utf-8"))
            return isinstance(manifest, dict) and manifest.get("name") == plugin_dir.name
    except (OSError, KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile):
        return False


def safe_output_path(output: Path, plugin_dir: Path, files: list[Path]) -> Path:
    if output.is_absolute() or ".." in output.parts or output.suffix.lower() != ".zip":
        raise ValueError("plugin output must be a relative .zip path inside the current working directory")
    cwd = Path.cwd().resolve()
    destination = (cwd / output).resolve()
    try:
        destination.relative_to(cwd)
    except ValueError as exc:
        raise ValueError("plugin output must stay inside the current working directory") from exc
    if destination.exists() and not archive_belongs_to_plugin(destination, plugin_dir):
        raise ValueError(f"refusing to overwrite unrelated output: {output}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def build_plugin_zip(plugin_dir: Path, output: Path) -> None:
    files = validate_plugin(plugin_dir)
    destination = safe_output_path(output, plugin_dir, files)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True) as archive:
        archive.comment = b""
        for source in files:
            entry = zipfile.ZipInfo(source.relative_to(plugin_dir).as_posix(), date_time=NORMALIZED_TIMESTAMP)
            entry.create_system, entry.create_version, entry.extract_version = 3, 30, 20
            entry.external_attr, entry.internal_attr, entry.extra, entry.comment = (stat.S_IFREG | 0o644) << 16, 0, b"", b""
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic, validated root-layout QoderWork Plugin ZIP.")
    parser.add_argument("--plugin-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        build_plugin_zip(args.plugin_dir, args.output)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
