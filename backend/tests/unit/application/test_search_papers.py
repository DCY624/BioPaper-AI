from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from biopaper_ai.application.ports.search_provider import (
    ProviderFailure,
    ProviderFailureCode,
    ProviderResult,
    SourceCount,
)
from biopaper_ai.application.search_papers import (
    SearchPapers,
    SearchRun,
    paper_matches_filters,
)
from biopaper_ai.domain.paper import Paper, PaperIdentifiers
from biopaper_ai.domain.provenance import Provenance, SourceName
from biopaper_ai.domain.search_plan import SearchFilters, SearchPlan, SynonymGroup

EXECUTED_AT = datetime(2026, 8, 13, 9, 30, tzinfo=UTC)


class RecordingProvider:
    def __init__(self, result: ProviderResult) -> None:
        self.result = result
        self.received_plan: SearchPlan | None = None
        self.received_limit: int | None = None

    async def search(self, plan: SearchPlan, limit: int) -> ProviderResult:
        self.received_plan = plan
        self.received_limit = limit
        return self.result


@pytest.mark.asyncio
async def test_execute_sends_the_reviewed_plan_and_limit_to_the_provider() -> None:
    plan = search_plan()
    count = SourceCount(source=SourceName.PUBMED, requested=12, returned=0)
    provider = RecordingProvider(ProviderResult(source_counts=(count,)))

    run = await SearchPapers(provider=provider, clock=lambda: EXECUTED_AT).execute(
        plan, limit=12
    )

    assert provider.received_plan is plan
    assert provider.received_limit == 12
    assert run.plan is plan
    assert run.source_counts == (count,)


@pytest.mark.asyncio
async def test_only_populated_year_species_and_study_type_filters_apply() -> None:
    filters = SearchFilters(
        year_from=2021,
        year_to=2025,
        species=("humans",),
        study_types=("randomized controlled trial",),
    )
    qualifying = paper(
        "qualifying",
        title="Probiotic intervention in humans",
        year=2024,
        publication_types=("Randomized Controlled Trial",),
    )
    result = ProviderResult(
        papers=(
            qualifying,
            paper(
                "too-old",
                title="Probiotic intervention in humans",
                year=2020,
                publication_types=("Randomized Controlled Trial",),
            ),
            paper(
                "wrong-species",
                title="Probiotic intervention in mice",
                year=2024,
                publication_types=("Randomized Controlled Trial",),
            ),
            paper(
                "wrong-type",
                title="Probiotic intervention in humans",
                year=2024,
                publication_types=("Observational Study",),
            ),
            paper("missing-metadata", title="Probiotic intervention"),
        )
    )

    run = await execute(result, search_plan(filters=filters))

    assert tuple(hit.paper for hit in run.hits) == (qualifying,)


def test_unpopulated_filters_do_not_reject_missing_metadata() -> None:
    metadata_free = paper("metadata-free", year=None, abstract=None)

    assert paper_matches_filters(metadata_free, SearchFilters())


@pytest.mark.parametrize(
    ("paper_kwargs", "filters", "expected"),
    [
        (
            {"title": "Effects in adult humans"},
            SearchFilters(species=("humans",)),
            True,
        ),
        (
            {"abstract": "The cohort included humans."},
            SearchFilters(species=("humans",)),
            True,
        ),
        (
            {"publication_types": ("Humans",)},
            SearchFilters(species=("humans",)),
            True,
        ),
        (
            {"title": "Probiotic metabolism", "abstract": None},
            SearchFilters(species=("humans",)),
            False,
        ),
        (
            {"title": "A study in humanized mice"},
            SearchFilters(species=("humans",)),
            False,
        ),
        (
            {"publication_types": ("Clinical Trial",)},
            SearchFilters(study_types=("clinical trial",)),
            True,
        ),
        (
            {"abstract": "This randomized controlled trial enrolled 40."},
            SearchFilters(study_types=("randomized controlled trial",)),
            True,
        ),
        (
            {"publication_types": ()},
            SearchFilters(study_types=("clinical trial",)),
            False,
        ),
    ],
    ids=(
        "species-in-title",
        "species-in-abstract",
        "species-in-publication-type",
        "missing-species-evidence",
        "no-species-stemming",
        "study-type-metadata",
        "study-type-text",
        "missing-study-type-evidence",
    ),
)
def test_species_and_study_type_filters_require_literal_metadata_evidence(
    paper_kwargs: dict[str, object], filters: SearchFilters, expected: bool
) -> None:
    candidate = paper("candidate", **paper_kwargs)
    assert paper_matches_filters(candidate, filters) is expected


@pytest.mark.asyncio
async def test_doi_duplicates_merge_and_ambiguous_title_matches_remain_visible() -> (
    None
):
    pubmed = paper(
        "pubmed",
        title="Shared DOI record",
        doi="10.1000/shared",
        source=SourceName.PUBMED,
        abstract="Short.",
    )
    europe_pmc = paper(
        "europe-pmc",
        title="Enriched DOI record",
        doi="https://doi.org/10.1000/SHARED",
        source=SourceName.EUROPE_PMC,
        abstract="A substantially longer abstract about probiotics.",
    )
    ambiguous_first = paper("ambiguous-first", title="Same title", year=2023, pmid="1")
    ambiguous_second = paper(
        "ambiguous-second", title=" same   title ", year=2023, pmid="2"
    )

    run = await execute(
        ProviderResult(papers=(pubmed, europe_pmc, ambiguous_first, ambiguous_second))
    )

    merged = next(hit.paper for hit in run.hits if hit.paper.identifiers.doi)
    assert merged.provenance == (*pubmed.provenance, *europe_pmc.provenance)
    assert merged.abstract == "A substantially longer abstract about probiotics."
    assert len(run.hits) == 3
    assert len(run.ambiguous_matches) == 1
    assert run.ambiguous_matches[0].papers == (ambiguous_first, ambiguous_second)


@pytest.mark.asyncio
async def test_filtering_a_doi_merge_uses_metadata_from_every_safe_duplicate() -> None:
    incomplete = paper(
        "incomplete",
        title="Probiotic intervention",
        year=None,
        doi="10.1000/shared",
    )
    qualifying = paper(
        "qualifying",
        title="Probiotic intervention in humans",
        year=2024,
        publication_types=("Randomized Controlled Trial",),
        doi="10.1000/shared",
        source=SourceName.EUROPE_PMC,
    )
    filters = SearchFilters(
        year_from=2020,
        species=("humans",),
        study_types=("randomized controlled trial",),
    )

    run = await execute(
        ProviderResult(papers=(incomplete, qualifying)),
        search_plan(filters=filters),
    )

    assert len(run.hits) == 1
    assert run.hits[0].paper.provenance == (
        *incomplete.provenance,
        *qualifying.provenance,
    )
    assert run.hits[0].paper.title == qualifying.title
    assert run.hits[0].paper.year == 2024
    assert run.hits[0].paper.publication_types == ("Randomized Controlled Trial",)
    assert run.hits[0].ranking_reasons[-1] == "publication year: 2024"


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1])
async def test_invalid_limit_is_rejected_before_clock_or_provider(limit: int) -> None:
    provider = RecordingProvider(ProviderResult())
    clock_called = False

    def clock() -> datetime:
        nonlocal clock_called
        clock_called = True
        return EXECUTED_AT

    with pytest.raises(ValueError, match="limit"):
        await SearchPapers(provider=provider, clock=clock).execute(search_plan(), limit)

    assert provider.received_plan is None
    assert provider.received_limit is None
    assert clock_called is False


@pytest.mark.asyncio
async def test_partial_provider_failures_remain_visible() -> None:
    failure = ProviderFailure(
        source=SourceName.EUROPE_PMC,
        code=ProviderFailureCode.RATE_LIMITED,
        message="Europe PMC request was rate limited",
        retry_after_seconds=2,
    )

    run = await execute(ProviderResult(papers=(paper("1"),), failures=(failure,)))

    assert run.failures == (failure,)
    assert len(run.hits) == 1


@pytest.mark.asyncio
async def test_ranking_is_lexicographic_explainable_and_stable() -> None:
    result = ProviderResult(
        papers=(
            paper("title-old", title="Probiotic outcomes", year=2020),
            paper(
                "abstract-new",
                title="Microbial outcomes",
                abstract="A probiotic was administered.",
                year=2025,
            ),
            paper(
                "both-old",
                title="Probiotic trial",
                abstract="The probiotic arm improved.",
                year=2019,
            ),
            paper("neither-new", title="Microbial outcomes", year=2026),
            paper("title-new-first", title="Probiotic response", year=2024),
            paper("title-new-second", title="Probiotic safety", year=2024),
        )
    )

    run = await execute(result)

    assert [hit.paper.provenance[0].record_id for hit in run.hits] == [
        "both-old",
        "title-new-first",
        "title-new-second",
        "title-old",
        "abstract-new",
        "neither-new",
    ]
    assert run.hits[0].ranking_reasons == (
        "title term match: probiotic",
        "abstract term match: probiotic",
        "publication year: 2019",
    )
    assert run.hits[-1].ranking_reasons == (
        "title term match: none",
        "abstract term match: none",
        "publication year: 2026",
    )


@pytest.mark.asyncio
async def test_run_id_is_reproducible_and_run_is_immutable_and_exportable() -> None:
    plan = search_plan()
    run = await execute(ProviderResult(papers=(paper("1"),)), plan)
    repeated = await execute(ProviderResult(papers=(paper("1"),)), plan)

    assert run.run_id == UUID("bd9644bd-b694-565c-9320-603a18a48914")
    assert repeated.run_id == run.run_id
    assert run.executed_at == EXECUTED_AT
    assert run.model_dump(mode="json")["run_id"] == str(run.run_id)
    with pytest.raises(ValidationError, match="frozen"):
        run.hits = cast(object, ())


async def execute(result: ProviderResult, plan: SearchPlan | None = None) -> SearchRun:
    provider = RecordingProvider(result)
    return await SearchPapers(provider=provider, clock=lambda: EXECUTED_AT).execute(
        plan or search_plan(), limit=20
    )


def search_plan(filters: SearchFilters | None = None) -> SearchPlan:
    return SearchPlan.build(
        original_query="probiotics",
        topic="probiotics",
        groups=(SynonymGroup(terms=("probiotic",)),),
        mesh_terms=("Probiotics",),
        filters=filters or SearchFilters(),
        generator="deterministic",
    )


def paper(
    record_id: str,
    *,
    title: str = "A paper",
    year: int | None = None,
    abstract: str | None = None,
    publication_types: tuple[str, ...] = (),
    doi: str | None = None,
    pmid: str | None = None,
    source: SourceName = SourceName.PUBMED,
) -> Paper:
    return Paper(
        title=title,
        year=year,
        abstract=abstract,
        publication_types=publication_types,
        identifiers=PaperIdentifiers(doi=doi, pmid=pmid),
        provenance=(
            Provenance(
                source=source,
                record_id=record_id,
                url=f"https://example.test/{source}/{record_id}",
                retrieved_at=EXECUTED_AT,
            ),
        ),
    )
