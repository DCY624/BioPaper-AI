"""Pure orchestration for reviewed biomedical literature searches."""

import json
import re
from collections.abc import Callable
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict

from biopaper_ai.application.ports.search_provider import (
    ProviderFailure,
    SearchProvider,
    SourceCount,
)
from biopaper_ai.domain.deduplication import AmbiguousMatch, deduplicate_papers
from biopaper_ai.domain.paper import Paper
from biopaper_ai.domain.search_plan import SearchFilters, SearchPlan

Clock = Callable[[], datetime]


class SearchHit(BaseModel):
    """A canonical paper with factual reasons for its deterministic position."""

    model_config = ConfigDict(frozen=True)

    paper: Paper
    ranking_reasons: tuple[str, ...]


class SearchRun(BaseModel):
    """Immutable, export-friendly record of one provider search execution."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    executed_at: datetime
    plan: SearchPlan
    hits: tuple[SearchHit, ...]
    source_counts: tuple[SourceCount, ...]
    failures: tuple[ProviderFailure, ...]
    ambiguous_matches: tuple[AmbiguousMatch, ...]


class SearchPapers:
    """Search with a reviewed plan, then deduplicate, filter, and rank locally."""

    def __init__(self, *, provider: SearchProvider, clock: Clock) -> None:
        self._provider = provider
        self._clock = clock

    async def execute(self, plan: SearchPlan, limit: int) -> SearchRun:
        """Execute a structured plan and retain all provider audit information."""
        executed_at = self._clock()
        provider_result = await self._provider.search(plan, limit)
        deduplicated = deduplicate_papers(provider_result.papers)

        ranked = _rank_papers(
            tuple(
                paper
                for paper in deduplicated.papers
                if _merged_paper_matches_filters(
                    paper, provider_result.papers, plan.filters
                )
            ),
            plan,
        )
        return SearchRun(
            run_id=_run_id(plan, executed_at),
            executed_at=executed_at,
            plan=plan,
            hits=ranked,
            source_counts=provider_result.source_counts,
            failures=provider_result.failures,
            ambiguous_matches=deduplicated.ambiguous,
        )


def paper_matches_filters(paper: Paper, filters: SearchFilters) -> bool:
    """Match only explicit filters against literal database-backed metadata."""
    if filters.year_from is not None:
        if paper.year is None or paper.year < filters.year_from:
            return False
    if filters.year_to is not None:
        if paper.year is None or paper.year > filters.year_to:
            return False

    searchable_metadata = _searchable_metadata(paper)
    if filters.species and not _contains_any(searchable_metadata, filters.species):
        return False
    if filters.study_types and not _contains_any(
        searchable_metadata, filters.study_types
    ):
        return False
    return True


def _merged_paper_matches_filters(
    canonical: Paper, originals: tuple[Paper, ...], filters: SearchFilters
) -> bool:
    canonical_provenance = set(canonical.provenance)
    safe_duplicates = tuple(
        paper
        for paper in originals
        if any(record in canonical_provenance for record in paper.provenance)
    )
    return any(paper_matches_filters(paper, filters) for paper in safe_duplicates)


def _searchable_metadata(paper: Paper) -> tuple[str, ...]:
    return (
        *paper.publication_types,
        paper.title,
        *((paper.abstract,) if paper.abstract is not None else ()),
    )


def _contains_any(values: tuple[str, ...], terms: tuple[str, ...]) -> bool:
    return any(_contains_literal(value, term) for value in values for term in terms)


def _contains_literal(value: str, term: str) -> bool:
    normalized_term = " ".join(term.casefold().split())
    if not normalized_term:
        return False
    normalized_value = " ".join(value.casefold().split())
    pattern = rf"(?<!\w){re.escape(normalized_term)}(?!\w)"
    return re.search(pattern, normalized_value) is not None


def _rank_papers(papers: tuple[Paper, ...], plan: SearchPlan) -> tuple[SearchHit, ...]:
    terms = _plan_terms(plan)
    positioned: list[tuple[tuple[int, int, int, int], SearchHit]] = []
    for position, paper in enumerate(papers):
        title_matches = _matched_terms(paper.title, terms)
        abstract_matches = _matched_terms(paper.abstract or "", terms)
        year = paper.year if paper.year is not None else -1
        key = (
            -int(bool(title_matches)),
            -int(bool(abstract_matches)),
            -year,
            position,
        )
        positioned.append(
            (
                key,
                SearchHit(
                    paper=paper,
                    ranking_reasons=(
                        _match_reason("title", title_matches),
                        _match_reason("abstract", abstract_matches),
                        _year_reason(paper.year),
                    ),
                ),
            )
        )
    positioned.sort(key=lambda item: item[0])
    return tuple(hit for _, hit in positioned)


def _plan_terms(plan: SearchPlan) -> tuple[str, ...]:
    terms: list[str] = []
    for group in plan.groups:
        for term in group.terms:
            if term.casefold() not in {existing.casefold() for existing in terms}:
                terms.append(term)
    return tuple(terms)


def _matched_terms(value: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(term for term in terms if _contains_literal(value, term))


def _match_reason(field: str, terms: tuple[str, ...]) -> str:
    rendered = ", ".join(terms) if terms else "none"
    return f"{field} term match: {rendered}"


def _year_reason(year: int | None) -> str:
    rendered = str(year) if year is not None else "unknown"
    return f"publication year: {rendered}"


def _run_id(plan: SearchPlan, executed_at: datetime) -> UUID:
    canonical_plan = json.dumps(
        plan.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    name = f"{canonical_plan}\n{executed_at.isoformat()}"
    return uuid5(NAMESPACE_URL, name)
