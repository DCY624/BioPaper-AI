from datetime import UTC, datetime

import pytest

from biopaper_ai.domain.paper import Paper, PaperIdentifiers
from biopaper_ai.domain.provenance import Provenance, SourceName
from biopaper_ai.domain.search_plan import SearchFilters, SearchPlan, SynonymGroup


def test_paper_requires_database_provenance() -> None:
    with pytest.raises(ValueError, match="provenance"):
        Paper(title="Invented paper", provenance=())


def test_search_plan_builds_boolean_query_locally() -> None:
    plan = SearchPlan.build(
        original_query="益生菌改善肠道屏障",
        topic="probiotics and intestinal barrier",
        groups=(
            SynonymGroup(terms=("probiotic", "Lactobacillus")),
            SynonymGroup(terms=("intestinal barrier", "tight junction")),
        ),
        mesh_terms=("Probiotics",),
        filters=SearchFilters(year_from=2021, year_to=2026),
        generator="deterministic",
    )

    assert plan.boolean_query == (
        '(probiotic OR Lactobacillus) AND ("intestinal barrier" OR "tight junction")'
    )


def test_paper_primary_id_prefers_canonical_doi() -> None:
    paper = Paper(
        title="A real paper",
        identifiers=PaperIdentifiers(doi="https://doi.org/10.1000/ABC.1", pmid="42"),
        provenance=(provenance(),),
    )

    assert paper.primary_id == "doi:10.1000/abc.1"


def test_paper_primary_id_uses_source_record_when_no_database_id_exists() -> None:
    paper = Paper(
        title="A real paper",
        provenance=(provenance(record_id="W123"),),
    )

    assert paper.primary_id == "pubmed:W123"


def test_synonym_group_quotes_and_escapes_multiword_terms() -> None:
    group = SynonymGroup(terms=("intestinal barrier", 'tight "junction"'))

    assert group.boolean_clause == '("intestinal barrier" OR "tight \\"junction\\"")'


def test_search_plan_rejects_empty_groups() -> None:
    with pytest.raises(ValueError, match="group"):
        SearchPlan.build(
            original_query="probiotics",
            topic="probiotics",
            groups=(),
            mesh_terms=(),
            filters=SearchFilters(),
            generator="deterministic",
        )


def test_search_plan_rejects_a_public_boolean_query_inconsistent_with_groups() -> None:
    with pytest.raises(ValueError, match="boolean_query"):
        SearchPlan(
            original_query="probiotics",
            topic="probiotics",
            groups=(SynonymGroup(terms=("probiotic",)),),
            mesh_terms=(),
            filters=SearchFilters(),
            generator="deterministic",
            boolean_query="malicious external query",
        )


def test_synonym_group_strips_terms_and_rejects_whitespace_only_term() -> None:
    assert SynonymGroup(terms=("  probiotic  ",)).boolean_clause == "(probiotic)"

    with pytest.raises(ValueError, match="blank"):
        SynonymGroup(terms=("   ",))


def test_synonym_group_quotes_and_escapes_single_word_terms_containing_quotes() -> None:
    group = SynonymGroup(terms=('foo"bar',))

    assert group.boolean_clause == '("foo\\"bar")'


@pytest.mark.parametrize("year", [-1, "2024", 2024.0])
def test_search_filters_requires_strict_positive_integer_years(year: object) -> None:
    with pytest.raises(ValueError, match="year"):
        SearchFilters(year_from=year)


def provenance(record_id: str = "123") -> Provenance:
    return Provenance(
        source=SourceName.PUBMED,
        record_id=record_id,
        url="https://pubmed.ncbi.nlm.nih.gov/123/",
        retrieved_at=datetime(2026, 8, 12, tzinfo=UTC),
    )
