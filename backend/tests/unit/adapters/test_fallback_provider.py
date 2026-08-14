import json
from datetime import UTC, datetime

import pytest
from pubmed_search import UnifiedSearchResult

from biopaper_ai.adapters.search.fallback import FallbackSearchProvider
from biopaper_ai.adapters.search.pubmed_search_mcp import PubMedSearchMcpProvider
from biopaper_ai.application.ports.search_provider import (
    ProviderFailure,
    ProviderFailureCode,
    ProviderResult,
    SourceCount,
)
from biopaper_ai.domain.paper import Paper, PaperIdentifiers
from biopaper_ai.domain.provenance import Provenance, SourceName
from biopaper_ai.domain.search_plan import SearchFilters, SearchPlan, SynonymGroup


class StubProvider:
    def __init__(self, result: ProviderResult | Exception) -> None:
        self.result = result
        self.calls = 0

    async def search(self, plan: SearchPlan, limit: int) -> ProviderResult:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class UnknownEmptySdkClient:
    async def unified_search(self, query: str, **kwargs: object) -> UnifiedSearchResult:
        payload = {
            "tool": "unified_search",
            "statistics": {"total_input": 0, "unique_articles": 0},
            "articles": [],
            "source_counts": [
                {
                    "source": "pubmed",
                    "returned": 0,
                    "total_available": None,
                    "has_more": False,
                }
            ],
            "next_tools": [],
            "next_commands": [],
        }
        return UnifiedSearchResult(raw=json.dumps(payload), output_format="json")


@pytest.mark.asyncio
async def test_non_empty_primary_returns_unchanged_without_fallback() -> None:
    primary_result = ProviderResult(papers=(paper("1"),))
    primary = StubProvider(primary_result)
    fallback = StubProvider(ProviderResult(papers=(paper("2"),)))

    result = await FallbackSearchProvider(primary, fallback).search(search_plan(), 5)

    assert result is primary_result
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_non_empty_primary_preserves_failure_without_fallback() -> None:
    failure = unavailable_failure()
    primary_result = ProviderResult(papers=(paper("1"),), failures=(failure,))
    fallback = StubProvider(ProviderResult(papers=(paper("2"),)))

    result = await FallbackSearchProvider(
        StubProvider(primary_result),
        fallback,
    ).search(search_plan(), 5)

    assert result is primary_result
    assert result.failures == (failure,)
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_source_unavailable_empty_primary_uses_fallback() -> None:
    failure = unavailable_failure()
    primary = StubProvider(ProviderResult(failures=(failure,)))
    fallback_result = ProviderResult(
        papers=(paper("2"),),
        source_counts=(SourceCount(source=SourceName.PUBMED, requested=5, returned=1),),
    )
    fallback = StubProvider(fallback_result)

    result = await FallbackSearchProvider(primary, fallback).search(search_plan(), 5)

    assert result.papers == fallback_result.papers
    assert result.source_counts == fallback_result.source_counts
    assert result.failures == (failure,)
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_valid_empty_primary_does_not_call_fallback() -> None:
    primary_result = ProviderResult(
        source_counts=(SourceCount(source=SourceName.PUBMED, requested=5, returned=0),)
    )
    fallback = StubProvider(ProviderResult(papers=(paper("2"),)))

    provider = FallbackSearchProvider(StubProvider(primary_result), fallback)

    result = await provider.search(search_plan(), 5)

    assert result is primary_result
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_unknown_empty_sdk_result_uses_composed_fallback() -> None:
    fallback_result = ProviderResult(
        papers=(paper("2"),),
        source_counts=(SourceCount(source=SourceName.PUBMED, requested=5, returned=1),),
    )
    fallback = StubProvider(fallback_result)
    provider = FallbackSearchProvider(
        PubMedSearchMcpProvider(UnknownEmptySdkClient()),
        fallback,
    )

    result = await provider.search(search_plan(), 5)

    assert result.papers == fallback_result.papers
    assert result.source_counts == fallback_result.source_counts
    assert result.failures[0].code is ProviderFailureCode.SOURCE_UNAVAILABLE
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_raised_primary_exception_is_sanitized() -> None:
    secret = "raised-primary-secret"
    fallback_result = ProviderResult(papers=(paper("2"),))

    result = await FallbackSearchProvider(
        StubProvider(RuntimeError(f"failure contains {secret}")),
        StubProvider(fallback_result),
    ).search(search_plan(), 5)

    assert result.papers == fallback_result.papers
    assert result.failures[0].code is ProviderFailureCode.SOURCE_UNAVAILABLE
    assert secret not in result.failures[0].message
    assert "RuntimeError" not in result.failures[0].message


def unavailable_failure() -> ProviderFailure:
    return ProviderFailure(
        source=SourceName.PUBMED,
        code=ProviderFailureCode.SOURCE_UNAVAILABLE,
        message="Primary PubMed source is unavailable",
    )


def paper(pmid: str) -> Paper:
    return Paper(
        title=f"Paper {pmid}",
        identifiers=PaperIdentifiers(pmid=pmid),
        provenance=(
            Provenance(
                source=SourceName.PUBMED,
                record_id=pmid,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                retrieved_at=datetime(2026, 8, 13, tzinfo=UTC),
            ),
        ),
    )


def search_plan() -> SearchPlan:
    return SearchPlan.build(
        original_query="test",
        topic="test",
        groups=(SynonymGroup(terms=("test",)),),
        mesh_terms=(),
        filters=SearchFilters(),
        generator="deterministic",
    )
