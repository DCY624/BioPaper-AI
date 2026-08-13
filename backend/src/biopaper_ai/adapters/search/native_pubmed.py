"""Native PubMed E-utilities fallback provider."""

import asyncio
import hashlib
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from xml.etree.ElementTree import Element, ParseError

import httpx
from defusedxml import ElementTree as DefusedElementTree

from biopaper_ai.adapters.search.pubmed_mapper import map_pubmed_record
from biopaper_ai.application.ports.search_provider import (
    ProviderFailure,
    ProviderFailureCode,
    ProviderResult,
    SourceCount,
)
from biopaper_ai.config import Settings
from biopaper_ai.domain.paper import Paper
from biopaper_ai.domain.provenance import SourceName
from biopaper_ai.domain.search_plan import SearchPlan

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]
Now = Callable[[], datetime]


class NativePubMedProvider:
    """Search PubMed directly using official E-utilities endpoints."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
        now: Now | None = None,
    ) -> None:
        if not settings.can_search_live or settings.ncbi_email is None:
            raise ValueError("BIOPAPER_NCBI_EMAIL is required for PubMed search")
        self._email = settings.ncbi_email
        self._api_key = (
            settings.ncbi_api_key.get_secret_value()
            if settings.ncbi_api_key is not None
            else None
        )
        self._client = client
        self._clock = clock
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(UTC))
        self._minimum_interval = 1.0 / (10 if self._api_key else 3)
        self._last_request_at: float | None = None
        self._rate_lock = asyncio.Lock()

    async def search(self, plan: SearchPlan, limit: int) -> ProviderResult:
        """Return complete PubMed papers or sanitized visible failures."""
        if limit < 1:
            raise ValueError("limit must be positive")

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30.0)
        try:
            try:
                search_response = await self._esearch(client, plan, limit)
                identifiers = _parse_esearch(search_response.json())
                if not identifiers:
                    return _result(limit=limit)
                fetch_response = await self._efetch(client, identifiers)
            except httpx.HTTPStatusError as error:
                return _result(limit=limit, failure=_http_failure(error))
            except (httpx.TimeoutException, httpx.RequestError, ValueError) as error:
                return _result(
                    limit=limit,
                    failure=ProviderFailure(
                        source=SourceName.PUBMED,
                        code=ProviderFailureCode.SOURCE_UNAVAILABLE,
                        message=f"PubMed is unavailable: {type(error).__name__}",
                    ),
                )

            retrieved_at = self._now()
            digest = hashlib.sha256(fetch_response.content).hexdigest()
            papers, failures = _parse_and_map_articles(
                fetch_response.content, retrieved_at, digest
            )
            return ProviderResult(
                papers=papers,
                source_counts=(
                    SourceCount(
                        source=SourceName.PUBMED,
                        requested=limit,
                        returned=len(papers),
                    ),
                ),
                failures=failures,
            )
        finally:
            if owns_client:
                await client.aclose()

    async def _esearch(
        self, client: httpx.AsyncClient, plan: SearchPlan, limit: int
    ) -> httpx.Response:
        data = {
            "db": "pubmed",
            "term": plan.boolean_query,
            "retmode": "json",
            "retmax": str(limit),
            "tool": "BioPaperAI",
            "email": self._email,
        }
        await self._pace()
        if self._api_key is None:
            response = await client.get(ESEARCH_URL, params=data)
        else:
            response = await client.post(
                ESEARCH_URL, data={**data, "api_key": self._api_key}
            )
        response.raise_for_status()
        return response

    async def _efetch(
        self, client: httpx.AsyncClient, identifiers: tuple[str, ...]
    ) -> httpx.Response:
        data = {
            "db": "pubmed",
            "id": ",".join(identifiers),
            "retmode": "xml",
            "tool": "BioPaperAI",
            "email": self._email,
        }
        if self._api_key is not None:
            data["api_key"] = self._api_key
        await self._pace()
        response = await client.post(EFETCH_URL, data=data)
        response.raise_for_status()
        return response

    async def _pace(self) -> None:
        async with self._rate_lock:
            now = self._clock()
            if self._last_request_at is not None:
                delay = self._minimum_interval - (now - self._last_request_at)
                if delay > 0:
                    await self._sleep(delay)
                    now = self._clock()
            self._last_request_at = now


def _parse_esearch(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, Mapping):
        raise ValueError("invalid ESearch response")
    result = payload.get("esearchresult")
    if not isinstance(result, Mapping):
        raise ValueError("invalid ESearch response")
    raw_ids = result.get("idlist")
    if not isinstance(raw_ids, list) or not all(
        isinstance(item, str) for item in raw_ids
    ):
        raise ValueError("invalid ESearch identifiers")
    if any(not item.isdigit() for item in raw_ids):
        raise ValueError("invalid ESearch identifiers")
    return tuple(raw_ids)


def _parse_and_map_articles(
    xml: bytes, retrieved_at: datetime, response_sha256: str
) -> tuple[tuple[Paper, ...], tuple[ProviderFailure, ...]]:
    try:
        root = DefusedElementTree.fromstring(xml)
    except ParseError as error:
        raise ValueError("invalid PubMed XML") from error

    papers: list[Paper] = []
    failures: list[ProviderFailure] = []
    for article in root.findall("./PubmedArticle"):
        record = _article_record(article, response_sha256)
        record_id = record.get("pmid")
        try:
            papers.append(map_pubmed_record(record, retrieved_at))
        except ValueError:
            failures.append(
                ProviderFailure(
                    source=SourceName.PUBMED,
                    code=ProviderFailureCode.INVALID_RECORD,
                    message="PubMed returned an incomplete record",
                    record_id=record_id if isinstance(record_id, str) else None,
                )
            )
    return tuple(papers), tuple(failures)


def _article_record(article: Element, digest: str) -> dict[str, object]:
    pmid = _element_text(article.find("./MedlineCitation/PMID"))
    title = _element_text(article.find("./MedlineCitation/Article/ArticleTitle"))
    abstract_parts = [
        _element_text(element)
        for element in article.findall(
            "./MedlineCitation/Article/Abstract/AbstractText"
        )
    ]
    authors = tuple(
        name
        for author in article.findall("./MedlineCitation/Article/AuthorList/Author")
        if (name := _author_name(author)) is not None
    )
    identifiers = {
        element.attrib.get("IdType", "").casefold(): _element_text(element)
        for element in article.findall("./PubmedData/ArticleIdList/ArticleId")
    }
    return {
        "pmid": pmid,
        "title": title,
        "abstract": "\n".join(part for part in abstract_parts if part) or None,
        "authors": authors,
        "journal": _element_text(
            article.find("./MedlineCitation/Article/Journal/Title")
        ),
        "year": _publication_year(article),
        "publication_types": tuple(
            text
            for element in article.findall(
                "./MedlineCitation/Article/PublicationTypeList/PublicationType"
            )
            if (text := _element_text(element)) is not None
        ),
        "doi": identifiers.get("doi"),
        "pmcid": identifiers.get("pmc"),
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
        "response_sha256": digest,
    }


def _element_text(element: Element | None) -> str | None:
    if element is None:
        return None
    text = "".join(element.itertext()).strip()
    return text or None


def _author_name(author: Element) -> str | None:
    collective = _element_text(author.find("./CollectiveName"))
    if collective:
        return collective
    parts = (
        _element_text(author.find("./ForeName")),
        _element_text(author.find("./LastName")),
    )
    name = " ".join(part for part in parts if part)
    return name or None


def _publication_year(article: Element) -> int | None:
    year = _element_text(
        article.find("./MedlineCitation/Article/Journal/JournalIssue/PubDate/Year")
    )
    if year and year.isdigit():
        return int(year)
    medline_date = _element_text(
        article.find(
            "./MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate"
        )
    )
    match = re.search(r"\b(\d{4})\b", medline_date or "")
    return int(match.group(1)) if match else None


def _http_failure(error: httpx.HTTPStatusError) -> ProviderFailure:
    if error.response.status_code == 429:
        return ProviderFailure(
            source=SourceName.PUBMED,
            code=ProviderFailureCode.RATE_LIMITED,
            message="PubMed rate limit reached",
            retry_after_seconds=_retry_after(error.response.headers.get("Retry-After")),
        )
    return ProviderFailure(
        source=SourceName.PUBMED,
        code=ProviderFailureCode.SOURCE_UNAVAILABLE,
        message=f"PubMed returned HTTP {error.response.status_code}",
    )


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return max(parsed, 0.0)


def _result(*, limit: int, failure: ProviderFailure | None = None) -> ProviderResult:
    return ProviderResult(
        source_counts=(
            SourceCount(source=SourceName.PUBMED, requested=limit, returned=0),
        ),
        failures=(failure,) if failure is not None else (),
    )
