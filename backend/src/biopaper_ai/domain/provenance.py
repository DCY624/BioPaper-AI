"""Source provenance attached to every canonical paper."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class SourceName(StrEnum):
    """Supported literature databases and enrichment sources."""

    PUBMED = "pubmed"
    PMC = "pmc"
    EUROPE_PMC = "europe_pmc"
    OPENALEX = "openalex"
    PUBTATOR = "pubtator"


class Provenance(BaseModel):
    """An immutable pointer to the database record supporting a paper."""

    model_config = ConfigDict(frozen=True)

    source: SourceName
    record_id: str = Field(min_length=1)
    url: HttpUrl
    retrieved_at: datetime
    response_sha256: str | None = None
