"""Port for asynchronous search-plan generation."""

from typing import Protocol

from biopaper_ai.domain.search_plan import SearchPlan


class PlanGenerator(Protocol):
    """Generate a reviewable search plan from an unchanged user query."""

    async def generate(self, query: str) -> SearchPlan:
        """Return a locally constructed search plan."""
        ...
