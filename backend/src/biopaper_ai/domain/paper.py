"""Canonical literature-paper models."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from biopaper_ai.domain.identifiers import (
    normalize_doi,
    normalize_pmcid,
    normalize_pmid,
)
from biopaper_ai.domain.provenance import Provenance


class PaperIdentifiers(BaseModel):
    """Validated external identifiers for one paper."""

    model_config = ConfigDict(frozen=True)

    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    openalex_id: str | None = None

    @field_validator("doi", mode="before")
    @classmethod
    def canonicalize_doi(cls, value: object) -> str | None:
        return normalize_doi(value)  # type: ignore[arg-type]

    @field_validator("pmid", mode="before")
    @classmethod
    def canonicalize_pmid(cls, value: object) -> str | None:
        return normalize_pmid(value)  # type: ignore[arg-type]

    @field_validator("pmcid", mode="before")
    @classmethod
    def canonicalize_pmcid(cls, value: object) -> str | None:
        return normalize_pmcid(value)  # type: ignore[arg-type]


class Paper(BaseModel):
    """An immutable, database-backed biomedical literature record."""

    model_config = ConfigDict(frozen=True)

    title: Annotated[str, Field(min_length=1)]
    authors: tuple[str, ...] = ()
    year: int | None = None
    journal: str | None = None
    publication_types: tuple[str, ...] = ()
    abstract: str | None = None
    identifiers: PaperIdentifiers = Field(default_factory=PaperIdentifiers)
    provenance: tuple[Provenance, ...]

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be empty")
        return value.strip()

    @model_validator(mode="after")
    def must_have_provenance(self) -> "Paper":
        if not self.provenance:
            raise ValueError("provenance must contain at least one database record")
        return self

    @property
    def primary_id(self) -> str:
        """Return a stable source identifier without deriving one from title text."""
        if self.identifiers.doi is not None:
            return f"doi:{self.identifiers.doi}"
        if self.identifiers.pmid is not None:
            return f"pmid:{self.identifiers.pmid}"
        if self.identifiers.pmcid is not None:
            return f"pmcid:{self.identifiers.pmcid}"
        first_source = self.provenance[0]
        return f"{first_source.source}:{first_source.record_id}"
