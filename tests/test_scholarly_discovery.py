from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from review_writer.discovery.scholarly import build_candidate_pool, validate_search_plan


REPO_ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_SCRIPT = REPO_ROOT / "scripts" / "discovery" / "discover_scholarly_corpus.py"
QUERIES = ["Catalytic alpha coupling", "Catalytic beta coupling"]


def search_plan() -> dict:
    return {
        "schema_version": "scholarly-search-plan.v1",
        "from_year": 2017,
        "to_year": 2025,
        "queries": list(QUERIES),
        "seed_dois": ["10.1000/seed"],
    }


def write_plan(root: Path, plan: dict | None = None) -> Path:
    path = root / "search-plan.json"
    path.write_text(json.dumps(plan or search_plan()), encoding="utf-8")
    return path


def _openalex_work(
    openalex_id: str,
    title: str,
    year: int,
    *,
    doi: str = "",
    abstract_inverted_index: dict[str, list[int]] | None = None,
    references: list[str] | None = None,
) -> dict:
    return {
        "id": f"https://openalex.org/{openalex_id}" if openalex_id else "",
        "display_name": title,
        "publication_year": year,
        "doi": f"https://doi.org/{doi}" if doi else "",
        "authorships": [
            {"author": {"display_name": "Ada Example"}},
            {"author": {"display_name": "Bo Researcher"}},
        ],
        "primary_location": {
            "landing_page_url": f"https://example.org/{openalex_id or 'title-only'}",
            "source": {"display_name": "Journal of Synthetic Fixtures"},
        },
        "best_oa_location": {
            "is_oa": True,
            "landing_page_url": f"https://example.org/{openalex_id or 'title-only'}",
            "pdf_url": f"https://example.org/{openalex_id or 'title-only'}.pdf",
            "version": "publishedVersion",
            "license": "cc-by",
            "source": {"display_name": "Fixture Repository"},
        },
        "locations": [],
        "abstract_inverted_index": abstract_inverted_index,
        "referenced_works": references or [],
    }


def _crossref_work(
    title: str,
    year: int,
    *,
    doi: str = "",
    abstract: str = "",
) -> dict:
    return {
        "title": [title],
        "published": {"date-parts": [[year, 6, 1]]},
        "DOI": doi,
        "author": [
            {"given": "Ada", "family": "Example"},
            {"name": "Fixture Consortium"},
        ],
        "container-title": ["Crossref Fixture Journal"],
        "URL": f"https://doi.org/{doi}" if doi else "https://example.org/title-only",
        "abstract": abstract,
    }


class FakeTransport:
    """Complete fixed-host fixture transport for every bounded discovery route."""

    def __init__(self, *, fail_second_crossref_query: bool = True) -> None:
        self.fail_second_crossref_query = fail_second_crossref_query
        self.calls: list[tuple[str, float]] = []
        self.backward_ids: list[str] = []

    @classmethod
    def with_duplicate_doi(cls, doi: str) -> "FakeTransport":
        if doi != "10.1000/example":
            raise ValueError("fixture supports only its declared duplicate DOI")
        return cls()

    def get_json(self, url: str, timeout_seconds: float) -> dict:
        self.calls.append((url, timeout_seconds))
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        if parsed.scheme != "https":
            raise AssertionError("discovery must use HTTPS")

        if parsed.netloc == "api.openalex.org" and parsed.path == "/works" and "search" in params:
            return copy.deepcopy(self._openalex_search(params["search"][0]))
        if parsed.netloc == "api.crossref.org" and parsed.path == "/works":
            query = params.get("query.bibliographic", [""])[0]
            if query == QUERIES[1] and self.fail_second_crossref_query:
                raise TimeoutError("fixture detail must not leak into warnings")
            return copy.deepcopy(self._crossref_search(query))
        if parsed.netloc == "api.openalex.org" and parsed.path.startswith("/works/https://doi.org/"):
            encoded_doi = parsed.path.removeprefix("/works/https://doi.org/")
            if unquote(encoded_doi) != "10.1000/seed":
                raise AssertionError("unexpected seed DOI")
            return copy.deepcopy(self._seed_work())
        if parsed.netloc == "api.openalex.org" and parsed.path == "/works":
            filter_value = params.get("filter", [""])[0]
            if filter_value.startswith("openalex:"):
                self.backward_ids = filter_value.removeprefix("openalex:").split("|")
                return {"results": [copy.deepcopy(self._backward_work())]}
            if filter_value == "cites:W900":
                return {"results": [copy.deepcopy(self._forward_work())]}
        raise AssertionError(f"unexpected fixture route: {parsed.scheme}://{parsed.netloc}{parsed.path}")

    def _openalex_search(self, query: str) -> dict:
        if query == QUERIES[0]:
            return {
                "results": [
                    _openalex_work(
                        "W100",
                        "Example Discovery",
                        2021,
                        doi="10.1000/EXAMPLE",
                        abstract_inverted_index={
                            "abstract": [3],
                            "Indexed": [0],
                            "OpenAlex": [1],
                            "fixture": [2],
                        },
                    ),
                    _openalex_work("W200", "OpenAlex Identity Fallback", 2019),
                    _openalex_work("", "Normalized   Title Fallback", 2020),
                    _openalex_work("WOLD", "Outside Lower Year Bound", 2016, doi="10.1000/old"),
                ]
            }
        if query == QUERIES[1]:
            return {
                "results": [
                    _openalex_work("W100", "Example Discovery", 2021, doi="10.1000/example"),
                    _openalex_work("W200", "OpenAlex Identity Fallback", 2019),
                    _openalex_work("", " normalized title fallback ", 2020),
                    _openalex_work("W250", "Upper Year Boundary", 2025, doi="10.1000/upper"),
                ]
            }
        raise AssertionError("unexpected OpenAlex fixture query")

    def _crossref_search(self, query: str) -> dict:
        if query == QUERIES[0]:
            return {
                "message": {
                    "items": [
                        _crossref_work(
                            "Example Discovery",
                            2021,
                            doi="10.1000/example",
                            abstract="<jats:p>Duplicate <jats:i>Crossref</jats:i> abstract.</jats:p>",
                        ),
                        _crossref_work(
                            "Crossref Abstract Normalization",
                            2022,
                            doi="10.1000/crossref",
                            abstract=(
                                '<jats:p xmlns:jats="http://www.ncbi.nlm.nih.gov/JATS1">'
                                "Tagged <jats:italic>abstract</jats:italic> &amp; entities."
                                "</jats:p>"
                            ),
                        ),
                        _crossref_work("NORMALIZED TITLE FALLBACK", 2020),
                        _crossref_work("Outside Upper Year Bound", 2026, doi="10.1000/future"),
                    ]
                }
            }
        if query == QUERIES[1]:
            return {"message": {"items": []}}
        raise AssertionError("unexpected Crossref fixture query")

    @staticmethod
    def _seed_work() -> dict:
        references = ["https://openalex.org/W300"] + [
            f"https://openalex.org/W{number}" for number in range(400, 500)
        ]
        return _openalex_work(
            "W900",
            "Resolved Seed Work",
            2020,
            doi="10.1000/seed",
            references=references,
        )

    @staticmethod
    def _backward_work() -> dict:
        return _openalex_work("W300", "Bounded Backward Reference", 2018, doi="10.1000/backward")

    @staticmethod
    def _forward_work() -> dict:
        return _openalex_work("W301", "Bounded Forward Citation", 2024, doi="10.1000/forward")


def _query_calls(transport: FakeTransport, host: str) -> list[str]:
    return [
        url
        for url, _timeout in transport.calls
        if urlsplit(url).netloc == host and "search" in parse_qs(urlsplit(url).query)
        or urlsplit(url).netloc == host and "query.bibliographic" in parse_qs(urlsplit(url).query)
    ]


def test_doi_dedup_retains_all_query_provenance() -> None:
    transport = FakeTransport.with_duplicate_doi("10.1000/example")

    pool = build_candidate_pool(search_plan(), transport=transport)

    rows = [row for row in pool["candidates"] if row["doi"] == "10.1000/example"]
    assert len(rows) == 1
    assert {item["query"] for item in rows[0]["provenance"]} == set(QUERIES)
    assert pool["counts"]["unique_candidates"] == len(pool["candidates"])


@pytest.mark.parametrize(
    "bad_plan",
    [
        {
            "schema_version": "scholarly-search-plan.v1",
            "from_year": 2025,
            "to_year": 2017,
            "queries": ["bounded query"],
            "seed_dois": [],
        },
        {
            "schema_version": "scholarly-search-plan.v1",
            "from_year": 2017,
            "to_year": 2025,
            "queries": [],
            "seed_dois": [],
        },
    ],
)
def test_invalid_plan_reports_search_plan(bad_plan: dict) -> None:
    with pytest.raises(ValueError, match="search plan"):
        build_candidate_pool(bad_plan, transport=FakeTransport())


def test_validation_normalizes_seed_dois_and_rejects_bool_years() -> None:
    plan = search_plan()
    plan["queries"] = ["  Catalytic alpha coupling  ", "Catalytic alpha coupling"]
    plan["seed_dois"] = [" DOI:10.1000/SEED ", "https://doi.org/10.1000/seed"]

    validated = validate_search_plan(plan)

    assert validated["queries"] == ["Catalytic alpha coupling"]
    assert validated["seed_dois"] == ["10.1000/seed"]
    for field in ("from_year", "to_year"):
        bool_year = search_plan()
        bool_year[field] = True
        with pytest.raises(ValueError, match="search plan"):
            validate_search_plan(bool_year)
    invalid_doi = search_plan()
    invalid_doi["seed_dois"] = ["not-a-doi"]
    with pytest.raises(ValueError, match="search plan"):
        validate_search_plan(invalid_doi)


def test_network_is_opt_in_at_cli_boundary(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(DISCOVERY_SCRIPT),
            "--plan",
            str(write_plan(tmp_path)),
            "--output",
            str(tmp_path / "pool.json"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--allow-network" in result.stderr
    assert not (tmp_path / "pool.json").exists()


def test_bounded_routes_normalization_failure_isolation_and_determinism() -> None:
    first_transport = FakeTransport()
    second_transport = FakeTransport()

    first = build_candidate_pool(search_plan(), transport=first_transport, timeout_seconds=7.5)
    second = build_candidate_pool(search_plan(), transport=second_transport, timeout_seconds=7.5)

    assert first == second
    assert len(_query_calls(first_transport, "api.openalex.org")) == 2
    assert len(_query_calls(first_transport, "api.crossref.org")) == 2
    assert all(timeout == 7.5 for _url, timeout in first_transport.calls)

    openalex_searches = _query_calls(first_transport, "api.openalex.org")
    for url in openalex_searches:
        params = parse_qs(urlsplit(url).query)
        assert params["per_page"] == ["100"]
        assert params["filter"] == [
            "from_publication_date:2017-01-01,to_publication_date:2025-12-31"
        ]
    crossref_searches = _query_calls(first_transport, "api.crossref.org")
    for url in crossref_searches:
        params = parse_qs(urlsplit(url).query)
        assert params["rows"] == ["100"]
        assert params["filter"] == ["from-pub-date:2017-01-01,until-pub-date:2025-12-31"]

    seed_calls = [url for url, _ in first_transport.calls if "/works/https://doi.org/" in urlsplit(url).path]
    backward_calls = [
        url
        for url, _ in first_transport.calls
        if parse_qs(urlsplit(url).query).get("filter", [""])[0].startswith("openalex:")
    ]
    forward_calls = [
        url
        for url, _ in first_transport.calls
        if parse_qs(urlsplit(url).query).get("filter") == ["cites:W900"]
    ]
    assert len(seed_calls) == len(backward_calls) == len(forward_calls) == 1
    assert len(first_transport.backward_ids) == 100
    assert "W499" not in first_transport.backward_ids
    for url in backward_calls + forward_calls:
        assert parse_qs(urlsplit(url).query)["per_page"] == ["100"]

    by_doi = {row["doi"]: row for row in first["candidates"] if row["doi"]}
    assert by_doi["10.1000/example"]["abstract"] == "Indexed OpenAlex fixture abstract"
    assert by_doi["10.1000/crossref"]["abstract"] == "Tagged abstract & entities."
    assert "10.1000/old" not in by_doi
    assert "10.1000/future" not in by_doi
    assert sum(row["openalex_id"] == "W200" for row in first["candidates"]) == 1
    assert sum(row["title"].casefold() == "normalized title fallback" for row in first["candidates"]) == 1

    assert first["warnings"] == [
        {
            "provider": "crossref",
            "operation": "query_search",
            "error_class": "TimeoutError",
            "message": "provider request failed",
        }
    ]
    assert "10.1000/forward" in by_doi
    assert "10.1000/backward" in by_doi
    assert {item["kind"] for item in by_doi["10.1000/backward"]["provenance"]} == {
        "backward_reference"
    }
    assert {item["kind"] for item in by_doi["10.1000/forward"]["provenance"]} == {
        "forward_citation"
    }

    expected_fields = {
        "candidate_id",
        "title",
        "authors",
        "year",
        "journal",
        "doi",
        "openalex_id",
        "landing_page_url",
        "oa_locations",
        "abstract",
        "provenance",
    }
    assert all(set(candidate) == expected_fields for candidate in first["candidates"])
    serialized = json.dumps(first, sort_keys=True)
    assert "scientifically_included" not in serialized
    assert '"included"' not in serialized
