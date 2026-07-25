from __future__ import annotations

import copy
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from review_writer.discovery import scholarly as scholarly_module
from review_writer.discovery.scholarly import (
    UrllibScholarlyTransport,
    _deduplicate,
    _normalize_openalex_id,
    build_candidate_pool,
    validate_search_plan,
)


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
        "published-print": {"date-parts": [[year, 6, 1]]},
        "published-online": {"date-parts": [[year - 1, 5, 1]]},
        "published": {"date-parts": [[year - 2, 4, 1]]},
        "issued": {"date-parts": [[year - 3, 3, 1]]},
        "created": {"date-parts": [[year - 20, 2, 1]]},
        "DOI": doi,
        "author": [
            {"given": "Ada", "family": "Example"},
            {"name": "Fixture Consortium"},
        ],
        "container-title": ["Crossref Fixture Journal"],
        "URL": f"https://doi.org/{doi}" if doi else "https://example.org/title-only",
        "abstract": abstract,
    }


def _crossref_lifecycle_only_work() -> dict:
    item = _crossref_work(
        "Lifecycle Dates Are Not Publication Dates",
        2022,
        doi="10.1000/lifecycle-only",
    )
    for field in ("published-print", "published-online", "published", "issued"):
        item.pop(field)
    item.update(
        {
            "created": {"date-parts": [[2018, 1, 1]]},
            "deposited": {"date-parts": [[2024, 1, 1]]},
            "indexed": {"date-parts": [[2025, 1, 1]]},
        }
    )
    return item


def _raw_candidate(
    *,
    provider: str,
    query: str,
    title: str,
    doi: str = "",
    openalex_id: str = "",
    authors: list[str] | None = None,
    year: int | None = None,
    journal: str = "",
    landing_page_url: str = "",
    abstract: str = "",
) -> dict:
    return {
        "title": title,
        "authors": authors or [],
        "year": year,
        "journal": journal,
        "doi": doi,
        "openalex_id": openalex_id,
        "landing_page_url": landing_page_url,
        "oa_locations": [],
        "abstract": abstract,
        "provenance": [
            {
                "provider": provider,
                "route": "/works",
                "operation": "query_search",
                "query": query,
                "bounded_pass": 1,
            }
        ],
    }


class _RedirectingOpener:
    """Emulates urllib redirect handling without opening a socket."""

    def __init__(self, handlers: tuple[object, ...], redirect_target: str) -> None:
        self.redirect_target = redirect_target
        self.requested_urls: list[str] = []
        self.redirect_handler = next(
            handler
            for handler in handlers
            if isinstance(handler, urllib.request.HTTPRedirectHandler)
        )

    def open(self, request: urllib.request.Request, timeout: float):
        assert timeout == 3.0
        self.requested_urls.append(request.full_url)
        redirected_request = self.redirect_handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            self.redirect_target,
        )
        if redirected_request is None:
            raise urllib.error.HTTPError(request.full_url, 302, "Found", {}, None)
        self.requested_urls.append(redirected_request.full_url)
        raise AssertionError("redirect target must never be requested")


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
                        _crossref_lifecycle_only_work(),
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


class OrderingTransport:
    def __init__(self, *, reverse_openalex_results: bool) -> None:
        self.reverse_openalex_results = reverse_openalex_results

    def get_json(self, url: str, timeout_seconds: float) -> dict:
        assert timeout_seconds == 20.0
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        if parsed.netloc == "api.openalex.org" and "search" in params:
            rows = self._openalex_rows()
            if self.reverse_openalex_results:
                rows.reverse()
            return {"results": rows}
        if parsed.netloc == "api.crossref.org" and "query.bibliographic" in params:
            crossref = _crossref_work(
                "Crossref title intentionally longer than either OpenAlex title",
                2010,
                doi="10.1000/order-independent",
                abstract="<jats:p>Crossref abstract intentionally much longer.</jats:p>",
            )
            crossref["author"] = [
                {"given": "Crossref", "family": "One"},
                {"given": "Crossref", "family": "Two"},
                {"given": "Crossref", "family": "Three"},
            ]
            return {"message": {"items": [crossref]}}
        raise AssertionError("ordering fixture received an unexpected route")

    @staticmethod
    def _openalex_rows() -> list[dict]:
        first = _openalex_work(
            "W700",
            "Short title",
            2020,
            doi="10.1000/order-independent",
            abstract_inverted_index={"Zulu": [0], "data": [1]},
        )
        first["authorships"] = [{"author": {"display_name": "Solo Author"}}]
        first["primary_location"] = {
            "landing_page_url": "https://example.org/z",
            "source": {"display_name": "Zulu Venue"},
        }
        second = _openalex_work(
            "W700",
            "A substantially longer OpenAlex title",
            2021,
            doi="10.1000/order-independent",
            abstract_inverted_index={"Beta": [0], "data": [1]},
        )
        second["primary_location"] = {
            "landing_page_url": "https://example.org/a",
            "source": {"display_name": "Beta Venue"},
        }
        return [first, second]


class EnvelopeTransport:
    def __init__(self, *, malformed_provider: str, malformed_payload: dict) -> None:
        self.malformed_provider = malformed_provider
        self.malformed_payload = malformed_payload

    def get_json(self, url: str, timeout_seconds: float) -> dict:
        assert timeout_seconds == 20.0
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        if parsed.netloc == "api.openalex.org" and "search" in params:
            if self.malformed_provider == "openalex":
                return copy.deepcopy(self.malformed_payload)
            return {
                "results": [
                    _openalex_work(
                        "W810",
                        "Valid OpenAlex Route Result",
                        2020,
                        doi="10.1000/valid-openalex",
                    )
                ]
            }
        if parsed.netloc == "api.crossref.org" and "query.bibliographic" in params:
            if self.malformed_provider == "crossref":
                return copy.deepcopy(self.malformed_payload)
            return {
                "message": {
                    "items": [
                        _crossref_work(
                            "Valid Crossref Route Result",
                            2020,
                            doi="10.1000/valid-crossref",
                        )
                    ]
                }
            }
        raise AssertionError("envelope fixture received an unexpected route")


class InvalidSeedTransport:
    def __init__(self, seed_payload: dict) -> None:
        self.seed_payload = seed_payload
        self.calls: list[str] = []

    def get_json(self, url: str, timeout_seconds: float) -> dict:
        assert timeout_seconds == 20.0
        self.calls.append(url)
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        if parsed.netloc == "api.crossref.org":
            return {"message": {"items": []}}
        if parsed.path.startswith("/works/https://doi.org/"):
            return copy.deepcopy(self.seed_payload)
        if "search" in params:
            return {"results": []}
        if params.get("filter", [""])[0].startswith(("cites:", "openalex:")):
            return {"results": []}
        raise AssertionError("seed fixture received an unexpected route")


class IdentitylessResultTransport:
    def __init__(self, malformed_provider: str) -> None:
        self.malformed_provider = malformed_provider

    def get_json(self, url: str, timeout_seconds: float) -> dict:
        assert timeout_seconds == 20.0
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        if parsed.netloc == "api.openalex.org" and "search" in params:
            if self.malformed_provider != "openalex":
                return {"results": []}
            return {
                "results": [
                    {
                        "id": "https://example.org/W999",
                        "doi": "not-a-doi",
                        "display_name": "   ",
                        "private_marker": "OPENALEX_RESULT_MUST_NOT_LEAK",
                    },
                    _openalex_work(
                        "W820",
                        "Valid OpenAlex Item",
                        2020,
                        doi="10.1000/valid-openalex-item",
                    ),
                ]
            }
        if parsed.netloc == "api.crossref.org" and "query.bibliographic" in params:
            if self.malformed_provider != "crossref":
                return {"message": {"items": []}}
            return {
                "message": {
                    "items": [
                        {
                            "DOI": "not-a-doi",
                            "title": ["   "],
                            "private_marker": "CROSSREF_RESULT_MUST_NOT_LEAK",
                        },
                        _crossref_work(
                            "Valid Crossref Item",
                            2020,
                            doi="10.1000/valid-crossref-item",
                        ),
                    ]
                }
            }
        raise AssertionError("identityless-result fixture received an unexpected route")


class IdentitylessChainResultTransport:
    def __init__(self, malformed_route: str) -> None:
        self.malformed_route = malformed_route

    def get_json(self, url: str, timeout_seconds: float) -> dict:
        assert timeout_seconds == 20.0
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        if parsed.netloc == "api.crossref.org":
            return {"message": {"items": []}}
        if parsed.path.startswith("/works/https://doi.org/"):
            return _openalex_work(
                "W900",
                "Resolved Chain Seed",
                2020,
                doi="10.1000/seed",
                references=["https://openalex.org/W300"],
            )
        if "search" in params:
            return {"results": []}

        filter_value = params.get("filter", [""])[0]
        if filter_value.startswith("openalex:"):
            if self.malformed_route != "backward":
                return {"results": []}
            return {
                "results": [
                    {
                        "id": "https://example.org/W998",
                        "doi": "not-a-doi",
                        "display_name": "   ",
                        "private_marker": "BACKWARD_RESULT_MUST_NOT_LEAK",
                    },
                    _openalex_work(
                        "W830",
                        "Valid Backward Item",
                        2020,
                        doi="10.1000/valid-backward-item",
                    ),
                ]
            }
        if filter_value == "cites:W900":
            if self.malformed_route != "forward":
                return {"results": []}
            return {
                "results": [
                    {
                        "id": "https://example.org/W997",
                        "doi": "not-a-doi",
                        "display_name": "   ",
                        "private_marker": "FORWARD_RESULT_MUST_NOT_LEAK",
                    },
                    _openalex_work(
                        "W831",
                        "Valid Forward Item",
                        2020,
                        doi="10.1000/valid-forward-item",
                    ),
                ]
            }
        raise AssertionError("identityless-chain fixture received an unexpected route")


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


def test_dedup_merges_rich_doi_openalex_record_with_sparse_openalex_record() -> None:
    rich = _raw_candidate(
        provider="openalex",
        query="rich query",
        title="Rich Canonical Scholarly Record",
        doi="10.1000/rich-sparse",
        openalex_id="W1000",
        authors=["Ada Rich", "Bo Rich"],
        year=2021,
        journal="Rich Journal",
        abstract="Rich abstract metadata.",
    )
    sparse = _raw_candidate(
        provider="openalex",
        query="sparse query",
        title="Sparse Record",
        openalex_id="W1000",
    )

    candidates = _deduplicate([rich, sparse])

    assert len(candidates) == 1
    assert candidates[0]["doi"] == "10.1000/rich-sparse"
    assert candidates[0]["openalex_id"] == "W1000"
    assert candidates[0]["title"] == "Rich Canonical Scholarly Record"
    assert {item["query"] for item in candidates[0]["provenance"]} == {
        "rich query",
        "sparse query",
    }


def test_same_openalex_id_does_not_merge_conflicting_nonempty_dois() -> None:
    first = _raw_candidate(
        provider="openalex",
        query="first DOI",
        title="First DOI Record",
        doi="10.1000/openalex-conflict-a",
        openalex_id="W1100",
    )
    second = _raw_candidate(
        provider="openalex",
        query="second DOI",
        title="Second DOI Record",
        doi="10.1000/openalex-conflict-b",
        openalex_id="W1100",
    )

    candidates = _deduplicate([first, second])

    assert len(candidates) == 2
    assert {candidate["doi"] for candidate in candidates} == {
        "10.1000/openalex-conflict-a",
        "10.1000/openalex-conflict-b",
    }


def test_dedup_closes_transitive_identity_intersections() -> None:
    doi_and_openalex = _raw_candidate(
        provider="openalex",
        query="doi-openalex",
        title="Primary Identity Record",
        doi="10.1000/transitive",
        openalex_id="W2000",
    )
    openalex_and_title = _raw_candidate(
        provider="openalex",
        query="openalex-title",
        title="Bridge Identity Title",
        openalex_id="W2000",
    )
    title_only = _raw_candidate(
        provider="crossref",
        query="title-only",
        title="  bridge   identity title  ",
        abstract="Metadata reached through the title bridge.",
    )

    candidates = _deduplicate([doi_and_openalex, openalex_and_title, title_only])

    assert len(candidates) == 1
    assert candidates[0]["doi"] == "10.1000/transitive"
    assert candidates[0]["openalex_id"] == "W2000"
    assert {item["query"] for item in candidates[0]["provenance"]} == {
        "doi-openalex",
        "openalex-title",
        "title-only",
    }


def test_same_title_does_not_merge_conflicting_dois() -> None:
    first = _raw_candidate(
        provider="crossref",
        query="first DOI",
        title="Shared but Ambiguous Title",
        doi="10.1000/conflict-a",
    )
    second = _raw_candidate(
        provider="crossref",
        query="second DOI",
        title="shared but ambiguous title",
        doi="10.1000/conflict-b",
    )

    candidates = _deduplicate([first, second])

    assert len(candidates) == 2
    assert {candidate["doi"] for candidate in candidates} == {
        "10.1000/conflict-a",
        "10.1000/conflict-b",
    }


def test_same_title_does_not_merge_conflicting_openalex_ids() -> None:
    first = _raw_candidate(
        provider="openalex",
        query="first OpenAlex",
        title="Shared OpenAlex Title",
        openalex_id="W3100",
    )
    second = _raw_candidate(
        provider="openalex",
        query="second OpenAlex",
        title="shared openalex title",
        openalex_id="W3200",
    )

    candidates = _deduplicate([first, second])

    assert len(candidates) == 2
    assert {candidate["openalex_id"] for candidate in candidates} == {"W3100", "W3200"}


def test_candidate_pool_is_identical_when_provider_results_are_reversed() -> None:
    plan = {
        "schema_version": "scholarly-search-plan.v1",
        "from_year": 2017,
        "to_year": 2025,
        "queries": ["ordering fixture"],
        "seed_dois": [],
    }

    forward = build_candidate_pool(
        plan,
        transport=OrderingTransport(reverse_openalex_results=False),
    )
    reverse = build_candidate_pool(
        plan,
        transport=OrderingTransport(reverse_openalex_results=True),
    )

    assert forward == reverse
    assert len(forward["candidates"]) == 1
    candidate = forward["candidates"][0]
    assert candidate["title"] == "A substantially longer OpenAlex title"
    assert candidate["authors"] == ["Ada Example", "Bo Researcher"]
    assert candidate["year"] == 2020
    assert candidate["journal"] == "Beta Venue"
    assert candidate["landing_page_url"] == "https://example.org/a"
    assert candidate["abstract"] == "Beta data"


def test_provenance_uses_operation_with_bounded_context() -> None:
    pool = build_candidate_pool(search_plan(), transport=FakeTransport())

    for candidate in pool["candidates"]:
        for provenance in candidate["provenance"]:
            assert "kind" not in provenance
            assert {"provider", "operation", "bounded_pass"} <= set(provenance)
            assert ("query" in provenance) != ("seed_doi" in provenance)


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


def test_openalex_identity_accepts_only_canonical_host_and_numeric_format() -> None:
    assert _normalize_openalex_id("W123") == "W123"
    assert _normalize_openalex_id("https://openalex.org/W123") == "W123"
    assert _normalize_openalex_id("https://api.openalex.org/works/W123") == "W123"

    assert _normalize_openalex_id("https://example.org/W123") == ""
    assert _normalize_openalex_id("https://openalex.org/WNOTREAL") == ""
    assert _normalize_openalex_id("WNOTREAL") == ""
    assert _normalize_openalex_id("http://openalex.org/W123") == ""


def test_search_plan_requires_explicit_seed_dois_list() -> None:
    missing_seed_dois = search_plan()
    missing_seed_dois.pop("seed_dois")

    with pytest.raises(ValueError, match="search plan"):
        validate_search_plan(missing_seed_dois)

    empty_seed_dois = search_plan()
    empty_seed_dois["seed_dois"] = []
    assert validate_search_plan(empty_seed_dois)["seed_dois"] == []


@pytest.mark.parametrize(
    ("malformed_provider", "malformed_payload", "surviving_doi"),
    [
        (
            "openalex",
            {"private_marker": "OPENALEX_PAYLOAD_MUST_NOT_LEAK"},
            "10.1000/valid-crossref",
        ),
        (
            "crossref",
            {"private_marker": "CROSSREF_MESSAGE_MUST_NOT_LEAK"},
            "10.1000/valid-openalex",
        ),
        (
            "crossref",
            {"message": {"private_marker": "CROSSREF_ITEMS_MUST_NOT_LEAK"}},
            "10.1000/valid-openalex",
        ),
    ],
    ids=["missing-openalex-results", "missing-crossref-message", "missing-crossref-items"],
)
def test_malformed_search_envelope_warns_without_erasing_other_provider(
    malformed_provider: str,
    malformed_payload: dict,
    surviving_doi: str,
) -> None:
    plan = {
        "schema_version": "scholarly-search-plan.v1",
        "from_year": 2017,
        "to_year": 2025,
        "queries": ["envelope fixture"],
        "seed_dois": [],
    }

    pool = build_candidate_pool(
        plan,
        transport=EnvelopeTransport(
            malformed_provider=malformed_provider,
            malformed_payload=malformed_payload,
        ),
    )

    assert pool["counts"]["raw_search_hits"] == 1
    assert pool["counts"]["unique_candidates"] == 1
    assert pool["candidates"][0]["doi"] == surviving_doi
    assert pool["warnings"] == [
        {
            "provider": malformed_provider,
            "operation": "query_search",
            "error_class": "TypeError",
            "message": "provider request failed",
        }
    ]
    assert "MUST_NOT_LEAK" not in json.dumps(pool["warnings"], sort_keys=True)


@pytest.mark.parametrize(
    ("malformed_provider", "surviving_doi"),
    [
        ("openalex", "10.1000/valid-openalex-item"),
        ("crossref", "10.1000/valid-crossref-item"),
    ],
)
def test_identityless_query_item_warns_and_is_not_counted_as_valid_hit(
    malformed_provider: str,
    surviving_doi: str,
) -> None:
    plan = {
        "schema_version": "scholarly-search-plan.v1",
        "from_year": 2017,
        "to_year": 2025,
        "queries": ["identityless item fixture"],
        "seed_dois": [],
    }

    pool = build_candidate_pool(
        plan,
        transport=IdentitylessResultTransport(malformed_provider),
    )

    assert pool["counts"]["raw_search_hits"] == 1
    assert pool["counts"]["unique_candidates"] == 1
    assert pool["candidates"][0]["doi"] == surviving_doi
    assert pool["warnings"] == [
        {
            "provider": malformed_provider,
            "operation": "query_result",
            "error_class": "ValueError",
            "message": "provider request failed",
        }
    ]
    assert "MUST_NOT_LEAK" not in json.dumps(pool["warnings"], sort_keys=True)


def test_identityless_backward_item_warns_without_counting_or_erasing_valid_item() -> None:
    pool = build_candidate_pool(
        search_plan(),
        transport=IdentitylessChainResultTransport("backward"),
    )

    assert pool["counts"]["raw_backward_hits"] == 1
    assert pool["counts"]["raw_forward_hits"] == 0
    assert {candidate["doi"] for candidate in pool["candidates"]} == {
        "10.1000/seed",
        "10.1000/valid-backward-item",
    }
    assert pool["warnings"] == [
        {
            "provider": "openalex",
            "operation": "backward_reference_result",
            "error_class": "ValueError",
            "message": "provider request failed",
        }
    ]
    assert "MUST_NOT_LEAK" not in json.dumps(pool["warnings"], sort_keys=True)


def test_identityless_forward_item_warns_without_counting_or_erasing_valid_item() -> None:
    pool = build_candidate_pool(
        search_plan(),
        transport=IdentitylessChainResultTransport("forward"),
    )

    assert pool["counts"]["raw_backward_hits"] == 0
    assert pool["counts"]["raw_forward_hits"] == 1
    assert {candidate["doi"] for candidate in pool["candidates"]} == {
        "10.1000/seed",
        "10.1000/valid-forward-item",
    }
    assert pool["warnings"] == [
        {
            "provider": "openalex",
            "operation": "forward_citation_result",
            "error_class": "ValueError",
            "message": "provider request failed",
        }
    ]
    assert "MUST_NOT_LEAK" not in json.dumps(pool["warnings"], sort_keys=True)


@pytest.mark.parametrize(
    "seed_payload",
    [
        {"private_marker": "SEED_PAYLOAD_MUST_NOT_LEAK"},
        _openalex_work("", "Seed Missing OpenAlex Identity", 2020, doi="10.1000/seed"),
        _openalex_work("W900", "Seed With Wrong DOI", 2020, doi="10.1000/not-the-seed"),
        {
            **_openalex_work("W900", "Seed With Foreign Identity Host", 2020, doi="10.1000/seed"),
            "id": "https://example.org/W900",
        },
    ],
    ids=["arbitrary-object", "missing-openalex-id", "mismatched-doi", "foreign-identity-host"],
)
def test_invalid_seed_work_identity_warns_without_counting_success(seed_payload: dict) -> None:
    plan = {
        "schema_version": "scholarly-search-plan.v1",
        "from_year": 2017,
        "to_year": 2025,
        "queries": ["seed identity fixture"],
        "seed_dois": ["10.1000/seed"],
    }
    transport = InvalidSeedTransport(seed_payload)

    pool = build_candidate_pool(plan, transport=transport)

    assert pool["counts"]["raw_seed_resolution_hits"] == 0
    assert pool["counts"]["raw_backward_hits"] == 0
    assert pool["counts"]["raw_forward_hits"] == 0
    assert pool["candidates"] == []
    assert pool["warnings"] == [
        {
            "provider": "openalex",
            "operation": "seed_resolution",
            "error_class": "ValueError",
            "message": "provider request failed",
        }
    ]
    assert len(transport.calls) == 3
    assert "MUST_NOT_LEAK" not in json.dumps(pool["warnings"], sort_keys=True)


def test_seed_ids_openalex_fallback_drives_exactly_one_forward_request() -> None:
    seed_payload = _openalex_work("", "Seed With IDs Fallback", 2020, doi="10.1000/seed")
    seed_payload["ids"] = {
        "openalex": "https://openalex.org/W901",
        "doi": "https://doi.org/10.1000/seed",
    }
    plan = {
        "schema_version": "scholarly-search-plan.v1",
        "from_year": 2017,
        "to_year": 2025,
        "queries": ["seed fallback fixture"],
        "seed_dois": ["10.1000/seed"],
    }
    transport = InvalidSeedTransport(seed_payload)

    pool = build_candidate_pool(plan, transport=transport)

    forward_filters = [
        parse_qs(urlsplit(url).query)["filter"][0]
        for url in transport.calls
        if parse_qs(urlsplit(url).query).get("filter", [""])[0].startswith("cites:")
    ]
    assert pool["counts"]["raw_seed_resolution_hits"] == 1
    assert pool["warnings"] == []
    assert forward_filters == ["cites:W901"]


@pytest.mark.parametrize(
    "redirect_target",
    [
        "https://api.openalex.org/works?page=2",
        "https://example.net/foreign-destination",
    ],
    ids=["same-host", "foreign-host"],
)
def test_urllib_transport_fails_closed_without_requesting_redirect_target(
    redirect_target: str,
) -> None:
    initial_url = "https://api.openalex.org/works?search=fixture&per_page=100"
    created_opener: _RedirectingOpener | None = None

    def fake_build_opener(*handlers: object) -> _RedirectingOpener:
        nonlocal created_opener
        created_opener = _RedirectingOpener(handlers, redirect_target)
        return created_opener

    with mock.patch.object(urllib.request, "build_opener", side_effect=fake_build_opener), mock.patch.object(
        urllib.request,
        "urlopen",
        side_effect=AssertionError("ambient urlopen must not handle provider redirects"),
    ) as ambient_urlopen:
        with pytest.raises(urllib.error.HTTPError):
            UrllibScholarlyTransport().get_json(initial_url, timeout_seconds=3.0)

    assert created_opener is not None
    assert created_opener.requested_urls == [initial_url]
    ambient_urlopen.assert_not_called()


def test_reference_note_records_crossref_larger_limit_and_combined_cap() -> None:
    reference_note = " ".join((scholarly_module.__doc__ or "").split())

    assert "Crossref supports ``rows`` up to 1,000" in reference_note
    assert "200 combined" in reference_note


def test_crossref_year_uses_publication_priority_not_lifecycle_dates() -> None:
    pool = build_candidate_pool(search_plan(), transport=FakeTransport())
    by_doi = {row["doi"]: row for row in pool["candidates"] if row["doi"]}

    assert by_doi["10.1000/crossref"]["year"] == 2022
    assert by_doi["10.1000/lifecycle-only"]["year"] is None


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
    assert {item["operation"] for item in by_doi["10.1000/backward"]["provenance"]} == {
        "backward_reference"
    }
    assert {item["operation"] for item in by_doi["10.1000/forward"]["provenance"]} == {
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
