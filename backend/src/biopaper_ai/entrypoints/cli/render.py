"""Rich rendering for application-owned CLI values."""

from rich.console import Console
from rich.table import Table

from biopaper_ai.application.search_papers import SearchRun
from biopaper_ai.config import Settings
from biopaper_ai.domain.search_plan import SearchPlan


def render_plan(console: Console, plan: SearchPlan) -> None:
    """Display a reviewable plan before any database call."""
    table = Table(title="Search plan")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Original query", plan.original_query)
    table.add_row("Topic", plan.topic)
    table.add_row(
        "Synonym groups",
        "\n".join(
            f"{position}. {' | '.join(group.terms)}"
            for position, group in enumerate(plan.groups, start=1)
        ),
    )
    table.add_row("Candidate MeSH", " | ".join(plan.mesh_terms) or "none")
    table.add_row("Boolean query", plan.boolean_query)
    table.add_row("Year filter", _year_filter(plan))
    table.add_row("Species filter", " | ".join(plan.filters.species) or "none")
    table.add_row(
        "Study type filter",
        " | ".join(plan.filters.study_types) or "none",
    )
    table.add_row("Generator", plan.generator)
    table.add_row("Warnings", "\n".join(plan.warnings) or "none")
    console.print(table)


def render_run(console: Console, run: SearchRun) -> None:
    """Display canonical papers and visible provider failures."""
    table = Table(title="Search results")
    table.add_column("Title")
    table.add_column("Year")
    table.add_column("Sources")
    for hit in run.hits:
        paper = hit.paper
        table.add_row(
            paper.title,
            str(paper.year) if paper.year is not None else "",
            ", ".join(record.source for record in paper.provenance),
        )
    console.print(table)
    for failure in run.failures:
        console.print(f"[yellow]Warning:[/yellow] {failure.message}")


def render_doctor(console: Console, settings: Settings) -> None:
    """Display only safe configuration flags and non-secret values."""
    diagnostics = settings.diagnostic_dict()
    table = Table(title="BioPaper doctor")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("NCBI email configured", _yes_no(settings.ncbi_email is not None))
    table.add_row(
        "NCBI API key configured",
        _yes_no(bool(diagnostics["ncbi_api_key_configured"])),
    )
    table.add_row(
        "OpenAI API key configured",
        _yes_no(bool(diagnostics["openai_api_key_configured"])),
    )
    table.add_row("Live search available", _yes_no(settings.can_search_live))
    table.add_row("Model", settings.model)
    table.add_row("Database configured", _yes_no(bool(settings.database_url)))
    console.print(table)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _year_filter(plan: SearchPlan) -> str:
    year_from = str(plan.filters.year_from) if plan.filters.year_from else "any"
    year_to = str(plan.filters.year_to) if plan.filters.year_to else "any"
    if year_from == year_to == "any":
        return "none"
    return f"{year_from} through {year_to}"
