import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import SecretStr
from rich.console import Console
from typer.testing import CliRunner

from biopaper_ai.application.ports.search_provider import (
    ProviderFailure,
    ProviderFailureCode,
    SourceCount,
)
from biopaper_ai.application.search_papers import SearchHit, SearchRun
from biopaper_ai.config import Settings
from biopaper_ai.domain.paper import Paper, PaperIdentifiers
from biopaper_ai.domain.provenance import Provenance, SourceName
from biopaper_ai.domain.search_plan import SearchFilters, SearchPlan, SynonymGroup
from biopaper_ai.entrypoints.cli.app import create_app
from biopaper_ai.entrypoints.cli.render import render_plan

EXECUTED_AT = datetime(2026, 8, 14, 11, 0, tzinfo=UTC)
RUNNER = CliRunner()


class RecordingPlanService:
    def __init__(self, plan: SearchPlan) -> None:
        self.plan = plan
        self.calls: list[tuple[str, bool]] = []

    async def execute(self, query: str, use_ai: bool) -> SearchPlan:
        self.calls.append((query, use_ai))
        return self.plan


class RecordingSearchService:
    def __init__(self, run: SearchRun) -> None:
        self.run = run
        self.calls: list[tuple[SearchPlan, int]] = []

    async def execute(self, plan: SearchPlan, limit: int) -> SearchRun:
        self.calls.append((plan, limit))
        return self.run


def test_plan_json_outputs_plan_without_calling_search() -> None:
    plan_service = RecordingPlanService(search_plan())
    search_service = RecordingSearchService(search_run())
    app = _make_app(plan_service, search_service)

    result = RUNNER.invoke(app, ["plan", "probiotic", "--json", "--no-ai"])

    assert result.exit_code == 0
    assert json.loads(result.output)["boolean_query"] == "(probiotic)"
    assert plan_service.calls == [("probiotic", False)]
    assert search_service.calls == []


def test_non_interactive_search_requires_explicit_plan_acceptance() -> None:
    plan_service = RecordingPlanService(search_plan())
    search_service = RecordingSearchService(search_run())
    app = _make_app(plan_service, search_service)

    result = RUNNER.invoke(
        app,
        ["search", "probiotic", "--non-interactive"],
        color=True,
        terminal_width=40,
    )

    assert result.exit_code == 2
    assert result.output == "Error: --accept-plan is required with --non-interactive\n"
    assert plan_service.calls == []
    assert search_service.calls == []


def test_accept_plan_with_no_ai_never_requests_openai() -> None:
    plan_service = RecordingPlanService(search_plan())
    search_service = RecordingSearchService(search_run())
    app = _make_app(plan_service, search_service)

    result = RUNNER.invoke(
        app,
        ["search", "probiotic", "--accept-plan", "--no-ai", "--limit", "7"],
    )

    assert result.exit_code == 0
    assert plan_service.calls == [("probiotic", False)]
    assert search_service.calls == [(plan_service.plan, 7)]


def test_interactive_rejection_does_not_call_search() -> None:
    plan_service = RecordingPlanService(search_plan())
    search_service = RecordingSearchService(search_run())
    app = _make_app(plan_service, search_service)

    result = RUNNER.invoke(
        app,
        ["search", "probiotic", "--no-ai"],
        input="n\n",
    )

    assert result.exit_code == 0
    assert "Boolean query" in result.output
    assert "Search this reviewed plan?" in result.output
    assert search_service.calls == []


def test_render_plan_includes_every_reviewable_search_input() -> None:
    output = StringIO()

    render_plan(Console(file=output, width=240, color_system=None), detailed_plan())

    rendered = output.getvalue()
    assert "Original query" in rendered
    assert "probiotics for gut barrier" in rendered
    assert "Synonym groups" in rendered
    assert "1. probiotic | gut flora" in rendered
    assert "2. intestinal barrier" in rendered
    assert "Candidate MeSH" in rendered
    assert "Probiotics | Gastrointestinal Microbiome" in rendered
    assert "Year filter" in rendered
    assert "2021 through 2026" in rendered
    assert "Species filter" in rendered
    assert "Mice | Humans" in rendered
    assert "Study type filter" in rendered
    assert "Review | Randomized Controlled Trial" in rendered


def test_interactive_review_shows_complete_plan_before_confirmation() -> None:
    plan_service = RecordingPlanService(detailed_plan())
    search_service = RecordingSearchService(search_run())
    app = _make_app(plan_service, search_service)

    result = RUNNER.invoke(
        app,
        ["search", "probiotics for gut barrier", "--no-ai"],
        input="n\n",
        terminal_width=240,
    )

    confirmation_position = result.output.index("Search this reviewed plan?")
    for expected in (
        "Synonym groups",
        "Candidate MeSH",
        "2021 through 2026",
        "Mice | Humans",
        "Review | Randomized Controlled Trial",
    ):
        assert 0 <= result.output.index(expected) < confirmation_position
    assert search_service.calls == []


def test_doctor_reports_configuration_flags_without_secret_values() -> None:
    ncbi_secret = "fake-ncbi-secret-never-print"
    openai_secret = "fake-openai-secret-never-print"
    database_secret = "fake-database-secret-never-print"
    settings = Settings(
        ncbi_email="researcher@example.test",
        ncbi_api_key=SecretStr(ncbi_secret),
        openai_api_key=SecretStr(openai_secret),
        database_url=f"postgresql://user:{database_secret}@database.test/biopaper",
    )
    app = _make_app(
        RecordingPlanService(search_plan()),
        RecordingSearchService(search_run()),
        settings=settings,
    )

    result = RUNNER.invoke(app, ["doctor"], terminal_width=240)

    assert result.exit_code == 0
    assert "NCBI API key configured" in result.output
    assert "OpenAI API key configured" in result.output
    assert "yes" in result.output
    assert ncbi_secret not in result.output
    assert openai_secret not in result.output
    assert database_secret not in result.output
    assert "postgresql://user:" not in result.output


def test_partial_failure_with_papers_warns_and_exits_zero() -> None:
    plan_service = RecordingPlanService(search_plan())
    search_service = RecordingSearchService(
        search_run(with_hit=True, with_failure=True)
    )
    app = _make_app(plan_service, search_service)

    result = RUNNER.invoke(app, accepted_search_args())

    assert result.exit_code == 0
    assert "warning" in result.output.lower()
    assert "rate limited" in result.output.lower()
    assert "Probiotic outcomes" in result.output


def test_source_failure_without_papers_exits_non_zero() -> None:
    plan_service = RecordingPlanService(search_plan())
    search_service = RecordingSearchService(
        search_run(with_hit=False, with_failure=True)
    )
    app = _make_app(plan_service, search_service)

    result = RUNNER.invoke(app, accepted_search_args())

    assert result.exit_code == 1
    assert "rate limited" in result.output.lower()


def test_production_search_reports_missing_ncbi_email_without_a_traceback() -> None:
    app = create_app()

    result = RUNNER.invoke(
        app,
        accepted_search_args(),
        env={"BIOPAPER_NCBI_EMAIL": ""},
    )

    assert result.exit_code == 1
    assert "BIOPAPER_NCBI_EMAIL" in result.output
    assert "traceback" not in result.output.casefold()
    assert not isinstance(result.exception, ValueError)


@pytest.mark.parametrize("suffix", ["json", "csv"])
def test_output_path_exports_results_with_provenance(
    tmp_path: Path, suffix: str
) -> None:
    plan_service = RecordingPlanService(search_plan())
    search_service = RecordingSearchService(search_run())
    app = _make_app(plan_service, search_service)
    destination = tmp_path / f"results.{suffix}"

    result = RUNNER.invoke(
        app,
        [*accepted_search_args(), "--output", str(destination)],
    )

    assert result.exit_code == 0
    assert destination.exists()
    exported = destination.read_text(encoding="utf-8-sig")
    assert "pubmed" in exported
    assert "https://pubmed.ncbi.nlm.nih.gov/12345/" in exported


def _make_app(
    plan_service: RecordingPlanService,
    search_service: RecordingSearchService,
    *,
    settings: Settings | None = None,
) -> object:
    configured = settings or Settings()
    return create_app(
        settings_factory=lambda: configured,
        plan_service_factory=lambda _: plan_service,
        search_service_factory=lambda _: search_service,
    )


def accepted_search_args() -> list[str]:
    return ["search", "probiotic", "--accept-plan", "--no-ai"]


def search_plan() -> SearchPlan:
    return SearchPlan.build(
        original_query="probiotic",
        topic="probiotic",
        groups=(SynonymGroup(terms=("probiotic",)),),
        mesh_terms=("Probiotics",),
        filters=SearchFilters(),
        generator="deterministic",
    )


def detailed_plan() -> SearchPlan:
    return SearchPlan.build(
        original_query="probiotics for gut barrier",
        topic="probiotics and intestinal barrier",
        groups=(
            SynonymGroup(terms=("probiotic", "gut flora")),
            SynonymGroup(terms=("intestinal barrier",)),
        ),
        mesh_terms=("Probiotics", "Gastrointestinal Microbiome"),
        filters=SearchFilters(
            year_from=2021,
            year_to=2026,
            species=("Mice", "Humans"),
            study_types=("Review", "Randomized Controlled Trial"),
        ),
        generator="openai",
    )


def search_run(*, with_hit: bool = True, with_failure: bool = False) -> SearchRun:
    plan = search_plan()
    paper = Paper(
        title="Probiotic outcomes",
        year=2025,
        journal="Journal of Tests",
        abstract="A probiotic improved outcomes.",
        identifiers=PaperIdentifiers(pmid="12345", doi="10.1000/example"),
        provenance=(
            Provenance(
                source=SourceName.PUBMED,
                record_id="12345",
                url="https://pubmed.ncbi.nlm.nih.gov/12345/",
                retrieved_at=EXECUTED_AT,
            ),
        ),
    )
    failures = (
        (
            ProviderFailure(
                source=SourceName.PUBMED,
                code=ProviderFailureCode.RATE_LIMITED,
                message="PubMed request was rate limited",
                retry_after_seconds=2,
            ),
        )
        if with_failure
        else ()
    )
    hits = (
        (SearchHit(paper=paper, ranking_reasons=("title term match: probiotic",)),)
        if with_hit
        else ()
    )
    return SearchRun(
        run_id=UUID("12345678-1234-5678-9234-567812345678"),
        executed_at=EXECUTED_AT,
        plan=plan,
        hits=hits,
        source_counts=(
            SourceCount(
                source=SourceName.PUBMED,
                requested=10,
                returned=len(hits),
            ),
        ),
        failures=failures,
        ambiguous_matches=(),
    )
