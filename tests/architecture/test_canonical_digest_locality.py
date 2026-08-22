from __future__ import annotations

import ast
import importlib
import inspect
import math
from pathlib import Path

import pytest

from review_writer.delivery.figure_policy import FigurePolicyError
from review_writer.delivery.project_release import ProjectReleaseError
from review_writer.project.source_truth import canonical_digest


GOLDEN_VALUE = {
    "z": ["β", {"b": 2, "a": "化学"}],
    "a": {"emoji": "🧪", "newline": "alpha\nbeta"},
}
REORDERED_GOLDEN_VALUE = {
    "a": {"newline": "alpha\nbeta", "emoji": "🧪"},
    "z": ["β", {"a": "化学", "b": 2}],
}
GOLDEN_DIGEST = "fb56dce42e54a92240e4b6ef64b16d95eec2b86b2ad8be9065db1e953319ed01"

ADAPTERS = (
    ("review_writer.project.dual_parse_bootstrap", "_canonical_digest"),
    ("review_writer.delivery.figure_policy", "_canonical_sha256"),
    ("review_writer.delivery.project_release", "_canonical_sha256"),
)


def _adapter_module_and_function(module_name: str, function_name: str):
    module = importlib.import_module(module_name)
    return module, getattr(module, function_name)


def _adapter_ast(module_name: str, function_name: str) -> ast.FunctionDef:
    module = importlib.import_module(module_name)
    source_path = Path(inspect.getsourcefile(module) or module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    ]
    assert len(functions) == 1
    return functions[0]


@pytest.mark.parametrize("module_name,function_name", ADAPTERS)
def test_adapters_match_fixed_unicode_canonical_golden_vector(module_name, function_name):
    _, adapter = _adapter_module_and_function(module_name, function_name)

    assert canonical_digest(GOLDEN_VALUE) == GOLDEN_DIGEST
    assert canonical_digest(REORDERED_GOLDEN_VALUE) == GOLDEN_DIGEST
    assert adapter(GOLDEN_VALUE) == GOLDEN_DIGEST
    assert adapter(REORDERED_GOLDEN_VALUE) == GOLDEN_DIGEST


@pytest.mark.parametrize("module_name,function_name", ADAPTERS)
def test_adapters_delegate_to_shared_digest(monkeypatch, module_name, function_name):
    module, adapter = _adapter_module_and_function(module_name, function_name)
    calls = []

    def fake_canonical_digest(value):
        calls.append(value)
        return "shared-digest-sentinel"

    monkeypatch.setattr(module, "canonical_digest", fake_canonical_digest, raising=False)

    assert adapter(GOLDEN_VALUE) == "shared-digest-sentinel"
    assert calls == [GOLDEN_VALUE]


@pytest.mark.parametrize("module_name,function_name", ADAPTERS)
def test_adapter_bodies_do_not_rebuild_canonical_json(module_name, function_name):
    function = _adapter_ast(module_name, function_name)
    dumps_calls = [
        node
        for node in ast.walk(function)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dumps"
        )
    ]

    assert dumps_calls == []


def test_invalid_canonical_values_keep_domain_error_mapping():
    invalid_value = {"not_finite": math.nan}

    with pytest.raises(ValueError):
        importlib.import_module("review_writer.project.dual_parse_bootstrap")._canonical_digest(
            invalid_value
        )

    with pytest.raises(FigurePolicyError) as figure_error:
        importlib.import_module("review_writer.delivery.figure_policy")._canonical_sha256(
            invalid_value
        )
    assert figure_error.value.code == "FIGURE_POLICY_INVALID"

    with pytest.raises(ProjectReleaseError) as release_error:
        importlib.import_module("review_writer.delivery.project_release")._canonical_sha256(
            invalid_value
        )
    assert release_error.value.code == "RELEASE_STATE_INVALID"
