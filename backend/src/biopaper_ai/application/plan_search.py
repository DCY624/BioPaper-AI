"""Application service selecting AI or deterministic search-plan generation."""

from collections.abc import Callable

from biopaper_ai.adapters.ai.deterministic_plan import DeterministicPlanGenerator
from biopaper_ai.adapters.ai.openai_plan import OpenAIPlanGenerator
from biopaper_ai.application.ports.plan_generator import PlanGenerator
from biopaper_ai.config import Settings
from biopaper_ai.domain.search_plan import SearchPlan

OpenAIGeneratorFactory = Callable[[str, str], PlanGenerator]


def _openai_generator(api_key: str, model: str) -> PlanGenerator:
    return OpenAIPlanGenerator.from_api_key(api_key=api_key, model=model)


class PlanSearch:
    """Generate a reviewable plan while keeping no-key operation available."""

    def __init__(
        self,
        *,
        settings: Settings,
        openai_generator_factory: OpenAIGeneratorFactory = _openai_generator,
    ) -> None:
        self._settings = settings
        self._openai_generator_factory = openai_generator_factory

    async def execute(self, query: str, use_ai: bool) -> SearchPlan:
        """Use OpenAI only when both requested and configured."""
        api_key = self._settings.openai_api_key
        api_key_value = (
            api_key.get_secret_value().strip() if api_key is not None else ""
        )
        if use_ai and api_key_value:
            generator = self._openai_generator_factory(
                api_key_value, self._settings.model
            )
            return await generator.generate(query)

        plan = await DeterministicPlanGenerator().generate(query)
        reason = (
            "AI generation was disabled; using the deterministic generator."
            if not use_ai
            else "No OpenAI API key is configured; using the deterministic generator."
        )
        return plan.model_copy(update={"warnings": (*plan.warnings, reason)})
