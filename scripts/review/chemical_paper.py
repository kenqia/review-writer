#!/usr/bin/env python3
"""Deterministic CLI for the MinerU Chemical Paper ZIP-only route."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.project.chemical_paper import (  # noqa: E402
    ChemicalPaperError,
    chemical_paper_projection,
    correct_chemical_paper_field,
    import_chemical_paper,
    review_chemical_paper_elements,
)
from review_writer.project.chemical_completion import (  # noqa: E402
    ChemicalCompletionError,
    apply_chemical_completion_batch,
    chemical_completion_state,
    project_chemical_completion_state,
)


COMMANDS = (
    "import-chemical-paper",
    "chemical-paper-state",
    "correct-chemical-paper-field",
    "review-chemical-paper-elements",
    "chemical-completion-state",
    "complete-chemical-fields",
)


def _actor(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--actor-type",
        required=True,
        choices=("human_researcher", "simulated_researcher_agent"),
    )
    parser.add_argument("--actor-label", required=True)


def add_subcommands(commands: argparse._SubParsersAction) -> None:
    importer = commands.add_parser("import-chemical-paper")
    importer.add_argument("--project", type=Path, required=True)
    importer.add_argument("--study-id", required=True)
    importer.add_argument("--source-pdf-sha256", required=True)
    importer.add_argument("--zip", dest="zip_path", type=Path, required=True)
    _actor(importer)

    state = commands.add_parser("chemical-paper-state")
    state.add_argument("--project", type=Path, required=True)

    completion_state = commands.add_parser("chemical-completion-state")
    completion_state.add_argument("--project", type=Path, required=True)
    completion_state.add_argument("--study-id")

    complete = commands.add_parser("complete-chemical-fields")
    complete.add_argument("--project", type=Path, required=True)
    complete.add_argument("--study-id", required=True)
    complete.add_argument("--input", type=Path, required=True)

    correct = commands.add_parser("correct-chemical-paper-field")
    correct.add_argument("--project", type=Path, required=True)
    correct.add_argument("--study-id", required=True)
    correct.add_argument("--molecule-index", type=int, required=True)
    correct.add_argument("--field", required=True, choices=("mol_idt", "smiles_expanded", "smiles_unexpanded"))
    correct.add_argument("--value", required=True)
    correct.add_argument("--reason", required=True)
    correct.add_argument("--version-token", required=True)
    _actor(correct)

    review = commands.add_parser("review-chemical-paper-elements")
    review.add_argument("--project", type=Path, required=True)
    review.add_argument("--study-id", required=True)
    review.add_argument("--molecule-index", type=int, required=True)
    review.add_argument("--state", required=True, choices=("confirmed", "corrected", "not_applicable"))
    review.add_argument("--reason", required=True)
    review.add_argument("--version-token", required=True)
    review.add_argument(
        "--element",
        action="append",
        default=[],
        metavar="SYMBOL=COUNT",
        help="Corrected element count; repeat for corrected state only.",
    )
    _actor(review)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import and review bound MinerU Chemical Paper manual exports."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    add_subcommands(commands)
    return parser


def _elements(values: Sequence[str]) -> dict[str, int] | None:
    if not values:
        return None
    result: dict[str, int] = {}
    for value in values:
        if value.count("=") != 1:
            raise ChemicalPaperError("ELEMENT_COUNTS_INVALID")
        symbol, raw_count = value.split("=", 1)
        if symbol in result:
            raise ChemicalPaperError("ELEMENT_COUNTS_INVALID")
        try:
            result[symbol] = int(raw_count)
        except ValueError as exc:
            raise ChemicalPaperError("ELEMENT_COUNTS_INVALID") from exc
    return result


def run(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "import-chemical-paper":
        return import_chemical_paper(
            args.project,
            args.study_id,
            args.source_pdf_sha256,
            args.zip_path,
            {"actor_type": args.actor_type, "actor_label": args.actor_label},
        )
    if args.command == "chemical-paper-state":
        return chemical_paper_projection(args.project)
    if args.command == "chemical-completion-state":
        return (
            chemical_completion_state(args.project, args.study_id)
            if args.study_id
            else project_chemical_completion_state(args.project)
        )
    if args.command == "complete-chemical-fields":
        try:
            payload = json.loads(args.input.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ChemicalCompletionError("CHEMICAL_COMPLETION_BATCH_INVALID") from exc
        return apply_chemical_completion_batch(args.project, args.study_id, payload)
    actor = {"actor_type": args.actor_type, "actor_label": args.actor_label}
    if args.command == "correct-chemical-paper-field":
        return correct_chemical_paper_field(
            args.project,
            study_id=args.study_id,
            molecule_index=args.molecule_index,
            field=args.field,
            value=args.value,
            actor=actor,
            reason=args.reason,
            version_token=args.version_token,
        )
    return review_chemical_paper_elements(
        args.project,
        study_id=args.study_id,
        molecule_index=args.molecule_index,
        review_state=args.state,
        actor=actor,
        reason=args.reason,
        version_token=args.version_token,
        corrected_elements=_elements(args.element),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except (ChemicalPaperError, ChemicalCompletionError) as exc:
        print(json.dumps({"ok": False, "error_code": exc.code}), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
