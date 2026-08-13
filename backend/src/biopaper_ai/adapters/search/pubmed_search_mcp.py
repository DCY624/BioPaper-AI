"""Adapter for the pinned pubmed-search-mcp Python SDK."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast

from pubmed_search import PubMedSearchClient, PubMedSearchConfig

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
from biopaper_ai.domain.search_plan import SearchFilters, SearchPlan


class UnifiedSearchResultView(Protocol):
    """Narrow portion of the upstream result consumed by the adapter."""

    @property
    def articles(self) -> list[dict[str, Any]]: ...

    @property
    def source_counts(self) -> list[dict[str, Any]]: ...


class UnifiedSearchClient(Protocol):
    """Narrow injected boundary around PubMedSearchClient."""

    async def unified_search(
        self,
        query: str,
        *,
        limit: int,
        sources: str,
        ranking: Literal["balanced"],
        output_format: Literal["json"],
        filters: str | None,
    ) -> UnifiedSearchResultView: ...


class Clock(Protocol):
    def __call__(self) -> datetime: ...


class PubMedSearchMcpProvider:
    """Translate the pinned SDK contract into application-owned models."""

    def __init__(
        self,
        client: UnifiedSearchClient,
        *,
        now: Clock | None = None,
    ) -> None:
        self._client = client
        self._now = now or (lambda: datetime.now(UTC))

    async def search(self, plan: SearchPlan, limit: int) -> ProviderResult:
        """Search only PubMed and sanitize all data at the adapter boundary."""
        if limit < 1:
            raise ValueError("limit must be positive")

        try:
            upstream = await self._client.unified_search(
                plan.boolean_query,
                limit=limit,
                sources="pubmed",
                ranking="balanced",
                output_format="json",
                filters=_serialize_filters(plan.filters),
            )
            raw_articles = upstream.articles
            # Access the pinned property inside the boundary even though canonical
            # returned counts are based on records that survived local validation.
            upstream.source_counts
        except Exception:
            return _unavailable_result(limit)

        retrieved_at = self._now()
        papers: list[Paper] = []
        failures: list[ProviderFailure] = []
        for raw_article in raw_articles:
            record_id = _candidate_pmid(raw_article)
            try:
                record = _article_record(raw_article)
                papers.append(map_pubmed_record(record, retrieved_at))
            except (TypeError, ValueError):
                failures.append(
                    ProviderFailure(
                        source=SourceName.PUBMED,
                        code=ProviderFailureCode.INVALID_RECORD,
                        message="PubMed returned an invalid record",
                        record_id=record_id,
                    )
                )

        return ProviderResult(
            papers=tuple(papers),
            source_counts=(
                SourceCount(
                    source=SourceName.PUBMED,
                    requested=limit,
                    returned=len(papers),
                ),
            ),
            failures=tuple(failures),
        )


def create_pubmed_search_mcp_provider(settings: Settings) -> PubMedSearchMcpProvider:
    """Build the SDK adapter, revealing a configured secret only to SDK config."""
    if settings.ncbi_email is None:
        raise ValueError("BIOPAPER_NCBI_EMAIL is required for PubMed search")
    config = PubMedSearchConfig(
        email=settings.ncbi_email,
        api_key=(
            settings.ncbi_api_key.get_secret_value()
            if settings.ncbi_api_key is not None
            else None
        ),
    )
    client = cast(UnifiedSearchClient, PubMedSearchClient(config))
    return PubMedSearchMcpProvider(client)


def _serialize_filters(filters: SearchFilters) -> str | None:
    parts: list[str] = []
    if filters.year_from is not None or filters.year_to is not None:
        lower = str(filters.year_from) if filters.year_from is not None else ""
        upper = str(filters.year_to) if filters.year_to is not None else ""
        if filters.year_from == filters.year_to:
            parts.append(f"year:{lower}")
        else:
            parts.append(f"year:{lower}-{upper}")
    parts.extend(f"species:{species.strip()}" for species in filters.species)
    return ", ".join(parts) or None


def _article_record(article: object) -> Mapping[str, object]:
    if not isinstance(article, Mapping):
        raise TypeError("article must be a mapping")
    if article.get("primary_source") != "pubmed":
        raise ValueError("record is not PubMed-backed")
    sources = article.get("sources")
    if not _has_pubmed_source(sources):
        raise ValueError("record lacks PubMed source provenance")

    identifiers = article.get("identifiers")
    urls = article.get("urls")
    if not isinstance(identifiers, Mapping) or not isinstance(urls, Mapping):
        raise ValueError("record lacks identifiers or URLs")
    pmid = _required_string(identifiers.get("pmid"))
    authors = _authors(article.get("authors"))
    article_type = article.get("article_type")
    publication_types: tuple[str, ...] = ()
    if article_type not in (None, "unknown"):
        publication_types = (_required_string(article_type),)
    return {
        "pmid": pmid,
        "title": article.get("title"),
        "authors": authors,
        "year": article.get("year"),
        "journal": article.get("journal"),
        "publication_types": publication_types,
        "abstract": article.get("abstract"),
        "doi": identifiers.get("doi"),
        "pmcid": identifiers.get("pmc"),
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    }


def _candidate_pmid(article: object) -> str | None:
    if not isinstance(article, Mapping):
        return None
    identifiers = article.get("identifiers")
    if not isinstance(identifiers, Mapping):
        return None
    value = identifiers.get("pmid")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _authors(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("authors must be a sequence")
    authors: list[str] = []
    for author in value:
        if not isinstance(author, Mapping):
            raise ValueError("author must be a mapping")
        authors.append(_required_string(author.get("name")))
    return tuple(authors)


def _has_pubmed_source(value: object) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return False
    return any(item == "pubmed" for item in value)


def _required_string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected a non-empty string")
    return value.strip()


def _unavailable_result(limit: int) -> ProviderResult:
    return ProviderResult(
        source_counts=(
            SourceCount(source=SourceName.PUBMED, requested=limit, returned=0),
        ),
        failures=(
            ProviderFailure(
                source=SourceName.PUBMED,
                code=ProviderFailureCode.SOURCE_UNAVAILABLE,
                message="PubMed SDK source is unavailable",
            ),
        ),
    )
