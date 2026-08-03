"""Bounded, reproducible scholarly candidate discovery.

Protocol references consulted 2026-07-25:

* https://developers.openalex.org/api-reference/introduction
* https://developers.openalex.org/guides/authentication
* https://developers.openalex.org/guides/page-through-results
* https://developers.openalex.org/guides/recipes
* https://www.crossref.org/documentation/retrieve-metadata/rest-api/
* https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/

Adopted: OpenAlex's current maximum is ``per_page=100``. Crossref supports
``rows`` up to 1,000, but this client deliberately caps Crossref at
``rows=100``; paired with OpenAlex ``per_page=100``, that permits at most 200
combined raw search hits per query. OpenAlex no-key access is suitable only
for this trial-scale path. Although both APIs document pagination (and
Crossref cursors), this product deliberately makes one request per route,
without retries or deep cursor traversal, so candidate provenance remains
bounded and reproducible.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any


OPENALEX_ORIGIN = "https://api.openalex.org"
CROSSREF_ORIGIN = "https://api.crossref.org"
RESULT_LIMIT = 100
MAX_QUERIES = 8
MAX_SEED_DOIS = 4
MAX_QUERY_CHARS = 500
MAX_DOI_INPUT_CHARS = 512
MAX_PROVIDER_CALLS = 2 * MAX_QUERIES + 3 * MAX_SEED_DOIS
USER_AGENT = (
    "review-writer-scholarly-discovery/1.0 "
    "(+https://github.com/XuehaiWang/review-writer)"
)
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
OPENALEX_ID_RE = re.compile(r"^W[0-9]+$")
SAFE_ERROR_CLASS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")
PROVIDER_PRIORITY = {"openalex": 0, "crossref": 1}


class _MarkupTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Fail closed before urllib can request any redirect destination."""

    def redirect_request(
        self,
        _request,
        _file_pointer,
        _code,
        _message,
        _headers,
        _new_url,
    ):
        return None


class UrllibScholarlyTransport:
    """Minimal JSON transport restricted to the two public metadata hosts."""

    def get_json(self, url: str, timeout_seconds: float) -> dict:
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc not in {"api.openalex.org", "api.crossref.org"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("scholarly transport URL is not an allowed fixed endpoint")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        opener = urllib.request.build_opener(_RejectRedirectHandler())
        with opener.open(request, timeout=timeout_seconds) as response:  # noqa: S310 - fixed hosts and redirects fail closed.
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("scholarly provider response must be a JSON object")
        return payload


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(html.unescape(value).split())


def _normalize_doi(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip()
    folded = normalized.casefold()
    for prefix in ("https://doi.org/", "doi:"):
        if folded.startswith(prefix):
            normalized = normalized[len(prefix) :].strip()
            break
    return normalized.casefold()


def _valid_doi(value: Any) -> bool:
    normalized = _normalize_doi(value)
    return bool(normalized and DOI_RE.fullmatch(normalized))


def _normalize_openalex_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    raw_value = value.strip()
    if OPENALEX_ID_RE.fullmatch(raw_value):
        return raw_value
    try:
        parsed = urllib.parse.urlsplit(raw_value)
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
    ):
        return ""
    if parsed.hostname == "openalex.org" and re.fullmatch(r"/W[0-9]+", parsed.path):
        return parsed.path[1:]
    if parsed.hostname == "api.openalex.org" and re.fullmatch(r"/works/W[0-9]+", parsed.path):
        return parsed.path.rsplit("/", 1)[-1]
    return ""


def validate_search_plan(plan: dict) -> dict:
    if not isinstance(plan, dict) or plan.get("schema_version") != "scholarly-search-plan.v1":
        raise ValueError("invalid scholarly search plan")
    queries = plan.get("queries")
    start, end = plan.get("from_year"), plan.get("to_year")
    if (
        not isinstance(queries, list)
        or not queries
        or not all(
            isinstance(query, str)
            and query.strip()
            and len(query) <= MAX_QUERY_CHARS
            for query in queries
        )
    ):
        raise ValueError("search plan requires nonempty queries")
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or start > end
    ):
        raise ValueError("search plan year range is invalid")
    seed_dois = plan.get("seed_dois")
    if not isinstance(seed_dois, list) or not all(
        isinstance(doi, str)
        and len(doi) <= MAX_DOI_INPUT_CHARS
        and _valid_doi(doi)
        for doi in seed_dois
    ):
        raise ValueError("search plan seed_dois are invalid")
    normalized_queries = list(dict.fromkeys(query.strip() for query in queries))
    normalized_seed_dois = list(dict.fromkeys(_normalize_doi(doi) for doi in seed_dois))
    if (
        len(normalized_queries) > MAX_QUERIES
        or len(normalized_seed_dois) > MAX_SEED_DOIS
        or any(len(query) > MAX_QUERY_CHARS for query in normalized_queries)
        or any(len(doi) > MAX_DOI_INPUT_CHARS for doi in normalized_seed_dois)
    ):
        raise ValueError("search plan request bounds are invalid")
    return {
        **plan,
        "queries": normalized_queries,
        "seed_dois": normalized_seed_dois,
    }


def _provider_url(origin: str, path: str, params: dict[str, str | int]) -> str:
    return f"{origin}{path}?{urllib.parse.urlencode(params)}"


def _openalex_query_url(query: str, start: int, end: int) -> str:
    return _provider_url(
        OPENALEX_ORIGIN,
        "/works",
        {
            "search": query,
            "filter": (
                f"from_publication_date:{start}-01-01,"
                f"to_publication_date:{end}-12-31"
            ),
            "per_page": RESULT_LIMIT,
        },
    )


def _crossref_query_url(query: str, start: int, end: int) -> str:
    return _provider_url(
        CROSSREF_ORIGIN,
        "/works",
        {
            "query.bibliographic": query,
            "filter": f"from-pub-date:{start}-01-01,until-pub-date:{end}-12-31",
            "rows": RESULT_LIMIT,
        },
    )


def _seed_url(doi: str) -> str:
    return f"{OPENALEX_ORIGIN}/works/https://doi.org/{urllib.parse.quote(doi, safe='')}"


def _backward_url(openalex_ids: list[str]) -> str:
    return _provider_url(
        OPENALEX_ORIGIN,
        "/works",
        {"filter": f"openalex:{'|'.join(openalex_ids)}", "per_page": RESULT_LIMIT},
    )


def _forward_url(seed_openalex_id: str) -> str:
    return _provider_url(
        OPENALEX_ORIGIN,
        "/works",
        {"filter": f"cites:{seed_openalex_id}", "per_page": RESULT_LIMIT},
    )


def _results_list(payload: dict, *, provider: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise TypeError("provider response must be a JSON object")
    if provider == "openalex":
        if "results" not in payload:
            raise TypeError("OpenAlex response requires a results list")
        results = payload["results"]
    elif provider == "crossref":
        if "message" not in payload:
            raise TypeError("Crossref response requires a message object")
        message = payload["message"]
        if not isinstance(message, dict):
            raise TypeError("Crossref response message must be an object")
        if "items" not in message:
            raise TypeError("Crossref response message requires an items list")
        results = message["items"]
    else:
        raise ValueError("unknown scholarly provider")
    if not isinstance(results, list):
        raise TypeError("provider results must be a list")
    bounded_results = results[:RESULT_LIMIT]
    if not all(isinstance(item, dict) for item in bounded_results):
        raise TypeError("provider result items must be objects")
    return bounded_results


def _first_text(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            text = _normalize_text(item)
            if text:
                return text
        return ""
    return _normalize_text(value)


def _year(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _crossref_year(item: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "published", "issued"):
        date = item.get(key)
        if not isinstance(date, dict):
            continue
        parts = date.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            result = _year(parts[0][0])
            if result is not None:
                return result
    return None


def _openalex_authors(item: dict[str, Any]) -> list[str]:
    authorships = item.get("authorships")
    if not isinstance(authorships, list):
        return []
    names: list[str] = []
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        name = _normalize_text(author.get("display_name")) if isinstance(author, dict) else ""
        if not name:
            name = _normalize_text(authorship.get("raw_author_name"))
        if name and name not in names:
            names.append(name)
    return names


def _crossref_authors(item: dict[str, Any]) -> list[str]:
    authors = item.get("author")
    if not isinstance(authors, list):
        return []
    names: list[str] = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        name = _normalize_text(author.get("name"))
        if not name:
            name = _normalize_text(
                " ".join(
                    part
                    for part in (
                        _normalize_text(author.get("given")),
                        _normalize_text(author.get("family")),
                    )
                    if part
                )
            )
        if name and name not in names:
            names.append(name)
    return names


def _openalex_abstract(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    positioned_words: list[tuple[int, str]] = []
    for word, positions in value.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for position in positions:
            parsed_position = _year(position)
            if parsed_position is not None and parsed_position >= 0:
                positioned_words.append((parsed_position, word))
    positioned_words.sort(key=lambda pair: (pair[0], pair[1].casefold(), pair[1]))
    return _normalize_text(" ".join(word for _position, word in positioned_words))


def _crossref_abstract(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    parser = _MarkupTextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except (ValueError, AssertionError):
        return _normalize_text(re.sub(r"<[^>]*>", " ", value))
    return _normalize_text(" ".join(parser.parts))


def _location_record(location: Any) -> dict[str, str] | None:
    if not isinstance(location, dict):
        return None
    source = location.get("source")
    record = {
        "landing_page_url": _normalize_text(location.get("landing_page_url")),
        "pdf_url": _normalize_text(location.get("pdf_url")),
        "version": _normalize_text(location.get("version")),
        "license": _normalize_text(location.get("license")),
        "source": _normalize_text(source.get("display_name")) if isinstance(source, dict) else "",
    }
    return record if any(record.values()) else None


def _openalex_oa_locations(item: dict[str, Any]) -> list[dict[str, str]]:
    locations: list[dict[str, str]] = []
    best = _location_record(item.get("best_oa_location"))
    if best is not None:
        locations.append(best)
    raw_locations = item.get("locations")
    if isinstance(raw_locations, list):
        for raw_location in raw_locations:
            if not isinstance(raw_location, dict) or raw_location.get("is_oa") is not True:
                continue
            location = _location_record(raw_location)
            if location is not None:
                locations.append(location)
    unique = {json.dumps(location, sort_keys=True): location for location in locations}
    return [unique[key] for key in sorted(unique)]


def _openalex_journal(item: dict[str, Any]) -> str:
    primary = item.get("primary_location")
    if isinstance(primary, dict):
        source = primary.get("source")
        if isinstance(source, dict):
            journal = _normalize_text(source.get("display_name"))
            if journal:
                return journal
    host_venue = item.get("host_venue")
    return _normalize_text(host_venue.get("display_name")) if isinstance(host_venue, dict) else ""


def _openalex_landing_page(item: dict[str, Any]) -> str:
    primary = item.get("primary_location")
    if isinstance(primary, dict):
        landing_page = _normalize_text(primary.get("landing_page_url"))
        if landing_page:
            return landing_page
    return _normalize_text(item.get("doi"))


def _openalex_candidate(item: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    identifiers = item.get("ids")
    ids = identifiers if isinstance(identifiers, dict) else {}
    doi = _normalize_doi(item.get("doi") or ids.get("doi"))
    if doi and not _valid_doi(doi):
        doi = ""
    return {
        "title": _normalize_text(item.get("display_name") or item.get("title")),
        "authors": _openalex_authors(item),
        "year": _year(item.get("publication_year")),
        "journal": _openalex_journal(item),
        "doi": doi,
        "openalex_id": _normalize_openalex_id(item.get("id") or ids.get("openalex")),
        "landing_page_url": _openalex_landing_page(item),
        "oa_locations": _openalex_oa_locations(item),
        "abstract": _openalex_abstract(item.get("abstract_inverted_index")),
        "provenance": [provenance],
    }


def _validate_seed_work(payload: Any, seed_doi: str) -> tuple[dict[str, Any], str]:
    if not isinstance(payload, dict):
        raise TypeError("OpenAlex seed response must be a JSON object")
    identifiers = payload.get("ids")
    ids = identifiers if isinstance(identifiers, dict) else {}
    openalex_id = _normalize_openalex_id(payload.get("id") or ids.get("openalex"))
    resolved_doi = _normalize_doi(payload.get("doi") or ids.get("doi"))
    if not openalex_id or resolved_doi != seed_doi:
        raise ValueError("OpenAlex seed response identity is invalid")
    return payload, openalex_id


def _crossref_candidate(item: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    doi = _normalize_doi(item.get("DOI"))
    if doi and not _valid_doi(doi):
        doi = ""
    resource = item.get("resource")
    resource_primary = resource.get("primary") if isinstance(resource, dict) else None
    resource_url = resource_primary.get("URL") if isinstance(resource_primary, dict) else ""
    return {
        "title": _first_text(item.get("title")),
        "authors": _crossref_authors(item),
        "year": _crossref_year(item),
        "journal": _first_text(item.get("container-title")),
        "doi": doi,
        "openalex_id": "",
        "landing_page_url": _normalize_text(item.get("URL") or resource_url),
        "oa_locations": [],
        "abstract": _crossref_abstract(item.get("abstract")),
        "provenance": [provenance],
    }


def _normalized_title(title: str) -> str:
    return _normalize_text(title).casefold()


def _dedup_key(candidate: dict[str, Any]) -> str:
    if candidate["doi"]:
        return f"doi:{candidate['doi']}"
    if candidate["openalex_id"]:
        return f"openalex:{candidate['openalex_id'].casefold()}"
    title = _normalized_title(candidate["title"])
    return f"title:{title}" if title else ""


def _identity_keys(candidate: dict[str, Any]) -> tuple[str, ...]:
    keys: list[str] = []
    doi = _normalize_doi(candidate.get("doi"))
    if doi and _valid_doi(doi):
        keys.append(f"doi:{doi}")
    openalex_id = _normalize_openalex_id(candidate.get("openalex_id"))
    if openalex_id:
        keys.append(f"openalex:{openalex_id.casefold()}")
    title = _normalized_title(candidate.get("title", ""))
    if title:
        keys.append(f"title:{title}")
    return tuple(keys)


def _provenance_sort_key(item: dict[str, Any]) -> tuple[str, str, str, str, str, int]:
    return (
        str(item.get("provider", "")),
        str(item.get("operation", "")),
        str(item.get("query", "")),
        str(item.get("seed_doi", "")),
        str(item.get("route", "")),
        int(item.get("bounded_pass", 0)),
    )


def _provider_rank(candidate: dict[str, Any]) -> int:
    ranks = [
        PROVIDER_PRIORITY.get(str(item.get("provider", "")), len(PROVIDER_PRIORITY))
        for item in candidate.get("provenance", [])
        if isinstance(item, dict)
    ]
    return min(ranks, default=len(PROVIDER_PRIORITY))


def _select_text(candidates: list[dict[str, Any]], field: str) -> str:
    """Prefer OpenAlex, then Crossref; within a provider prefer length, then lexical order."""

    choices: list[tuple[int, int, str, str]] = []
    for candidate in candidates:
        value = _normalize_text(candidate.get(field))
        if value:
            choices.append((_provider_rank(candidate), -len(value), value.casefold(), value))
    return min(choices)[-1] if choices else ""


def _select_authors(candidates: list[dict[str, Any]]) -> list[str]:
    choices: list[tuple[int, int, tuple[str, ...], tuple[str, ...]]] = []
    for candidate in candidates:
        raw_authors = candidate.get("authors")
        if not isinstance(raw_authors, list):
            continue
        authors = tuple(
            author
            for author in (_normalize_text(value) for value in raw_authors)
            if author
        )
        if authors:
            choices.append(
                (
                    _provider_rank(candidate),
                    -len(authors),
                    tuple(author.casefold() for author in authors),
                    authors,
                )
            )
    return list(min(choices)[-1]) if choices else []


def _select_year(candidates: list[dict[str, Any]]) -> int | None:
    choices = [
        (_provider_rank(candidate), year)
        for candidate in candidates
        if (year := _year(candidate.get("year"))) is not None
    ]
    return min(choices)[1] if choices else None


def _select_identifier(candidates: list[dict[str, Any]], field: str) -> str:
    if field == "doi":
        values = {
            value
            for value in (_normalize_doi(candidate.get(field)) for candidate in candidates)
            if value and _valid_doi(value)
        }
    else:
        values = {
            value
            for value in (_normalize_openalex_id(candidate.get(field)) for candidate in candidates)
            if value
        }
    return min(values, key=lambda value: (value.casefold(), value)) if values else ""


def _reduce_identity_component(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    locations = [
        location
        for candidate in candidates
        for location in candidate.get("oa_locations", [])
        if isinstance(location, dict)
    ]
    unique_locations = {json.dumps(location, sort_keys=True): location for location in locations}
    provenance = [
        item
        for candidate in candidates
        for item in candidate.get("provenance", [])
        if isinstance(item, dict)
    ]
    unique_provenance = {json.dumps(item, sort_keys=True): item for item in provenance}
    return {
        "title": _select_text(candidates, "title"),
        "authors": _select_authors(candidates),
        "year": _select_year(candidates),
        "journal": _select_text(candidates, "journal"),
        "doi": _select_identifier(candidates, "doi"),
        "openalex_id": _select_identifier(candidates, "openalex_id"),
        "landing_page_url": _select_text(candidates, "landing_page_url"),
        "oa_locations": [unique_locations[key] for key in sorted(unique_locations)],
        "abstract": _select_text(candidates, "abstract"),
        "provenance": sorted(unique_provenance.values(), key=_provenance_sort_key),
    }


def _candidate_id(candidate: dict[str, Any]) -> str:
    identity = _dedup_key(candidate)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"scholarly-{digest}"


def _deduplicate(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keyed_candidates = [
        (candidate, keys)
        for candidate in candidates
        if (keys := _identity_keys(candidate))
    ]
    parents = list(range(len(keyed_candidates)))
    component_dois = [
        {doi} if (doi := _normalize_doi(candidate.get("doi"))) and _valid_doi(doi) else set()
        for candidate, _keys in keyed_candidates
    ]
    component_openalex_ids = [
        {openalex_id} if (openalex_id := _normalize_openalex_id(candidate.get("openalex_id"))) else set()
        for candidate, _keys in keyed_candidates
    ]

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        lower, higher = sorted((left_root, right_root))
        parents[higher] = lower
        component_dois[lower].update(component_dois[higher])
        component_openalex_ids[lower].update(component_openalex_ids[higher])

    doi_owner: dict[str, int] = {}
    for index, (_candidate, keys) in enumerate(keyed_candidates):
        for key in keys:
            if not key.startswith("doi:"):
                continue
            if key in doi_owner:
                union(index, doi_owner[key])
            else:
                doi_owner[key] = index

    openalex_groups: dict[str, list[int]] = {}
    for index, (_candidate, keys) in enumerate(keyed_candidates):
        for key in keys:
            if key.startswith("openalex:"):
                openalex_groups.setdefault(key, []).append(index)
    for key in sorted(openalex_groups):
        roots = sorted({find(index) for index in openalex_groups[key]})
        dois = {doi for root in roots for doi in component_dois[root]}
        if len(dois) > 1:
            continue
        for root in roots[1:]:
            union(roots[0], root)

    title_groups: dict[str, list[int]] = {}
    for index, (candidate, _keys) in enumerate(keyed_candidates):
        title = _normalized_title(candidate.get("title", ""))
        if title:
            title_groups.setdefault(title, []).append(index)
    for title in sorted(title_groups):
        roots = sorted({find(index) for index in title_groups[title]})
        if len(roots) < 2:
            continue
        doi_roots = [root for root in roots if component_dois[root]]
        openalex_roots = [root for root in roots if component_openalex_ids[root]]
        if len(doi_roots) > 1 or len(openalex_roots) > 1:
            continue
        for root in roots[1:]:
            union(roots[0], root)

    components: dict[int, list[dict[str, Any]]] = {}
    for index, (candidate, _keys) in enumerate(keyed_candidates):
        components.setdefault(find(index), []).append(candidate)

    result: list[dict[str, Any]] = []
    for component in components.values():
        candidate = _reduce_identity_component(component)
        candidate["candidate_id"] = _candidate_id(candidate)
        result.append(candidate)
    result.sort(
        key=lambda candidate: (
            candidate["year"] is None,
            candidate["year"] if candidate["year"] is not None else 0,
            candidate["doi"] or _normalized_title(candidate["title"]),
            candidate["candidate_id"],
        )
    )
    return result


def _warning(
    provider: str,
    operation: str,
    error: Exception,
    *,
    query: str = "",
    seed_doi: str = "",
) -> dict[str, str]:
    error_class = type(error).__name__
    if not SAFE_ERROR_CLASS_RE.fullmatch(error_class):
        error_class = "Exception"
    warning = {
        "provider": provider,
        "operation": operation,
        "error_class": error_class,
        "message": "provider request failed",
    }
    if query:
        warning["query"] = query
    if seed_doi:
        warning["seed_doi"] = seed_doi
    return warning


def _in_year_range(candidate: dict[str, Any], start: int, end: int) -> bool:
    year = candidate["year"]
    return year is None or start <= year <= end


def _search_provenance(provider: str, query: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "route": "/works",
        "operation": "query_search",
        "query": query,
        "bounded_pass": 1,
    }


def _seed_provenance(operation: str, seed_doi: str, route: str) -> dict[str, Any]:
    return {
        "provider": "openalex",
        "route": route,
        "operation": operation,
        "seed_doi": seed_doi,
        "bounded_pass": 1,
    }


def build_candidate_pool(
    plan: dict,
    transport: Any,
    timeout_seconds: float = 20.0,
) -> dict:
    """Build a candidate-only pool from one bounded pass over each route."""

    validated = validate_search_plan(plan)
    if (
        not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds must be finite and greater than zero")

    start = validated["from_year"]
    end = validated["to_year"]
    raw_candidates: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    raw_search_hits = 0
    raw_seed_resolution_hits = 0
    raw_backward_hits = 0
    raw_forward_hits = 0
    filtered_out_by_year = 0

    for query in validated["queries"]:
        for provider, url in (
            ("openalex", _openalex_query_url(query, start, end)),
            ("crossref", _crossref_query_url(query, start, end)),
        ):
            try:
                payload = transport.get_json(url, timeout_seconds)
                items = _results_list(payload, provider=provider)
                for item in items:
                    provenance = _search_provenance(provider, query)
                    candidate = (
                        _openalex_candidate(item, provenance)
                        if provider == "openalex"
                        else _crossref_candidate(item, provenance)
                    )
                    if not _identity_keys(candidate):
                        warnings.append(
                            _warning(
                                provider,
                                "query_result",
                                ValueError("normalized result has no usable identity"),
                                query=query,
                            )
                        )
                        continue
                    raw_search_hits += 1
                    if _in_year_range(candidate, start, end):
                        raw_candidates.append(candidate)
                    else:
                        filtered_out_by_year += 1
            except Exception as error:  # noqa: BLE001 - each external source is isolated into a warning.
                warnings.append(_warning(provider, "query_search", error, query=query))

    for seed_doi in validated["seed_dois"]:
        seed_work: dict[str, Any] | None = None
        seed_openalex_id = ""
        try:
            payload = transport.get_json(_seed_url(seed_doi), timeout_seconds)
            seed_work, seed_openalex_id = _validate_seed_work(payload, seed_doi)
            raw_seed_resolution_hits += 1
            seed_candidate = _openalex_candidate(
                seed_work,
                _seed_provenance(
                    "seed_resolution",
                    seed_doi,
                    "/works/https://doi.org/{doi}",
                ),
            )
            if _in_year_range(seed_candidate, start, end):
                raw_candidates.append(seed_candidate)
            else:
                filtered_out_by_year += 1
        except Exception as error:  # noqa: BLE001 - seed failures cannot erase query results.
            warnings.append(
                _warning("openalex", "seed_resolution", error, seed_doi=seed_doi)
            )

        if seed_work is None:
            continue
        references = seed_work.get("referenced_works")
        if isinstance(references, list):
            reference_ids = list(
                dict.fromkeys(
                    openalex_id
                    for openalex_id in (_normalize_openalex_id(reference) for reference in references)
                    if openalex_id
                )
            )[:RESULT_LIMIT]
        else:
            reference_ids = []

        if reference_ids:
            try:
                payload = transport.get_json(_backward_url(reference_ids), timeout_seconds)
                items = _results_list(payload, provider="openalex")
                for item in items:
                    candidate = _openalex_candidate(
                        item,
                        _seed_provenance(
                            "backward_reference",
                            seed_doi,
                            "/works?filter=openalex:{ids}",
                        ),
                    )
                    if not _identity_keys(candidate):
                        warnings.append(
                            _warning(
                                "openalex",
                                "backward_reference_result",
                                ValueError("normalized result has no usable identity"),
                                seed_doi=seed_doi,
                            )
                        )
                        continue
                    raw_backward_hits += 1
                    if _in_year_range(candidate, start, end):
                        raw_candidates.append(candidate)
                    else:
                        filtered_out_by_year += 1
            except Exception as error:  # noqa: BLE001 - forward pass still runs after this warning.
                warnings.append(
                    _warning(
                        "openalex",
                        "backward_references",
                        error,
                        seed_doi=seed_doi,
                    )
                )

        if seed_openalex_id:
            try:
                payload = transport.get_json(_forward_url(seed_openalex_id), timeout_seconds)
                items = _results_list(payload, provider="openalex")
                for item in items:
                    candidate = _openalex_candidate(
                        item,
                        _seed_provenance(
                            "forward_citation",
                            seed_doi,
                            "/works?filter=cites:{openalex_id}",
                        ),
                    )
                    if not _identity_keys(candidate):
                        warnings.append(
                            _warning(
                                "openalex",
                                "forward_citation_result",
                                ValueError("normalized result has no usable identity"),
                                seed_doi=seed_doi,
                            )
                        )
                        continue
                    raw_forward_hits += 1
                    if _in_year_range(candidate, start, end):
                        raw_candidates.append(candidate)
                    else:
                        filtered_out_by_year += 1
            except Exception as error:  # noqa: BLE001 - completed work remains available.
                warnings.append(
                    _warning(
                        "openalex",
                        "forward_citations",
                        error,
                        seed_doi=seed_doi,
                    )
                )

    candidates = _deduplicate(raw_candidates)
    canonical_plan = {
        "schema_version": validated["schema_version"],
        "from_year": start,
        "to_year": end,
        "queries": validated["queries"],
        "seed_dois": validated["seed_dois"],
    }
    return {
        "schema_version": "scholarly-candidate-pool.v1",
        "search_plan": canonical_plan,
        "request_bounds": {
            "max_queries": MAX_QUERIES,
            "max_seed_dois": MAX_SEED_DOIS,
            "max_provider_calls": MAX_PROVIDER_CALLS,
            "openalex_results_per_request": RESULT_LIMIT,
            "crossref_results_per_request": RESULT_LIMIT,
            "query_requests_per_provider": 1,
            "backward_batches_per_seed": 1,
            "forward_requests_per_seed": 1,
            "recursive_chaining": False,
        },
        "counts": {
            "queries": len(validated["queries"]),
            "seed_dois": len(validated["seed_dois"]),
            "raw_search_hits": raw_search_hits,
            "raw_seed_resolution_hits": raw_seed_resolution_hits,
            "raw_backward_hits": raw_backward_hits,
            "raw_forward_hits": raw_forward_hits,
            "filtered_out_by_year": filtered_out_by_year,
            "unique_candidates": len(candidates),
            "warnings": len(warnings),
        },
        "warnings": warnings,
        "candidates": candidates,
    }
