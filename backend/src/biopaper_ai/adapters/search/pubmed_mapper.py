"""Map parsed PubMed records into canonical papers."""

from collections.abc import Mapping
from datetime import datetime

from pydantic import HttpUrl

from biopaper_ai.domain.paper import Paper, PaperIdentifiers
from biopaper_ai.domain.provenance import Provenance, SourceName


def map_pubmed_record(record: Mapping[str, object], retrieved_at: datetime) -> Paper:
    """Map one complete parsed record, rejecting truth-critical omissions."""
    pmid = _required_string(record, "pmid", "PMID")
    title = _required_string(record, "title", "title")
    url = _required_string(record, "url", "provenance URL")

    return Paper(
        title=title,
        authors=_string_tuple(record.get("authors")),
        year=_optional_year(record.get("year")),
        journal=_optional_string(record.get("journal")),
        publication_types=_string_tuple(record.get("publication_types")),
        abstract=_optional_string(record.get("abstract")),
        identifiers=PaperIdentifiers(
            pmid=pmid,
            doi=_optional_string(record.get("doi")),
            pmcid=_optional_string(record.get("pmcid")),
        ),
        provenance=(
            Provenance(
                source=SourceName.PUBMED,
                record_id=pmid,
                url=HttpUrl(url),
                retrieved_at=retrieved_at,
                response_sha256=_optional_string(record.get("response_sha256")),
            ),
        ),
    )


def _required_string(record: Mapping[str, object], key: str, display_name: str) -> str:
    value = _optional_string(record.get(key))
    if value is None:
        raise ValueError(f"PubMed record is missing {display_name}")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("PubMed text fields must be strings")
    normalized = value.strip()
    return normalized or None


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) for item in value
    ):
        raise ValueError("PubMed list fields must contain strings")
    return tuple(item.strip() for item in value if item.strip())


def _optional_year(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("PubMed year must be a positive integer")
    return value
