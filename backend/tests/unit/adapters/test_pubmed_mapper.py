from datetime import UTC, datetime

import pytest

from biopaper_ai.adapters.search.pubmed_mapper import map_pubmed_record
from biopaper_ai.domain.provenance import SourceName


def test_mapper_requires_truth_critical_fields() -> None:
    retrieved_at = datetime(2026, 8, 13, tzinfo=UTC)
    complete = {
        "pmid": "123",
        "title": "A real title",
        "url": "https://pubmed.ncbi.nlm.nih.gov/123/",
    }

    for missing, expected in (
        ("pmid", "PMID"),
        ("title", "title"),
        ("url", "provenance URL"),
    ):
        record = dict(complete)
        record.pop(missing)
        with pytest.raises(ValueError, match=expected):
            map_pubmed_record(record, retrieved_at)


def test_mapper_accepts_absent_optional_fields() -> None:
    retrieved_at = datetime(2026, 8, 13, tzinfo=UTC)

    paper = map_pubmed_record(
        {
            "pmid": "123",
            "title": "A real title",
            "url": "https://pubmed.ncbi.nlm.nih.gov/123/",
        },
        retrieved_at,
    )

    assert paper.identifiers.pmid == "123"
    assert paper.identifiers.doi is None
    assert paper.identifiers.pmcid is None
    assert paper.year is None
    assert paper.journal is None
    assert paper.abstract is None
    assert paper.provenance[0].source is SourceName.PUBMED
    assert paper.provenance[0].retrieved_at == retrieved_at


def test_mapper_rejects_invalid_optional_value_instead_of_guessing() -> None:
    with pytest.raises(ValueError, match="year"):
        map_pubmed_record(
            {
                "pmid": "123",
                "title": "A real title",
                "url": "https://pubmed.ncbi.nlm.nih.gov/123/",
                "year": "2024",
            },
            datetime(2026, 8, 13, tzinfo=UTC),
        )
