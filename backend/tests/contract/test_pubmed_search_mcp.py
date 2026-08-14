import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pubmed_search import UnifiedSearchResult

from biopaper_ai.adapters.search.pubmed_search_mcp import (
    PubMedSearchMcpProvider,
    create_pubmed_search_mcp_provider,
)
from biopaper_ai.application.ports.search_provider import (
    ProviderFailure,
    ProviderFailureCode,
)
from biopaper_ai.config import Settings
from biopaper_ai.domain.provenance import SourceName
from biopaper_ai.domain.search_plan import SearchFilters, SearchPlan, SynonymGroup

FIXTURES = Path(__file__).parent / "fixtures"


class FakeUnifiedResult:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.structured = dict(payload)
        self.articles = list(payload["articles"])
        self.source_counts = list(payload["source_counts"])


FakeSdkResult = FakeUnifiedResult | UnifiedSearchResult


class FakePubMedSearchClient:
    def __init__(self, result: FakeSdkResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def unified_search(self, query: str, **kwargs: object) -> FakeSdkResult:
        self.calls.append((query, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.asyncio
async def test_pinned_sdk_contract_maps_only_truth_backed_pubmed_records() -> None:
    payload = json.loads((FIXTURES / "pubmed_search_mcp_result.json").read_text())
    client = FakePubMedSearchClient(FakeUnifiedResult(payload))
    provider = PubMedSearchMcpProvider(
        client,
        now=lambda: datetime(2026, 8, 13, tzinfo=UTC),
    )

    result = await provider.search(filtered_search_plan(), limit=7)

    assert client.calls == [
        (
            filtered_search_plan().boolean_query,
            {
                "limit": 7,
                "sources": "pubmed",
                "ranking": "balanced",
                "output_format": "json",
                "filters": "year:2020-2025, species:humans",
            },
        )
    ]
    assert [paper.identifiers.pmid for paper in result.papers] == ["41000001"]
    assert result.papers[0].identifiers.doi == "10.1000/example.1"
    assert result.papers[0].identifiers.pmcid == "PMC4100001"
    assert result.papers[0].provenance[0].source is SourceName.PUBMED
    assert result.papers[0].provenance[0].record_id == "41000001"
    assert str(result.papers[0].provenance[0].url) == (
        "https://pubmed.ncbi.nlm.nih.gov/41000001/"
    )
    assert result.source_counts[0].requested == 7
    assert result.source_counts[0].returned == 1
    assert result.failures[0].code is ProviderFailureCode.INVALID_RECORD
    assert result.failures[0].record_id is None


@pytest.mark.asyncio
async def test_upstream_exception_is_sanitized() -> None:
    secret = "api-secret-must-not-escape"
    client = FakePubMedSearchClient(RuntimeError(f"upstream failed with {secret}"))

    result = await PubMedSearchMcpProvider(client).search(filtered_search_plan(), 2)

    assert result.papers == ()
    assert result.failures[0].code is ProviderFailureCode.SOURCE_UNAVAILABLE
    assert secret not in result.failures[0].message
    assert "RuntimeError" not in result.failures[0].message


@pytest.mark.asyncio
async def test_unknown_empty_sdk_result_is_sanitized_as_unavailable() -> None:
    client = FakePubMedSearchClient(empty_sdk_result(total_available=None))

    result = await PubMedSearchMcpProvider(client).search(filtered_search_plan(), 2)

    assert result.papers == ()
    assert [failure.code for failure in result.failures] == [
        ProviderFailureCode.SOURCE_UNAVAILABLE
    ]
    assert all(
        failure.message == "PubMed SDK source is unavailable"
        for failure in result.failures
    )


@pytest.mark.asyncio
async def test_confirmed_empty_sdk_result_remains_a_valid_empty_result() -> None:
    client = FakePubMedSearchClient(empty_sdk_result(total_available=0))

    result = await PubMedSearchMcpProvider(client).search(filtered_search_plan(), 2)

    assert result.papers == ()
    assert result.source_counts[0].returned == 0
    assert result.failures == ()


@pytest.mark.asyncio
async def test_explicit_sdk_source_error_is_sanitized_as_unavailable() -> None:
    secret = "low-level-transport-secret-must-not-escape"
    client = FakePubMedSearchClient(
        empty_sdk_result(
            total_available=0,
            source_errors=[
                {
                    "source": "pubmed",
                    "status": "error",
                    "message": secret,
                }
            ],
        )
    )

    result = await PubMedSearchMcpProvider(client).search(filtered_search_plan(), 2)

    assert [failure.code for failure in result.failures] == [
        ProviderFailureCode.SOURCE_UNAVAILABLE
    ]
    assert secret not in repr(result.failures)


@pytest.mark.asyncio
async def test_valid_sdk_articles_preserve_a_sanitized_partial_failure() -> None:
    secret = "partial-transport-secret-must-not-escape"
    payload = json.loads((FIXTURES / "pubmed_search_mcp_result.json").read_text())
    payload["articles"] = [payload["articles"][0]]
    payload["source_counts"][0]["returned"] = 1
    payload["source_errors"] = [
        {
            "source": "pubmed",
            "operation": "search",
            "message": f"TimeoutError carried {secret}",
            "kind": "timeout",
            "retryable": True,
            "status": "error",
        }
    ]
    client = FakePubMedSearchClient(
        UnifiedSearchResult(raw=json.dumps(payload), output_format="json")
    )

    result = await PubMedSearchMcpProvider(client).search(filtered_search_plan(), 2)

    assert [paper.identifiers.pmid for paper in result.papers] == ["41000001"]
    assert len(result.failures) == 1
    assert type(result.failures[0]) is ProviderFailure
    assert result.failures[0].code is ProviderFailureCode.SOURCE_UNAVAILABLE
    assert result.failures[0].message == "PubMed SDK source is unavailable"
    assert secret not in repr(result)
    assert "TimeoutError" not in repr(result)


def test_factory_extracts_settings_at_sdk_config_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class CapturingConfig:
        def __init__(self, *, email: str, api_key: str | None) -> None:
            captured.update(email=email, api_key=api_key)

    class CapturingClient:
        def __init__(self, config: object) -> None:
            captured["config"] = config

    monkeypatch.setattr(
        "biopaper_ai.adapters.search.pubmed_search_mcp.PubMedSearchConfig",
        CapturingConfig,
    )
    monkeypatch.setattr(
        "biopaper_ai.adapters.search.pubmed_search_mcp.PubMedSearchClient",
        CapturingClient,
    )
    secret = "factory-boundary-secret"

    provider = create_pubmed_search_mcp_provider(
        Settings(ncbi_email="maintainer@example.test", ncbi_api_key=secret)
    )

    assert isinstance(provider, PubMedSearchMcpProvider)
    assert captured["email"] == "maintainer@example.test"
    assert captured["api_key"] == secret
    assert secret not in repr(provider)


def filtered_search_plan() -> SearchPlan:
    return SearchPlan.build(
        original_query="probiotics and gut barrier",
        topic="probiotics and gut barrier",
        groups=(
            SynonymGroup(terms=("probiotic", "Lactobacillus")),
            SynonymGroup(terms=("intestinal barrier",)),
        ),
        mesh_terms=(),
        filters=SearchFilters(year_from=2020, year_to=2025, species=("humans",)),
        generator="deterministic",
    )


def empty_sdk_result(
    *,
    total_available: int | None,
    source_errors: list[dict[str, object]] | None = None,
) -> UnifiedSearchResult:
    payload = {
        "tool": "unified_search",
        "statistics": {"total_input": 0, "unique_articles": 0},
        "articles": [],
        "source_counts": [
            {
                "source": "pubmed",
                "returned": 0,
                "total_available": total_available,
                "has_more": False,
            }
        ],
        "next_tools": [],
        "next_commands": [],
    }
    if source_errors is not None:
        payload["source_errors"] = source_errors
    return UnifiedSearchResult(raw=json.dumps(payload), output_format="json")
