"""Thin Typer orchestration over application-owned services."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import typer
from rich.console import Console

from biopaper_ai.application.export_results import export_search_run
from biopaper_ai.application.plan_search import PlanSearch
from biopaper_ai.application.search_papers import SearchPapers, SearchRun
from biopaper_ai.config import Settings
from biopaper_ai.domain.search_plan import SearchPlan
from biopaper_ai.entrypoints.cli.render import render_doctor, render_plan, render_run


class PlanService(Protocol):
    async def execute(self, query: str, use_ai: bool) -> SearchPlan: ...


class SearchService(Protocol):
    async def execute(self, plan: SearchPlan, limit: int) -> SearchRun: ...


SettingsFactory = Callable[[], Settings]
PlanServiceFactory = Callable[[Settings], PlanService]
SearchServiceFactory = Callable[[Settings], SearchService]


class _SearchConfigurationError(Exception):
    """Known, safe-to-display configuration problem at CLI composition."""


def _plan_service(settings: Settings) -> PlanService:
    return PlanSearch(settings=settings)


def _search_service(settings: Settings) -> SearchService:
    if not settings.can_search_live:
        raise _SearchConfigurationError(
            "BIOPAPER_NCBI_EMAIL is required for PubMed search"
        )
    from biopaper_ai.adapters.search.fallback import FallbackSearchProvider
    from biopaper_ai.adapters.search.native_pubmed import NativePubMedProvider
    from biopaper_ai.adapters.search.pubmed_search_mcp import (
        create_pubmed_search_mcp_provider,
    )

    provider = FallbackSearchProvider(
        create_pubmed_search_mcp_provider(settings),
        NativePubMedProvider(settings),
    )
    return SearchPapers(provider=provider, clock=lambda: datetime.now(UTC))


def create_app(
    *,
    settings_factory: SettingsFactory = Settings.from_env,
    plan_service_factory: PlanServiceFactory = _plan_service,
    search_service_factory: SearchServiceFactory = _search_service,
) -> typer.Typer:
    """Build a CLI whose application services can be replaced in tests."""
    cli = typer.Typer(help="BioPaper AI trusted biomedical literature search.")

    @cli.command("plan")
    def plan_command(
        query: str,
        json_output: bool = typer.Option(False, "--json"),
        use_ai: bool = typer.Option(True, "--ai/--no-ai"),
    ) -> None:
        settings = settings_factory()
        plan = asyncio.run(plan_service_factory(settings).execute(query, use_ai))
        if json_output:
            typer.echo(plan.model_dump_json(indent=2))
        else:
            render_plan(Console(), plan)

    @cli.command("search")
    def search_command(
        query: str,
        limit: int = typer.Option(20, min=1),
        use_ai: bool = typer.Option(True, "--ai/--no-ai"),
        non_interactive: bool = typer.Option(False, "--non-interactive"),
        accept_plan: bool = typer.Option(False, "--accept-plan"),
        output: Path | None = typer.Option(None, "--output"),
    ) -> None:
        if non_interactive and not accept_plan:
            typer.echo(
                "Error: --accept-plan is required with --non-interactive",
                err=True,
            )
            raise typer.Exit(code=2)
        settings = settings_factory()
        plan = asyncio.run(plan_service_factory(settings).execute(query, use_ai))
        console = Console()
        if not accept_plan:
            render_plan(console, plan)
            if not typer.confirm("Search this reviewed plan?"):
                typer.echo("Search cancelled.")
                return
        try:
            search_service = search_service_factory(settings)
        except _SearchConfigurationError as error:
            typer.echo(f"Configuration error: {error}", err=True)
            raise typer.Exit(code=1) from None
        run = asyncio.run(search_service.execute(plan, limit))
        render_run(console, run)
        if output is not None:
            export_format = output.suffix.removeprefix(".").casefold()
            try:
                exported = export_search_run(run, export_format, output)
            except ValueError as error:
                raise typer.BadParameter(str(error), param_hint="--output") from error
            typer.echo(f"Exported results to {exported}")
        if run.failures and not run.hits:
            raise typer.Exit(code=1)

    @cli.command("doctor")
    def doctor_command() -> None:
        render_doctor(Console(), settings_factory())

    return cli


app = create_app()
