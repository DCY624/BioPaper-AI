"""Conservative search-plan generation without an AI service."""

import re

from biopaper_ai.domain.search_plan import SearchFilters, SearchPlan, SynonymGroup

_YEAR_RANGE = re.compile(r"(?<!\d)(\d{4})\s*[-–—]\s*(\d{4})(?!\d)")
_CJK = re.compile(r"[\u3400-\u9fff]")


class DeterministicPlanGenerator:
    """Build one conservative free-text group without inventing semantics."""

    async def generate(self, query: str) -> SearchPlan:
        """Extract one year range and otherwise preserve the user's terms."""
        match = _YEAR_RANGE.search(query)
        year_from = int(match.group(1)) if match else None
        year_to = int(match.group(2)) if match else None
        topic = _YEAR_RANGE.sub(" ", query, count=1)
        topic = " ".join(topic.split())
        warnings: tuple[str, ...] = ()
        if _CJK.search(query):
            warnings = (
                "No translation was performed; the original query was preserved.",
            )

        return SearchPlan.build(
            original_query=query,
            topic=topic,
            groups=(SynonymGroup(terms=(topic,)),),
            mesh_terms=(),
            filters=SearchFilters(year_from=year_from, year_to=year_to),
            generator="deterministic",
            warnings=warnings,
        )
