"""Conservative paper deduplication that preserves database provenance."""

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from biopaper_ai.domain.paper import Paper, PaperIdentifiers
from biopaper_ai.domain.provenance import Provenance


class AmbiguousMatch(BaseModel):
    """Papers that look related but cannot be merged without guessing."""

    model_config = ConfigDict(frozen=True)

    normalized_title: str
    year: int | None
    papers: tuple[Paper, ...] = Field(min_length=2)
    conflicting_identifier_types: tuple[str, ...] = ()


class DeduplicationResult(BaseModel):
    """Stable canonical records and candidates requiring human review."""

    model_config = ConfigDict(frozen=True)

    papers: tuple[Paper, ...]
    ambiguous: tuple[AmbiguousMatch, ...]


def deduplicate_papers(papers: Iterable[Paper]) -> DeduplicationResult:
    """Merge exact identifier matches and report title/year candidates."""
    merged: list[Paper] = []
    for paper in papers:
        match_index = _first_compatible_identifier_match(merged, paper)
        if match_index is None:
            merged.append(paper)
            continue

        merged[match_index] = _merge_papers(merged[match_index], paper)
        _merge_newly_connected_records(merged, match_index)

    ambiguous = _find_ambiguous_title_year_matches(merged)
    return DeduplicationResult(papers=tuple(merged), ambiguous=ambiguous)


def _first_compatible_identifier_match(
    papers: list[Paper], candidate: Paper
) -> int | None:
    for index, existing in enumerate(papers):
        if _shares_strict_identifier(existing, candidate) and not _ids_conflict(
            existing, candidate
        ):
            return index
    return None


def _merge_newly_connected_records(papers: list[Paper], target_index: int) -> None:
    """Close safe transitive identifier links without merging conflicts."""
    scan_index = 0
    while scan_index < len(papers):
        if scan_index == target_index:
            scan_index += 1
            continue

        target = papers[target_index]
        candidate = papers[scan_index]
        if not _shares_strict_identifier(target, candidate) or _ids_conflict(
            target, candidate
        ):
            scan_index += 1
            continue

        first_index = min(target_index, scan_index)
        second_index = max(target_index, scan_index)
        papers[first_index] = _merge_papers(papers[first_index], papers[second_index])
        papers.pop(second_index)
        target_index = first_index
        scan_index = 0


def _shares_strict_identifier(left: Paper, right: Paper) -> bool:
    left_ids = left.identifiers
    right_ids = right.identifiers
    return any(
        first is not None and first == second
        for first, second in (
            (left_ids.doi, right_ids.doi),
            (left_ids.pmid, right_ids.pmid),
            (left_ids.pmcid, right_ids.pmcid),
        )
    )


def _ids_conflict(left: Paper, right: Paper) -> bool:
    left_ids = left.identifiers
    right_ids = right.identifiers
    return any(
        first is not None and second is not None and first != second
        for first, second in (
            (left_ids.doi, right_ids.doi),
            (left_ids.pmid, right_ids.pmid),
            (left_ids.pmcid, right_ids.pmcid),
            (left_ids.openalex_id, right_ids.openalex_id),
        )
    )


def _merge_papers(first: Paper, second: Paper) -> Paper:
    if _ids_conflict(first, second):
        raise ValueError("cannot merge papers with conflicting identifiers")

    first_ids = first.identifiers
    second_ids = second.identifiers
    identifiers = PaperIdentifiers(
        doi=first_ids.doi or second_ids.doi,
        pmid=first_ids.pmid or second_ids.pmid,
        pmcid=first_ids.pmcid or second_ids.pmcid,
        openalex_id=first_ids.openalex_id or second_ids.openalex_id,
    )
    return first.model_copy(
        update={
            "abstract": _longest_abstract(first.abstract, second.abstract),
            "identifiers": identifiers,
            "provenance": _stable_unique_provenance(
                (*first.provenance, *second.provenance)
            ),
        }
    )


def _longest_abstract(first: str | None, second: str | None) -> str | None:
    candidates = tuple(value for value in (first, second) if value and value.strip())
    if not candidates:
        return None
    return max(candidates, key=len)


def _stable_unique_provenance(records: Iterable[Provenance]) -> tuple[Provenance, ...]:
    unique: list[Provenance] = []
    for record in records:
        if record not in unique:
            unique.append(record)
    return tuple(unique)


def _find_ambiguous_title_year_matches(
    papers: list[Paper],
) -> tuple[AmbiguousMatch, ...]:
    groups: dict[tuple[str, int | None], list[Paper]] = {}
    for paper in papers:
        key = (_normalize_title(paper.title), paper.year)
        groups.setdefault(key, []).append(paper)

    ambiguous: list[AmbiguousMatch] = []
    for (normalized_title, year), candidates in groups.items():
        if len(candidates) < 2:
            continue
        ambiguous.append(
            AmbiguousMatch(
                normalized_title=normalized_title,
                year=year,
                papers=tuple(candidates),
                conflicting_identifier_types=_conflicting_identifier_types(candidates),
            )
        )
    return tuple(ambiguous)


def _normalize_title(title: str) -> str:
    return " ".join(title.casefold().split())


def _conflicting_identifier_types(papers: list[Paper]) -> tuple[str, ...]:
    conflicts: list[str] = []
    fields: tuple[tuple[str, tuple[str | None, ...]], ...] = (
        ("doi", tuple(paper.identifiers.doi for paper in papers)),
        ("pmid", tuple(paper.identifiers.pmid for paper in papers)),
        ("pmcid", tuple(paper.identifiers.pmcid for paper in papers)),
        ("openalex_id", tuple(paper.identifiers.openalex_id for paper in papers)),
    )
    for name, values in fields:
        if len({value for value in values if value is not None}) > 1:
            conflicts.append(name)
    return tuple(conflicts)
