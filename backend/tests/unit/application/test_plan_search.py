"""Tests for reviewable search-plan generation."""

import pytest
from pydantic import SecretStr

from biopaper_ai.adapters.ai.deterministic_plan import DeterministicPlanGenerator
from biopaper_ai.application.plan_search import PlanSearch
from biopaper_ai.config import Settings
from biopaper_ai.domain.search_plan import SearchPlan


@pytest.mark.asyncio
async def test_deterministic_generator_extracts_one_year_range_conservatively() -> None:
    plan = await DeterministicPlanGenerator().generate(
        "aspirin cardiovascular prevention 2021-2026"
    )

    assert plan.original_query == "aspirin cardiovascular prevention 2021-2026"
    assert plan.topic == "aspirin cardiovascular prevention"
    assert [group.terms for group in plan.groups] == [
        ("aspirin cardiovascular prevention",)
    ]
    assert plan.boolean_query == '("aspirin cardiovascular prevention")'
    assert plan.filters.year_from == 2021
    assert plan.filters.year_to == 2026
    assert plan.mesh_terms == ()
    assert plan.generator == "deterministic"


@pytest.mark.asyncio
async def test_deterministic_generator_preserves_chinese_without_translation() -> None:
    plan = await DeterministicPlanGenerator().generate("糖尿病治疗")

    assert [group.terms for group in plan.groups] == [("糖尿病治疗",)]
    assert plan.boolean_query == '("糖尿病治疗")'
    assert plan.mesh_terms == ()
    assert any("translation" in warning.lower() for warning in plan.warnings)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("use_ai", "api_key"),
    [(False, SecretStr("configured")), (True, None)],
)
async def test_plan_search_falls_back_without_instantiating_openai(
    use_ai: bool, api_key: SecretStr | None
) -> None:
    instantiated = False

    def forbidden_factory(api_key: str, model: str) -> DeterministicPlanGenerator:
        nonlocal instantiated
        instantiated = True
        raise AssertionError("OpenAI generator must not be instantiated")

    service = PlanSearch(
        settings=Settings(openai_api_key=api_key),
        openai_generator_factory=forbidden_factory,
    )

    plan = await service.execute("heart failure", use_ai=use_ai)

    assert isinstance(plan, SearchPlan)
    assert plan.generator == "deterministic"
    assert any("deterministic" in warning.lower() for warning in plan.warnings)
    assert instantiated is False


@pytest.mark.asyncio
async def test_plan_search_uses_openai_only_when_requested_and_configured() -> None:
    generated = await DeterministicPlanGenerator().generate("heart failure")
    calls: list[str] = []

    class StubGenerator:
        async def generate(self, query: str) -> SearchPlan:
            calls.append(query)
            return generated.model_copy(update={"generator": "openai"})

    def factory(api_key: str, model: str) -> StubGenerator:
        assert api_key == "configured"
        assert model == "test-model"
        return StubGenerator()

    service = PlanSearch(
        settings=Settings(openai_api_key=SecretStr("configured"), model="test-model"),
        openai_generator_factory=factory,
    )

    plan = await service.execute("heart failure", use_ai=True)

    assert plan.generator == "openai"
    assert calls == ["heart failure"]
