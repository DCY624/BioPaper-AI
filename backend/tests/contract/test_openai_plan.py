"""Contract tests for OpenAI structured search-plan generation."""

from types import SimpleNamespace
from typing import Any

import pytest

from biopaper_ai.adapters.ai.openai_plan import (
    OpenAIPlanGenerator,
    SearchPlanDraft,
)
from biopaper_ai.errors import BioPaperError, ErrorCode


class FakeResponses:
    def __init__(self, parsed: SearchPlanDraft | None) -> None:
        self.parsed = parsed
        self.request: dict[str, Any] | None = None

    async def parse(self, **kwargs: Any) -> object:
        self.request = kwargs
        return SimpleNamespace(output_parsed=self.parsed)


class FakeAsyncOpenAI:
    def __init__(self, parsed: SearchPlanDraft | None) -> None:
        self.responses = FakeResponses(parsed)


@pytest.mark.asyncio
async def test_openai_generator_requests_only_structured_search_concepts() -> None:
    query = "Does exercise help adults with depression since 2020?"
    draft = SearchPlanDraft(
        topic="exercise for adult depression",
        synonym_groups=[["exercise", "physical activity"], ["depression"]],
        mesh_candidates=["Exercise", "Depressive Disorder"],
        year_from=2020,
        year_to=None,
        species=["humans"],
        study_types=["randomized controlled trial"],
    )
    client = FakeAsyncOpenAI(draft)

    plan = await OpenAIPlanGenerator(client=client, model="test-model").generate(query)

    assert client.responses.request is not None
    request = client.responses.request
    assert request["input"] == query
    assert request["model"] == "test-model"
    assert request["text_format"] is SearchPlanDraft
    instructions = request["instructions"].lower()
    for concept in ("topic", "synonym", "mesh", "year", "species", "study type"):
        assert concept in instructions
    for forbidden in ("pmid", "pmcid", "doi", "url", "source record", "citation"):
        assert f"do not request or return {forbidden}" in instructions

    assert plan.original_query == query
    assert plan.mesh_terms == ("Exercise", "Depressive Disorder")
    assert any("candidates" in warning.lower() for warning in plan.warnings)
    assert plan.boolean_query == ('(exercise OR "physical activity") AND (depression)')
    assert plan.filters.year_from == 2020
    assert plan.filters.species == ("humans",)
    assert plan.filters.study_types == ("randomized controlled trial",)
    assert plan.generator == "openai"


@pytest.mark.asyncio
async def test_openai_generator_rejects_missing_or_refused_parsed_output() -> None:
    client = FakeAsyncOpenAI(None)

    with pytest.raises(BioPaperError) as error:
        await OpenAIPlanGenerator(client=client, model="test-model").generate("query")

    assert error.value.code is ErrorCode.AI_OUTPUT_INVALID


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_term",
    ["asthma OR bronchitis", "PMID 12345", "https://example.test/paper"],
)
async def test_openai_generator_rejects_boolean_or_identifier_model_data(
    unsafe_term: str,
) -> None:
    client = FakeAsyncOpenAI(None)

    async def malformed_parse(**kwargs: Any) -> object:
        model = kwargs["text_format"]
        parsed = model.model_validate(
            {
                "topic": "asthma",
                "synonym_groups": [[unsafe_term]],
                "mesh_candidates": [],
                "year_from": None,
                "year_to": None,
                "species": [],
                "study_types": [],
            }
        )
        return SimpleNamespace(output_parsed=parsed)

    client.responses.parse = malformed_parse

    with pytest.raises(BioPaperError) as error:
        await OpenAIPlanGenerator(client=client, model="test-model").generate("asthma")

    assert error.value.code is ErrorCode.AI_OUTPUT_INVALID
