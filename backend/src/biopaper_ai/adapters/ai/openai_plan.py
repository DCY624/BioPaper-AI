"""OpenAI Structured Outputs adapter for reviewable search plans."""

import importlib
import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from biopaper_ai.domain.search_plan import SearchFilters, SearchPlan, SynonymGroup
from biopaper_ai.errors import BioPaperError, ErrorCode

_UNSAFE_DATA = re.compile(
    r"(?:\b(?:AND|OR|NOT)\b|https?://|\b(?:PMID|PMCID|DOI)\b|10\.\d{4,9}/)",
    re.IGNORECASE,
)

_INSTRUCTIONS = """Return only structured data for a biomedical search-plan draft.
Request or return only: topic, synonym groups, MeSH candidates, year constraints
(year from and year to), species constraints, and study type constraints.
MeSH values are candidates for human review, not verified headings.
Do not return Boolean syntax; the application constructs it locally.
Do not request or return PMID.
Do not request or return PMCID.
Do not request or return DOI.
Do not request or return URL.
Do not request or return source record.
Do not request or return citation or paper citations.
"""


class SearchPlanDraft(BaseModel):
    """Data-only output accepted from the model before local construction."""

    model_config = ConfigDict(extra="forbid", strict=True)

    topic: str = Field(min_length=1)
    synonym_groups: list[list[str]] = Field(min_length=1)
    mesh_candidates: list[str]
    year_from: int | None
    year_to: int | None
    species: list[str]
    study_types: list[str]

    @field_validator("topic", "mesh_candidates", "species", "study_types", mode="after")
    @classmethod
    def validates_scalar_or_list_data(cls, value: object) -> object:
        values = value if isinstance(value, list) else [value]
        if any(
            not isinstance(item, str)
            or not item.strip()
            or _UNSAFE_DATA.search(item) is not None
            for item in values
        ):
            raise ValueError("model data contains blank, Boolean, or identifier syntax")
        return value

    @field_validator("synonym_groups", mode="after")
    @classmethod
    def validates_synonym_data(cls, groups: list[list[str]]) -> list[list[str]]:
        if any(not group for group in groups):
            raise ValueError("synonym groups must not be empty")
        if any(
            not term.strip() or _UNSAFE_DATA.search(term) is not None
            for group in groups
            for term in group
        ):
            raise ValueError("synonyms contain blank, Boolean, or identifier syntax")
        return groups


class _Responses(Protocol):
    async def parse(self, **kwargs: object) -> object: ...


class _OpenAIClient(Protocol):
    responses: _Responses


class OpenAIPlanGenerator:
    """Request structured concepts and construct the actual plan locally."""

    def __init__(self, *, client: _OpenAIClient, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_api_key(cls, *, api_key: str, model: str) -> "OpenAIPlanGenerator":
        """Create the external client only after orchestration selects AI."""
        openai = importlib.import_module("openai")
        client: _OpenAIClient = openai.AsyncOpenAI(api_key=api_key)
        return cls(client=client, model=model)

    async def generate(self, query: str) -> SearchPlan:
        """Turn parsed data into a locally controlled Boolean search plan."""
        try:
            response = await self._client.responses.parse(
                model=self._model,
                input=query,
                instructions=_INSTRUCTIONS,
                text_format=SearchPlanDraft,
            )
            parsed = getattr(response, "output_parsed", None)
            if not isinstance(parsed, SearchPlanDraft):
                raise ValueError("structured output was missing or refused")
            groups = tuple(
                SynonymGroup(terms=tuple(terms)) for terms in parsed.synonym_groups
            )
            warnings = (
                ("MeSH terms are unverified candidates and require human review.",)
                if parsed.mesh_candidates
                else ()
            )
            return SearchPlan.build(
                original_query=query,
                topic=parsed.topic,
                groups=groups,
                mesh_terms=tuple(parsed.mesh_candidates),
                filters=SearchFilters(
                    year_from=parsed.year_from,
                    year_to=parsed.year_to,
                    species=tuple(parsed.species),
                    study_types=tuple(parsed.study_types),
                ),
                generator="openai",
                warnings=warnings,
            )
        except (AttributeError, TypeError, ValueError, ValidationError) as error:
            raise BioPaperError(
                ErrorCode.AI_OUTPUT_INVALID,
                "OpenAI returned an invalid structured search-plan draft.",
            ) from error
