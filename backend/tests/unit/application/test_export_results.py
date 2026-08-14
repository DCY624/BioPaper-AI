import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from biopaper_ai.application.export_results import export_search_run
from biopaper_ai.application.ports.search_provider import (
    ProviderFailure,
    ProviderFailureCode,
    SourceCount,
)
from biopaper_ai.application.search_papers import SearchHit, SearchRun
from biopaper_ai.domain.deduplication import AmbiguousMatch
from biopaper_ai.domain.paper import Paper, PaperIdentifiers
from biopaper_ai.domain.provenance import Provenance, SourceName
from biopaper_ai.domain.search_plan import SearchFilters, SearchPlan, SynonymGroup

EXECUTED_AT = datetime(2026, 8, 14, 10, 30, tzinfo=UTC)
FAKE_NCBI_SECRET = "fake-ncbi-secret-never-export"
FAKE_OPENAI_SECRET = "fake-openai-secret-never-export"


def test_json_export_contains_auditable_search_values_without_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIOPAPER_NCBI_API_KEY", FAKE_NCBI_SECRET)
    monkeypatch.setenv("BIOPAPER_OPENAI_API_KEY", FAKE_OPENAI_SECRET)
    destination = tmp_path / "nested" / "results.json"

    result = export_search_run(search_run(), "json", destination)

    assert result == destination
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["plan"]["boolean_query"] == "(probiotic)"
    assert payload["hits"][0]["paper"]["identifiers"] == {
        "doi": "10.1000/example",
        "pmid": "12345",
        "pmcid": "PMC6789",
        "openalex_id": None,
    }
    assert payload["hits"][0]["paper"]["provenance"][0]["url"] == (
        "https://pubmed.ncbi.nlm.nih.gov/12345/"
    )
    assert payload["failures"][0]["code"] == "rate_limited"
    assert payload["ambiguous_matches"][0]["papers"][1]["identifiers"]["pmid"] == (
        "54321"
    )
    exported = destination.read_text(encoding="utf-8")
    assert FAKE_NCBI_SECRET not in exported
    assert FAKE_OPENAI_SECRET not in exported
    assert list(destination.parent.glob(f".{destination.name}.*.tmp")) == []


def test_csv_export_has_bom_required_columns_and_provenance_without_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIOPAPER_NCBI_API_KEY", FAKE_NCBI_SECRET)
    monkeypatch.setenv("BIOPAPER_OPENAI_API_KEY", FAKE_OPENAI_SECRET)
    destination = tmp_path / "results.csv"

    export_search_run(search_run(), "csv", destination)

    assert destination.read_bytes().startswith(b"\xef\xbb\xbf")
    with destination.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        assert {
            "pmid",
            "pmcid",
            "doi",
            "title",
            "year",
            "journal",
            "abstract",
            "source_names",
            "source_urls",
        }.issubset(reader.fieldnames or ())
        rows = list(reader)
    paper_rows = [row for row in rows if row["row_type"] == "paper"]
    assert len(paper_rows) == 1
    paper_row = paper_rows[0]
    assert {
        key: paper_row[key]
        for key in (
            "pmid",
            "pmcid",
            "doi",
            "title",
            "year",
            "journal",
            "abstract",
            "source_names",
            "source_urls",
        )
    } == {
        "pmid": "12345",
        "pmcid": "PMC6789",
        "doi": "10.1000/example",
        "title": "Probiotic outcomes",
        "year": "2025",
        "journal": "Journal of Tests",
        "abstract": "A probiotic improved outcomes.",
        "source_names": "pubmed|pmc",
        "source_urls": (
            "https://pubmed.ncbi.nlm.nih.gov/12345/|"
            "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6789/"
        ),
    }
    exported = destination.read_text(encoding="utf-8-sig")
    assert FAKE_NCBI_SECRET not in exported
    assert FAKE_OPENAI_SECRET not in exported


def test_csv_export_preserves_partial_failure_and_run_level_audit(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "partial.csv"

    export_search_run(search_run(), "csv", destination)

    with destination.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows_by_type = {row["row_type"]: row for row in rows}
    assert set(rows_by_type) == {
        "paper",
        "source_count",
        "failure",
        "ambiguity",
    }
    assert all(row["run_id"] == "12345678-1234-5678-9234-567812345678" for row in rows)
    assert rows_by_type["paper"]["ranking_reasons"] == ("title term match: probiotic")
    assert {
        key: rows_by_type["source_count"][key]
        for key in ("audit_source", "requested_count", "returned_count")
    } == {
        "audit_source": "pubmed",
        "requested_count": "10",
        "returned_count": "1",
    }
    assert {
        key: rows_by_type["failure"][key]
        for key in (
            "audit_source",
            "failure_code",
            "failure_message",
            "retry_after_seconds",
        )
    } == {
        "audit_source": "pmc",
        "failure_code": "rate_limited",
        "failure_message": "PMC request was rate limited",
        "retry_after_seconds": "2",
    }
    assert {
        key: rows_by_type["ambiguity"][key]
        for key in (
            "ambiguous_title",
            "ambiguous_year",
            "ambiguous_paper_ids",
            "conflicting_identifier_types",
        )
    } == {
        "ambiguous_title": "same title",
        "ambiguous_year": "2025",
        "ambiguous_paper_ids": "pmid:11111|pmid:54321",
        "conflicting_identifier_types": "pmid",
    }


def test_export_rejects_unknown_format_without_replacing_destination(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "results.txt"
    destination.write_text("keep me", encoding="utf-8")

    with pytest.raises(ValueError, match="format"):
        export_search_run(search_run(), "yaml", destination)

    assert destination.read_text(encoding="utf-8") == "keep me"


def search_run() -> SearchRun:
    primary = paper(
        "12345",
        title="Probiotic outcomes",
        pmid="12345",
        pmcid="PMC6789",
        doi="10.1000/example",
        provenance=(
            provenance(
                SourceName.PUBMED,
                "12345",
                "https://pubmed.ncbi.nlm.nih.gov/12345/",
            ),
            provenance(
                SourceName.PMC,
                "PMC6789",
                "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6789/",
            ),
        ),
    )
    ambiguous_first = paper("11111", title="Same title", pmid="11111")
    ambiguous_second = paper("54321", title="Same title", pmid="54321")
    return SearchRun(
        run_id=UUID("12345678-1234-5678-9234-567812345678"),
        executed_at=EXECUTED_AT,
        plan=SearchPlan.build(
            original_query="probiotic",
            topic="probiotic",
            groups=(SynonymGroup(terms=("probiotic",)),),
            mesh_terms=("Probiotics",),
            filters=SearchFilters(year_from=2020),
            generator="deterministic",
        ),
        hits=(
            SearchHit(
                paper=primary,
                ranking_reasons=("title term match: probiotic",),
            ),
        ),
        source_counts=(
            SourceCount(source=SourceName.PUBMED, requested=10, returned=1),
        ),
        failures=(
            ProviderFailure(
                source=SourceName.PMC,
                code=ProviderFailureCode.RATE_LIMITED,
                message="PMC request was rate limited",
                retry_after_seconds=2,
            ),
        ),
        ambiguous_matches=(
            AmbiguousMatch(
                normalized_title="same title",
                year=2025,
                papers=(ambiguous_first, ambiguous_second),
                conflicting_identifier_types=("pmid",),
            ),
        ),
    )


def paper(
    record_id: str,
    *,
    title: str,
    pmid: str,
    pmcid: str | None = None,
    doi: str | None = None,
    provenance: tuple[Provenance, ...] | None = None,
) -> Paper:
    return Paper(
        title=title,
        year=2025,
        journal="Journal of Tests",
        abstract="A probiotic improved outcomes.",
        identifiers=PaperIdentifiers(pmid=pmid, pmcid=pmcid, doi=doi),
        provenance=provenance
        or (
            globals()["provenance"](
                SourceName.PUBMED,
                record_id,
                f"https://pubmed.ncbi.nlm.nih.gov/{record_id}/",
            ),
        ),
    )


def provenance(source: SourceName, record_id: str, url: str) -> Provenance:
    return Provenance(
        source=source,
        record_id=record_id,
        url=url,
        retrieved_at=EXECUTED_AT,
    )
