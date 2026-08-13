"""Reviewable local construction of biomedical Boolean search plans."""

from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)


class SynonymGroup(BaseModel):
    """A non-empty group of terms joined by a Boolean OR."""

    model_config = ConfigDict(frozen=True)

    terms: tuple[Annotated[str, Field(min_length=1)], ...] = Field(min_length=1)

    @field_validator("terms")
    @classmethod
    def normalizes_terms(cls, terms: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(term.strip() for term in terms)
        if any(not term for term in normalized):
            raise ValueError("synonym terms must not be blank")
        return normalized

    @property
    def boolean_clause(self) -> str:
        """Render terms in a safe, locally-owned Boolean clause."""
        rendered_terms = " OR ".join(_quote_term(term) for term in self.terms)
        return f"({rendered_terms})"


class SearchFilters(BaseModel):
    """Optional post-search filters the application evaluates locally."""

    model_config = ConfigDict(frozen=True)

    year_from: Annotated[StrictInt, Field(gt=0)] | None = None
    year_to: Annotated[StrictInt, Field(gt=0)] | None = None
    species: tuple[str, ...] = ()
    study_types: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validates_year_range(self) -> "SearchFilters":
        if self.year_from is not None and self.year_to is not None:
            if self.year_from > self.year_to:
                raise ValueError("year_from must not be after year_to")
        return self


class SearchPlan(BaseModel):
    """An immutable plan requiring explicit review before a database search."""

    model_config = ConfigDict(frozen=True)

    original_query: Annotated[str, Field(min_length=1)]
    topic: Annotated[str, Field(min_length=1)]
    groups: tuple[SynonymGroup, ...] = Field(min_length=1)
    mesh_terms: tuple[str, ...] = ()
    filters: SearchFilters = Field(default_factory=SearchFilters)
    generator: Annotated[str, Field(min_length=1)]
    boolean_query: Annotated[str, Field(min_length=1)]
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validates_local_boolean_query(self) -> "SearchPlan":
        expected = " AND ".join(group.boolean_clause for group in self.groups)
        if self.boolean_query != expected:
            raise ValueError("boolean_query must be constructed locally from groups")
        return self

    @classmethod
    def build(
        cls,
        *,
        original_query: str,
        topic: str,
        groups: tuple[SynonymGroup, ...],
        mesh_terms: tuple[str, ...],
        filters: SearchFilters,
        generator: str,
        warnings: tuple[str, ...] = (),
    ) -> "SearchPlan":
        """Construct Boolean syntax from structured groups, never external text."""
        if not groups:
            raise ValueError("at least one synonym group is required")
        return cls(
            original_query=original_query,
            topic=topic,
            groups=groups,
            mesh_terms=mesh_terms,
            filters=filters,
            generator=generator,
            boolean_query=" AND ".join(group.boolean_clause for group in groups),
            warnings=warnings,
        )


def _quote_term(term: str) -> str:
    normalized = term.strip()
    if not normalized:
        raise ValueError("synonym terms must not be blank")
    if '"' in normalized or any(character.isspace() for character in normalized):
        escaped = normalized.replace('"', r"\"")
        return f'"{escaped}"'
    return normalized
