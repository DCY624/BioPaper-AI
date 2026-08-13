"""Controlled fallback composition for literature search providers."""

from biopaper_ai.application.ports.search_provider import (
    ProviderFailure,
    ProviderFailureCode,
    ProviderResult,
    SearchProvider,
)
from biopaper_ai.domain.provenance import SourceName
from biopaper_ai.domain.search_plan import SearchPlan


class FallbackSearchProvider:
    """Use fallback only for an unavailable primary source with no papers."""

    def __init__(self, primary: SearchProvider, fallback: SearchProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    async def search(self, plan: SearchPlan, limit: int) -> ProviderResult:
        """Search primary first and preserve its unavailable failure on fallback."""
        try:
            primary_result = await self._primary.search(plan, limit)
        except Exception:
            primary_result = ProviderResult(failures=(_raised_primary_failure(),))

        if primary_result.papers or not _requires_fallback(primary_result):
            return primary_result

        try:
            fallback_result = await self._fallback.search(plan, limit)
        except Exception:
            fallback_result = ProviderResult(failures=(_raised_fallback_failure(),))
        return ProviderResult(
            papers=fallback_result.papers,
            source_counts=fallback_result.source_counts,
            failures=primary_result.failures + fallback_result.failures,
        )


def _requires_fallback(result: ProviderResult) -> bool:
    return not result.papers and any(
        failure.code is ProviderFailureCode.SOURCE_UNAVAILABLE
        for failure in result.failures
    )


def _raised_primary_failure() -> ProviderFailure:
    return ProviderFailure(
        source=SourceName.PUBMED,
        code=ProviderFailureCode.SOURCE_UNAVAILABLE,
        message="Primary PubMed provider is unavailable",
    )


def _raised_fallback_failure() -> ProviderFailure:
    return ProviderFailure(
        source=SourceName.PUBMED,
        code=ProviderFailureCode.SOURCE_UNAVAILABLE,
        message="Fallback PubMed provider is unavailable",
    )
