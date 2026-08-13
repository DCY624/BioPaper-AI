"""Application-facing contract for literature search providers."""

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from biopaper_ai.domain.paper import Paper
from biopaper_ai.domain.provenance import SourceName
from biopaper_ai.domain.search_plan import SearchPlan


class ProviderFailureCode(StrEnum):
    """Sanitized failure categories that callers may safely persist."""

    RATE_LIMITED = "rate_limited"
    SOURCE_UNAVAILABLE = "source_unavailable"
    INVALID_RECORD = "invalid_record"


class ProviderFailure(BaseModel):
    """A safe, immutable provider failure without request or secret data."""

    model_config = ConfigDict(frozen=True)

    source: SourceName
    code: ProviderFailureCode
    message: str
    retry_after_seconds: float | None = Field(default=None, ge=0)
    record_id: str | None = None


class SourceCount(BaseModel):
    """Counts reported by one provider for a search call."""

    model_config = ConfigDict(frozen=True)

    source: SourceName
    requested: int = Field(ge=0)
    returned: int = Field(ge=0)


class ProviderResult(BaseModel):
    """Immutable papers plus visible counts and partial failures."""

    model_config = ConfigDict(frozen=True)

    papers: tuple[Paper, ...] = ()
    source_counts: tuple[SourceCount, ...] = ()
    failures: tuple[ProviderFailure, ...] = ()


class SearchProvider(Protocol):
    """Port implemented by every external literature database adapter."""

    async def search(self, plan: SearchPlan, limit: int) -> ProviderResult:
        """Search using a reviewed structured plan."""
        ...
