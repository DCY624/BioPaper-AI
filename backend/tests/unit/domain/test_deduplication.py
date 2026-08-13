from datetime import UTC, datetime

import pytest

from biopaper_ai.domain.deduplication import deduplicate_papers
from biopaper_ai.domain.paper import Paper, PaperIdentifiers
from biopaper_ai.domain.provenance import Provenance, SourceName


@pytest.mark.parametrize(
    ("first_ids", "second_ids"),
    [
        ({"doi": "10.1000/shared"}, {"doi": "https://doi.org/10.1000/SHARED"}),
        ({"pmid": "123"}, {"pmid": "123"}),
        ({"pmcid": "PMC456"}, {"pmcid": "456"}),
    ],
    ids=("doi", "pmid", "pmcid"),
)
def test_exact_strict_identifier_merges_papers(
    first_ids: dict[str, str], second_ids: dict[str, str]
) -> None:
    result = deduplicate_papers(
        [paper(record_id="first", **first_ids), paper(record_id="second", **second_ids)]
    )

    assert len(result.papers) == 1
    assert result.ambiguous == ()


def test_merge_preserves_every_provenance_record() -> None:
    first = provenance(SourceName.PUBMED, "123")
    second = provenance(SourceName.EUROPE_PMC, "MED:123")

    result = deduplicate_papers(
        [
            paper(doi="10.1000/shared", provenance_records=(first,)),
            paper(doi="10.1000/shared", provenance_records=(second,)),
        ]
    )

    assert result.papers[0].provenance == (first, second)


def test_merge_retains_longest_non_empty_abstract() -> None:
    result = deduplicate_papers(
        [
            paper(doi="10.1000/shared", abstract="Short."),
            paper(doi="10.1000/shared", abstract="A substantially longer abstract."),
        ]
    )

    assert result.papers[0].abstract == "A substantially longer abstract."


def test_deduplication_preserves_first_seen_order() -> None:
    result = deduplicate_papers(
        [
            paper(title="First", pmid="1", record_id="1"),
            paper(title="Second", pmid="2", record_id="2"),
            paper(title="First, enriched", pmid="1", record_id="3"),
            paper(title="Third", pmid="3", record_id="4"),
        ]
    )

    assert [item.title for item in result.papers] == ["First", "Second", "Third"]


def test_title_and_year_candidate_without_strict_ids_is_not_merged() -> None:
    result = deduplicate_papers(
        [
            paper(title="  Shared   Title ", year=2024, record_id="first"),
            paper(title="shared title", year=2024, record_id="second"),
        ]
    )

    assert len(result.papers) == 2
    assert len(result.ambiguous) == 1


def test_conflicting_ids_are_not_title_merged() -> None:
    result = deduplicate_papers(
        [
            paper(title="Same title", year=2024, doi="10.1000/a", pmid="1"),
            paper(title="Same title", year=2024, doi="10.1000/b", pmid="2"),
        ]
    )

    assert len(result.papers) == 2
    assert len(result.ambiguous) == 1
    assert result.ambiguous[0].papers == result.papers


def test_shared_identifier_does_not_override_conflicting_identifier() -> None:
    result = deduplicate_papers(
        [
            paper(title="Same title", doi="10.1000/a", pmid="1", record_id="first"),
            paper(title="Same title", doi="10.1000/a", pmid="2", record_id="second"),
        ]
    )

    assert len(result.papers) == 2
    assert len(result.ambiguous) == 1


def paper(
    *,
    title: str = "A paper",
    year: int | None = 2024,
    abstract: str | None = None,
    doi: str | None = None,
    pmid: str | None = None,
    pmcid: str | None = None,
    record_id: str = "123",
    provenance_records: tuple[Provenance, ...] | None = None,
) -> Paper:
    return Paper(
        title=title,
        year=year,
        abstract=abstract,
        identifiers=PaperIdentifiers(doi=doi, pmid=pmid, pmcid=pmcid),
        provenance=provenance_records
        if provenance_records is not None
        else (provenance(SourceName.PUBMED, record_id),),
    )


def provenance(source: SourceName, record_id: str) -> Provenance:
    return Provenance(
        source=source,
        record_id=record_id,
        url=f"https://example.test/{source}/{record_id}",
        retrieved_at=datetime(2026, 8, 12, tzinfo=UTC),
    )
