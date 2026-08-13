import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from biopaper_ai.adapters.search.native_pubmed import (
    EFETCH_URL,
    ESEARCH_URL,
    NativePubMedProvider,
)
from biopaper_ai.application.ports.search_provider import (
    ProviderFailureCode,
    ProviderResult,
)
from biopaper_ai.config import Settings
from biopaper_ai.domain.provenance import SourceName
from biopaper_ai.domain.search_plan import SearchFilters, SearchPlan, SynonymGroup

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_native_pubmed_offline_contract() -> None:
    search_fixture = json.loads((FIXTURES / "ncbi_esearch.json").read_text())
    fetch_fixture = (FIXTURES / "ncbi_efetch.xml").read_bytes()
    ticker = FakeTicker()

    with respx.mock(assert_all_called=True) as router:
        search_route = router.get(ESEARCH_URL).mock(
            return_value=httpx.Response(200, json=search_fixture)
        )
        fetch_route = router.post(EFETCH_URL).mock(
            return_value=httpx.Response(200, content=fetch_fixture)
        )
        async with httpx.AsyncClient() as client:
            result = await NativePubMedProvider(
                Settings(ncbi_email="maintainer@example.test"),
                client=client,
                clock=ticker.clock,
                sleep=ticker.sleep,
                now=lambda: datetime(2026, 8, 13, tzinfo=UTC),
            ).search(search_plan(), limit=2)

    request = search_route.calls[0].request
    assert request.url.params["tool"] == "BioPaperAI"
    assert request.url.params["email"] == "maintainer@example.test"
    assert request.url.params["retmode"] == "json"
    assert request.url.params["retmax"] == "2"
    assert request.url.params["term"] == search_plan().boolean_query
    fetch_form = parse_qs(fetch_route.calls[0].request.content.decode())
    assert fetch_form["id"] == ["10000001,10000002"]

    assert [paper.identifiers.pmid for paper in result.papers] == [
        "10000001",
        "10000002",
    ]
    assert result.papers[0].identifiers.pmcid == "PMC1000001"
    assert all(
        paper.provenance[0].source is SourceName.PUBMED for paper in result.papers
    )
    assert all(
        str(paper.provenance[0].url)
        == f"https://pubmed.ncbi.nlm.nih.gov/{paper.identifiers.pmid}/"
        for paper in result.papers
    )
    assert result.source_counts[0].returned == 2
    assert result.failures == ()
    assert ticker.delays == pytest.approx([1 / 3])


@pytest.mark.asyncio
async def test_rate_limit_failure_preserves_retry_after() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get(ESEARCH_URL).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "2.5"})
        )
        async with httpx.AsyncClient() as client:
            result = await NativePubMedProvider(
                Settings(ncbi_email="maintainer@example.test"), client=client
            ).search(search_plan(), limit=2)

    assert result.papers == ()
    assert result.failures[0].code is ProviderFailureCode.RATE_LIMITED
    assert result.failures[0].retry_after_seconds == 2.5


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [500, 503])
async def test_server_errors_become_source_unavailable(status_code: int) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get(ESEARCH_URL).mock(return_value=httpx.Response(status_code))
        async with httpx.AsyncClient() as client:
            result = await NativePubMedProvider(
                Settings(ncbi_email="maintainer@example.test"), client=client
            ).search(search_plan(), limit=2)

    assert result.failures[0].code is ProviderFailureCode.SOURCE_UNAVAILABLE


@pytest.mark.asyncio
async def test_timeout_becomes_source_unavailable() -> None:
    request = httpx.Request("GET", ESEARCH_URL)
    with respx.mock(assert_all_called=True) as router:
        router.get(ESEARCH_URL).mock(
            side_effect=httpx.ReadTimeout("late", request=request)
        )
        async with httpx.AsyncClient() as client:
            result = await NativePubMedProvider(
                Settings(ncbi_email="maintainer@example.test"), client=client
            ).search(search_plan(), limit=2)

    assert result.failures[0].code is ProviderFailureCode.SOURCE_UNAVAILABLE
    assert "late" not in result.failures[0].message


@pytest.mark.asyncio
async def test_api_key_uses_post_body_and_ten_request_rate() -> None:
    search_fixture = json.loads((FIXTURES / "ncbi_esearch.json").read_text())
    fetch_fixture = (FIXTURES / "ncbi_efetch.xml").read_bytes()
    ticker = FakeTicker()
    secret = "test-api-key-must-not-enter-url"

    with respx.mock(assert_all_called=True) as router:
        search_route = router.post(ESEARCH_URL).mock(
            return_value=httpx.Response(200, json=search_fixture)
        )
        fetch_route = router.post(EFETCH_URL).mock(
            return_value=httpx.Response(200, content=fetch_fixture)
        )
        async with httpx.AsyncClient() as client:
            await NativePubMedProvider(
                Settings(ncbi_email="maintainer@example.test", ncbi_api_key=secret),
                client=client,
                clock=ticker.clock,
                sleep=ticker.sleep,
            ).search(search_plan(), limit=2)

    assert secret not in str(search_route.calls[0].request.url)
    assert secret not in str(fetch_route.calls[0].request.url)
    search_form = parse_qs(search_route.calls[0].request.content.decode())
    fetch_form = parse_qs(fetch_route.calls[0].request.content.decode())
    assert search_form["api_key"] == [secret]
    assert fetch_form["api_key"] == [secret]
    assert ticker.delays == pytest.approx([0.1])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "xml",
    [
        b"<PubmedArticleSet><PubmedArticle>",
        (
            b'<!DOCTYPE PubmedArticleSet [<!ENTITY unsafe "content">]>'
            b"<PubmedArticleSet>&unsafe;</PubmedArticleSet>"
        ),
        b"<UnexpectedRoot />",
        b"<PubmedArticleSet />",
    ],
    ids=("truncated", "forbidden-entity", "wrong-root", "empty"),
)
async def test_invalid_or_empty_xml_becomes_sanitized_failure(xml: bytes) -> None:
    result = await search_with_fetch_xml(xml)

    assert result.papers == ()
    assert result.failures[0].code is ProviderFailureCode.SOURCE_UNAVAILABLE
    assert "xml" not in result.failures[0].message.casefold()


@pytest.mark.asyncio
async def test_missing_requested_pmid_is_visible_as_invalid_record() -> None:
    fetch_fixture = (FIXTURES / "ncbi_efetch.xml").read_text()
    second_start = fetch_fixture.rindex("  <PubmedArticle>")
    incomplete_fixture = (fetch_fixture[:second_start] + "</PubmedArticleSet>").encode()

    result = await search_with_fetch_xml(incomplete_fixture)

    assert [paper.identifiers.pmid for paper in result.papers] == ["10000001"]
    assert result.source_counts[0].returned == 1
    assert result.failures[0].code is ProviderFailureCode.INVALID_RECORD
    assert result.failures[0].record_id == "10000002"


@pytest.mark.asyncio
async def test_all_incomplete_articles_preserve_per_record_failures() -> None:
    incomplete_xml = b"""\
<PubmedArticleSet>
  <PubmedArticle><MedlineCitation><PMID>10000001</PMID></MedlineCitation></PubmedArticle>
  <PubmedArticle><MedlineCitation><PMID>10000002</PMID></MedlineCitation></PubmedArticle>
</PubmedArticleSet>
"""

    result = await search_with_fetch_xml(incomplete_xml)

    assert result.papers == ()
    assert [failure.code for failure in result.failures] == [
        ProviderFailureCode.INVALID_RECORD,
        ProviderFailureCode.INVALID_RECORD,
    ]
    assert [failure.record_id for failure in result.failures] == [
        "10000001",
        "10000002",
    ]


@pytest.mark.asyncio
async def test_unexpected_pmid_is_never_returned_as_a_paper() -> None:
    fetch_fixture = (FIXTURES / "ncbi_efetch.xml").read_bytes()
    inconsistent_xml = fetch_fixture.replace(b"10000002", b"99999999")

    result = await search_with_fetch_xml(inconsistent_xml)

    assert [paper.identifiers.pmid for paper in result.papers] == ["10000001"]
    assert {failure.record_id for failure in result.failures} == {
        "10000002",
        "99999999",
    }
    assert all(
        failure.code is ProviderFailureCode.INVALID_RECORD
        for failure in result.failures
    )


async def search_with_fetch_xml(xml: bytes) -> ProviderResult:
    search_fixture = json.loads((FIXTURES / "ncbi_esearch.json").read_text())
    with respx.mock(assert_all_called=True) as router:
        router.get(ESEARCH_URL).mock(
            return_value=httpx.Response(200, json=search_fixture)
        )
        router.post(EFETCH_URL).mock(return_value=httpx.Response(200, content=xml))
        async with httpx.AsyncClient() as client:
            return await NativePubMedProvider(
                Settings(ncbi_email="maintainer@example.test"), client=client
            ).search(search_plan(), limit=2)


def search_plan() -> SearchPlan:
    return SearchPlan.build(
        original_query="probiotics and gut barrier",
        topic="probiotics and gut barrier",
        groups=(
            SynonymGroup(terms=("probiotic", "Lactobacillus")),
            SynonymGroup(terms=("intestinal barrier",)),
        ),
        mesh_terms=(),
        filters=SearchFilters(),
        generator="deterministic",
    )


class FakeTicker:
    def __init__(self) -> None:
        self.current = 0.0
        self.delays: list[float] = []

    def clock(self) -> float:
        return self.current

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.current += delay
