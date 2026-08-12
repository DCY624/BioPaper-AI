import pytest

from biopaper_ai.domain.identifiers import (
    normalize_doi,
    normalize_pmcid,
    normalize_pmid,
)


def test_doi_is_canonical() -> None:
    assert normalize_doi("https://doi.org/10.1000/ABC.1") == "10.1000/abc.1"


def test_invalid_pmid_is_rejected() -> None:
    with pytest.raises(ValueError, match="PMID"):
        normalize_pmid("AI-made-id")


def test_pmcid_is_prefixed() -> None:
    assert normalize_pmcid("123456") == "PMC123456"
