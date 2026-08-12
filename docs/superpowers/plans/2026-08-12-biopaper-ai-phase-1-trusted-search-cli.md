# BioPaper AI Phase 1 Trusted Search CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Build an installable biopaper Python CLI that turns a natural-language biomedical question into a reviewable search plan, searches real PubMed records through a pinned upstream SDK with a native NCBI fallback, deduplicates results, and exports source-grounded JSON or CSV.

**Architecture:** A dependency-free domain layer defines plans, papers, provenance, filters, identifiers, and provider protocols. Application services orchestrate plan generation and search; adapters isolate OpenAI, pubmed-search-mcp, and native NCBI E-Utilities. Typer remains a thin entrypoint, while offline contract fixtures cover all default tests.

**Tech Stack:** Python 3.11+, Hatchling, Pydantic 2, pydantic-settings, HTTPX, defusedxml, Typer, Rich, OpenAI Python SDK, pubmed-search-mcp==0.6.2, pytest, pytest-asyncio, Ruff, mypy, GitHub Actions.

## Global Constraints

- Paper truthfulness has priority over extraction accuracy, feature count, and appearance.
- PMID, PMCID, and DOI values may only come from database responses or official identifier conversion responses.
- BIOPAPER_NCBI_EMAIL is required for live PubMed calls; BIOPAPER_NCBI_API_KEY is optional.
- NCBI traffic is capped at 3 requests/second without a key and 10 requests/second with one.
- AI uses a user-supplied BIOPAPER_OPENAI_API_KEY; search and export remain usable without it.
- Secrets never enter logs, database files, exports, URLs, fixtures, or committed environment files.
- pubmed-search-mcp is pinned to exactly 0.6.2 and accessed only through PubMedSearchMcpProvider.
- Domain modules do not import FastAPI, MCP, OpenAI, HTTPX, Typer, Rich, SQLAlchemy, or pubmed_search.
- Phase 1 excludes Web UI, MCP tools, full-text reading, evidence tables, PubTator, OpenAlex, and citation graphs.
- Default tests are offline. Real API tests require the live marker and explicit configuration.
- Project license is Apache-2.0; attribution belongs in THIRD_PARTY_NOTICES.md.

---

## File Map

- backend/pyproject.toml: package, exact dependencies, tools, and CLI entrypoint.
- backend/src/biopaper_ai/config.py: environment settings and redacted diagnostics.
- backend/src/biopaper_ai/errors.py: stable error codes.
- backend/src/biopaper_ai/domain/: identifiers, provenance, paper, plan, and deduplication.
- backend/src/biopaper_ai/application/ports/: search and plan-generator protocols.
- backend/src/biopaper_ai/application/: plan, search, and export use cases.
- backend/src/biopaper_ai/adapters/search/: upstream SDK, native NCBI, mapper, and fallback.
- backend/src/biopaper_ai/adapters/ai/: deterministic and OpenAI plan generators.
- backend/src/biopaper_ai/entrypoints/cli/: Typer parsing and Rich rendering.
- backend/tests/unit/: pure unit tests.
- backend/tests/contract/: sanitized fixed upstream responses and adapter contracts.
- backend/tests/integration/: opt-in live PubMed truthfulness checks.
- .github/workflows/backend-ci.yml: Python 3.11–3.13 offline CI.
- README.md and open-source policy files: claims, setup, security, and attribution.

---

### Task 1: Package Skeleton, Configuration, and Open-Source Baseline

**Files:**
- Create: backend/pyproject.toml
- Create: backend/src/biopaper_ai/__init__.py
- Create: backend/src/biopaper_ai/config.py
- Create: backend/src/biopaper_ai/errors.py
- Create: backend/tests/unit/test_config.py
- Create: .github/workflows/backend-ci.yml
- Create: .env.example
- Create: LICENSE
- Create: THIRD_PARTY_NOTICES.md
- Create: CONTRIBUTING.md
- Create: SECURITY.md
- Create: CODE_OF_CONDUCT.md

**Interfaces:**
- Produces: Settings.from_env() -> Settings
- Produces: Settings.diagnostic_dict() -> dict[str, object]
- Produces: BioPaperError(code, message, retry_after_seconds=None)
- Produces: console command biopaper

- [ ] **Step 1: Write failing configuration tests**

Create backend/tests/unit/test_config.py:

~~~python
from biopaper_ai.config import Settings


def test_settings_requires_ncbi_email_for_live_search(monkeypatch):
    monkeypatch.delenv("BIOPAPER_NCBI_EMAIL", raising=False)
    assert Settings.from_env().can_search_live is False


def test_diagnostics_never_expose_secrets(monkeypatch):
    monkeypatch.setenv("BIOPAPER_NCBI_EMAIL", "researcher@example.org")
    monkeypatch.setenv("BIOPAPER_NCBI_API_KEY", "ncbi-secret")
    monkeypatch.setenv("BIOPAPER_OPENAI_API_KEY", "openai-secret")
    text = repr(Settings.from_env().diagnostic_dict())
    assert "researcher@example.org" in text
    assert "ncbi-secret" not in text
    assert "openai-secret" not in text
~~~

- [ ] **Step 2: Add package metadata and verify the test fails**

backend/pyproject.toml must define Python >=3.11, Apache-2.0, the biopaper entrypoint, strict mypy, Ruff, pytest, and exact pubmed-search-mcp==0.6.2. Use an inline PEP 621 readme value for this initial package so editable installation does not depend on the root README that Task 9 creates. Runtime dependency ranges are Pydantic >=2.12,<3; pydantic-settings >=2.10,<3; HTTPX >=0.28.1,<0.29; defusedxml >=0.7.1,<0.8; Typer >=0.16,<1; Rich >=14,<15; OpenAI >=1.99,<2.

Run:

~~~bash
cd backend
python -m pip install -e . --group dev
pytest tests/unit/test_config.py -v
~~~

Expected: FAIL because biopaper_ai.config does not exist.

- [ ] **Step 3: Implement settings and errors**

Implement Settings as a pydantic-settings BaseSettings with BIOPAPER_ prefix, blank-safe ncbi_email, SecretStr keys, default model gpt-5.6-luna, and database URL sqlite:///./biopaper.db. diagnostic_dict returns only email, configured booleans, model, and database URL.

Define ErrorCode string enum values source_unavailable, rate_limited, paper_not_found, ai_key_missing, ai_output_invalid, partial_result, and invalid_search_plan. BioPaperError stores code and optional retry-after seconds.

- [ ] **Step 4: Add policy and CI files**

.env.example contains blank NCBI/OpenAI keys. THIRD_PARTY_NOTICES identifies pubmed-search-mcp 0.6.2 Apache-2.0 and lists the four researched projects without claiming vendored source. LICENSE uses the unmodified Apache 2.0 text. CONTRIBUTING documents offline default tests and required contract fixtures. SECURITY tells users to report credential exposure privately and rotate keys. CODE_OF_CONDUCT uses Contributor Covenant 2.1.

CI runs on Python 3.11, 3.12, and 3.13:

~~~yaml
- python -m pip install -e . --group dev
- ruff check .
- ruff format --check .
- mypy
- pytest -m "not live" --cov=biopaper_ai
~~~

- [ ] **Step 5: Verify and commit**

~~~bash
cd backend
ruff check .
ruff format --check .
mypy
pytest tests/unit/test_config.py -v
git add ../.github ../.env.example ../LICENSE ../THIRD_PARTY_NOTICES.md ../CONTRIBUTING.md ../SECURITY.md ../CODE_OF_CONDUCT.md .
git commit -m "chore: scaffold BioPaper AI backend"
~~~

Expected: all checks pass.

---

### Task 2: Canonical Domain Models and Strict Identifiers

**Files:**
- Create: backend/src/biopaper_ai/domain/identifiers.py
- Create: backend/src/biopaper_ai/domain/provenance.py
- Create: backend/src/biopaper_ai/domain/paper.py
- Create: backend/src/biopaper_ai/domain/search_plan.py
- Create: backend/tests/unit/domain/test_identifiers.py
- Create: backend/tests/unit/domain/test_models.py

**Interfaces:**
- Produces: normalize_doi, normalize_pmid, normalize_pmcid
- Produces: Provenance, PaperIdentifiers, Paper
- Produces: SynonymGroup, SearchFilters, SearchPlan.build

- [ ] **Step 1: Write failing identifier tests**

~~~python
import pytest
from biopaper_ai.domain.identifiers import normalize_doi, normalize_pmcid, normalize_pmid


def test_doi_is_canonical():
    assert normalize_doi("https://doi.org/10.1000/ABC.1") == "10.1000/abc.1"


def test_invalid_pmid_is_rejected():
    with pytest.raises(ValueError, match="PMID"):
        normalize_pmid("AI-made-id")


def test_pmcid_is_prefixed():
    assert normalize_pmcid("123456") == "PMC123456"
~~~

Run pytest tests/unit/domain/test_identifiers.py -v. Expected: import failure.

- [ ] **Step 2: Implement anchored identifier rules**

DOI must match 10 followed by 4–9 digits, slash, and a non-space suffix after stripping DOI URL/prefix. PMID is 1–9 digits. PMCID is PMC plus digits. Return None only for missing input; reject all other malformed values.

- [ ] **Step 3: Write model invariant tests**

~~~python
def test_paper_requires_database_provenance():
    with pytest.raises(ValueError, match="provenance"):
        Paper(title="Invented paper", provenance=())


def test_search_plan_builds_boolean_query_locally():
    plan = SearchPlan.build(
        original_query="益生菌改善肠道屏障",
        topic="probiotics and intestinal barrier",
        groups=(
            SynonymGroup(terms=("probiotic", "Lactobacillus")),
            SynonymGroup(terms=("intestinal barrier", "tight junction")),
        ),
        mesh_terms=("Probiotics",),
        filters=SearchFilters(year_from=2021, year_to=2026),
        generator="deterministic",
    )
    assert plan.boolean_query == (
        "(probiotic OR Lactobacillus) AND "
        '("intestinal barrier" OR "tight junction")'
    )
~~~

- [ ] **Step 4: Implement frozen Pydantic models**

SourceName contains pubmed, pmc, europe_pmc, openalex, and pubtator. Paper rejects empty title and provenance. primary_id uses DOI, PMID, PMCID, then source plus record ID; it never hashes the title. SynonymGroup quotes multiword terms, escapes quotes, and joins with OR. SearchPlan.build requires at least one group and constructs Boolean syntax locally.

- [ ] **Step 5: Verify and commit**

~~~bash
pytest tests/unit/domain -v
ruff check .
mypy
git add src/biopaper_ai/domain tests/unit/domain
git commit -m "feat: add canonical literature domain models"
~~~

---

### Task 3: Provenance-Preserving Deduplication

**Files:**
- Create: backend/src/biopaper_ai/domain/deduplication.py
- Create: backend/tests/unit/domain/test_deduplication.py

**Interfaces:**
- Produces: DeduplicationResult and AmbiguousMatch
- Produces: deduplicate_papers(papers) -> DeduplicationResult

- [ ] **Step 1: Write failing tests**

Test exact DOI merge, PMID merge, PMCID merge, preservation of both provenance records, selection of the longer abstract, stable ordering, and this conflict:

~~~python
def test_conflicting_ids_are_not_title_merged():
    result = deduplicate_papers([
        paper(title="Same title", year=2024, doi="10.1000/a", pmid="1"),
        paper(title="Same title", year=2024, doi="10.1000/b", pmid="2"),
    ])
    assert len(result.papers) == 2
    assert len(result.ambiguous) == 1
~~~

Run the test. Expected: module import failure.

- [ ] **Step 2: Implement two-pass deduplication**

First merge records sharing DOI, PMID, or PMCID. Never merge two non-null conflicting values of the same identifier type. Then create normalized title plus year candidates. If strict IDs conflict, keep records separate and emit AmbiguousMatch. Preserve first-seen order, union all provenance, and retain the longest non-empty abstract.

- [ ] **Step 3: Verify and commit**

~~~bash
pytest tests/unit/domain/test_deduplication.py -v
ruff check .
mypy
git add src/biopaper_ai/domain/deduplication.py tests/unit/domain/test_deduplication.py
git commit -m "feat: add provenance-preserving deduplication"
~~~

---

### Task 4: Search Provider Contract and Native PubMed Fallback

**Files:**
- Create: backend/src/biopaper_ai/application/ports/search_provider.py
- Create: backend/src/biopaper_ai/adapters/search/pubmed_mapper.py
- Create: backend/src/biopaper_ai/adapters/search/native_pubmed.py
- Create: backend/tests/contract/fixtures/ncbi_esearch.json
- Create: backend/tests/contract/fixtures/ncbi_efetch.xml
- Create: backend/tests/contract/test_native_pubmed.py
- Create: backend/tests/unit/adapters/test_pubmed_mapper.py

**Interfaces:**
- Produces: SearchProvider.search(plan, limit) -> ProviderResult
- Produces: ProviderResult, ProviderFailure, SourceCount
- Produces: map_pubmed_record(record, retrieved_at) -> Paper
- Produces: NativePubMedProvider

- [ ] **Step 1: Define the provider protocol and sanitized fixtures**

SearchProvider is an async Protocol. ProviderResult contains immutable papers, source counts, and failures. The ESearch fixture contains two fake-but-valid numeric IDs. The EFetch XML fixture contains two structured PubmedArticle records with title, abstract, authors, journal, year, publication types, PMID, DOI, and one PMCID.

- [ ] **Step 2: Write the offline contract test**

Using respx, mock ESearch GET and batched EFetch POST. Assert the request contains tool=BioPaperAI, email, retmode=json, retmax, and the reviewed Boolean query. Assert resulting PMIDs exactly match the fixture and every paper has PubMed provenance and a PubMed URL.

Run pytest tests/contract/test_native_pubmed.py -v. Expected: import failure.

- [ ] **Step 3: Implement mapper and provider**

The mapper rejects missing PMID, title, or provenance URL and accepts absent DOI, PMCID, year, journal, or abstract. NativePubMedProvider uses official ESearch and EFetch endpoints, sends one batch POST, parses XML with defusedxml, and never returns a partially parsed paper.

Convert 429 into rate_limited failure carrying Retry-After. Convert timeout and 5xx into source_unavailable. Add an injected monotonic rate limiter using 3 requests/second without a key and 10 with a key; unit tests inject fake sleep and clock.

- [ ] **Step 4: Verify and commit**

~~~bash
pytest tests/unit/adapters/test_pubmed_mapper.py tests/contract/test_native_pubmed.py -v
ruff check .
mypy
git add src/biopaper_ai/application/ports src/biopaper_ai/adapters/search tests
git commit -m "feat: add native PubMed search provider"
~~~

---

### Task 5: Pinned Upstream SDK Adapter and Fallback Composition

**Files:**
- Create: backend/src/biopaper_ai/adapters/search/pubmed_search_mcp.py
- Create: backend/src/biopaper_ai/adapters/search/fallback.py
- Create: backend/tests/contract/fixtures/pubmed_search_mcp_result.json
- Create: backend/tests/contract/test_pubmed_search_mcp.py
- Create: backend/tests/unit/adapters/test_fallback_provider.py

**Interfaces:**
- Produces: PubMedSearchMcpProvider
- Produces: create_pubmed_search_mcp_provider(settings)
- Produces: FallbackSearchProvider(primary, fallback)

- [ ] **Step 1: Capture and test the exact 0.6.2 contract**

Create a sanitized fixture containing only article fields observed from pubmed-search-mcp 0.6.2. Inject a fake PubMedSearchClient. Assert unified_search receives the reviewed Boolean query, limit, sources="pubmed", output_format="json", and explicit filter serialization. Assert mapped identifiers and source record IDs match the fixture.

Run pytest tests/contract/test_pubmed_search_mcp.py -v. Expected: module import failure.

- [ ] **Step 2: Implement adapter**

The factory builds PubMedSearchConfig from redacted Settings and extracts SecretStr values only at the call boundary. Invalid individual records become per-record failures and are omitted. Upstream exceptions become source_unavailable. No upstream object escapes the adapter.

- [ ] **Step 3: Implement and test fallback rules**

- Return non-empty primary results without calling fallback.
- Call fallback only when primary raises or returns zero papers with source_unavailable.
- Do not call fallback for a valid empty search.
- Preserve the primary failure when fallback succeeds.

- [ ] **Step 4: Verify version and commit**

~~~bash
python -c "import importlib.metadata as m; assert m.version('pubmed-search-mcp') == '0.6.2'"
pytest tests/contract/test_pubmed_search_mcp.py tests/unit/adapters/test_fallback_provider.py -v
ruff check .
mypy
git add src/biopaper_ai/adapters/search tests
git commit -m "feat: adapt pinned PubMed SDK with fallback"
~~~

---

### Task 6: Reviewable Search Plan Generation

**Files:**
- Create: backend/src/biopaper_ai/application/ports/plan_generator.py
- Create: backend/src/biopaper_ai/application/plan_search.py
- Create: backend/src/biopaper_ai/adapters/ai/deterministic_plan.py
- Create: backend/src/biopaper_ai/adapters/ai/openai_plan.py
- Create: backend/tests/unit/application/test_plan_search.py
- Create: backend/tests/contract/test_openai_plan.py

**Interfaces:**
- Produces: PlanGenerator.generate(query) -> SearchPlan
- Produces: PlanSearch.execute(query, use_ai) -> SearchPlan
- Produces: DeterministicPlanGenerator and OpenAIPlanGenerator

- [ ] **Step 1: Write deterministic-generator tests**

For an English query containing 2021-2026, assert extraction of the year range, a conservative term group, no invented MeSH terms, and generator="deterministic". For Chinese input, preserve the original query as a quoted group and add a warning that no translation was performed.

- [ ] **Step 2: Implement PlanGenerator and deterministic path**

The async protocol returns SearchPlan. The deterministic generator extracts a single YYYY-YYYY range, removes it from terms, and never labels free text as MeSH.

- [ ] **Step 3: Write OpenAI Structured Outputs contract test**

Inject a fake AsyncOpenAI response parsed into:

~~~python
class SearchPlanDraft(BaseModel):
    topic: str
    synonym_groups: list[list[str]]
    mesh_candidates: list[str]
    year_from: int | None
    year_to: int | None
    species: list[str]
    study_types: list[str]
~~~

Assert the original query is sent unchanged, MeSH values are labeled candidates, organism/date/study constraints are requested, and no paper identifiers are requested. A malformed response raises ai_output_invalid and does not create a partial plan.

- [ ] **Step 4: Implement OpenAI adapter and no-key fallback**

Use AsyncOpenAI.responses.parse with SearchPlanDraft. Ignore any model Boolean syntax, ID, DOI, URL, or source record; build Boolean syntax locally. PlanSearch uses OpenAI only when configured and use_ai is true. Otherwise it returns the deterministic plan with a warning and never instantiates the OpenAI client.

- [ ] **Step 5: Verify and commit**

~~~bash
pytest tests/unit/application/test_plan_search.py tests/contract/test_openai_plan.py -v
ruff check .
mypy
git add src/biopaper_ai/application src/biopaper_ai/adapters/ai tests
git commit -m "feat: generate reviewable biomedical search plans"
~~~

---

### Task 7: Search Orchestration, Local Filters, and Explainable Ranking

**Files:**
- Create: backend/src/biopaper_ai/application/search_papers.py
- Create: backend/tests/unit/application/test_search_papers.py

**Interfaces:**
- Produces: SearchPapers.execute(plan, limit) -> SearchRun
- Produces: SearchRun with plan, hits, source counts, failures, and ambiguous matches

- [ ] **Step 1: Write orchestration tests**

Assert provider receives SearchPlan rather than raw natural language; year/species/type filters run locally; DOI duplicates merge; ambiguous title matches remain separate; partial failures remain visible; stable ranking reasons describe title match, abstract match, and recency.

- [ ] **Step 2: Implement pure filters and ranking**

paper_matches_filters handles only explicitly populated filters. Ranking order is title contains a plan term, abstract contains a plan term, newer year, then stable provider position. Each SearchHit stores ranking_reasons. Do not call the score scientific relevance.

Generate run_id as UUID5 from canonical plan JSON plus an injected execution timestamp. The injected clock makes tests deterministic.

- [ ] **Step 3: Verify and commit**

~~~bash
pytest tests/unit/application/test_search_papers.py -v
ruff check .
mypy
git add src/biopaper_ai/application/search_papers.py tests/unit/application/test_search_papers.py
git commit -m "feat: orchestrate grounded literature searches"
~~~

---

### Task 8: Safe Export and Typer CLI

**Files:**
- Create: backend/src/biopaper_ai/application/export_results.py
- Create: backend/src/biopaper_ai/entrypoints/cli/app.py
- Create: backend/src/biopaper_ai/entrypoints/cli/render.py
- Create: backend/tests/unit/application/test_export_results.py
- Create: backend/tests/unit/cli/test_cli.py

**Interfaces:**
- Produces: export_search_run(run, format, destination) -> Path
- Produces CLI commands: plan, search, doctor

- [ ] **Step 1: Write export tests**

JSON contains plan, identifiers, provenance URLs, failures, and ambiguous matches. CSV contains pmid, pmcid, doi, title, year, journal, abstract, source_names, and source_urls. Fake NCBI/OpenAI secret values must be absent from both outputs.

- [ ] **Step 2: Implement atomic export**

Write a sibling temporary file, flush and close, then replace destination. Use UTF-8 JSON and UTF-8 with BOM CSV. Refuse unknown formats. Export only domain/application values, never Settings.

- [ ] **Step 3: Write CLI tests**

Using CliRunner and injected dependencies, test:

- plan --json does not call search.
- search --non-interactive without --accept-plan exits 2.
- search --accept-plan --no-ai never calls OpenAI.
- doctor reports configured flags without secret values.
- partial failure with papers warns and exits zero.
- source failure with no papers exits non-zero.
- output path creates JSON or CSV with provenance.

- [ ] **Step 4: Implement thin CLI and rendering**

Interactive search displays SearchPlan, asks for confirmation, and performs no network call on rejection. Non-interactive search requires --accept-plan. app.py owns factories and arguments; render.py owns Rich tables. Neither command handler imports NCBI or upstream SDK record types.

- [ ] **Step 5: Verify and commit**

~~~bash
pytest tests/unit/application/test_export_results.py tests/unit/cli/test_cli.py -v
biopaper --help
biopaper doctor
git add src/biopaper_ai/application/export_results.py src/biopaper_ai/entrypoints tests
git commit -m "feat: add safe export and BioPaper CLI"
~~~

---

### Task 9: Live Truthfulness Gate and Phase 1 Documentation

**Files:**
- Create: backend/tests/integration/test_live_pubmed.py
- Create: backend/tests/fixtures/truth_queries.json
- Create: scripts/verify_phase1.ps1
- Create: README.md
- Modify: THIRD_PARTY_NOTICES.md

**Interfaces:**
- Produces: reproducible offline gate and opt-in live verification.

- [ ] **Step 1: Define live truth queries**

truth_queries.json contains:

~~~json
[
  {"query": "Lactobacillus rhamnosus intestinal immunity mice 2021-2026", "limit": 5},
  {"query": "BRCA1 breast cancer review 2024", "limit": 5}
]
~~~

Do not store expected IDs because databases change.

- [ ] **Step 2: Write opt-in live verification**

Mark live and skip without BIOPAPER_NCBI_EMAIL. For every query, generate a deterministic plan, search, require at least one PubMed-provenanced paper, locally validate IDs and allowlisted URL hosts, then batch EFetch the reported PMIDs and assert NCBI returns every reported PMID.

- [ ] **Step 3: Add offline release script**

scripts/verify_phase1.ps1 runs, with ErrorActionPreference Stop:

~~~powershell
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest -m 'not live' --cov=biopaper_ai --cov-report=term-missing
python -m pip check
biopaper --help
biopaper doctor
~~~

It does not run live tests.

- [ ] **Step 4: Write README**

Document problem, trust boundary, Python 3.11+ setup, .env names, no-AI use, plan/search/export examples, NCBI limits, live test command, Phase 1 limitations, four-week roadmap, attribution, license, and non-diagnostic disclaimer. Use the Lactobacillus Chinese query as the primary example. Do not claim full text, evidence tables, PubTator, OpenAlex graphs, MCP, or Web UI are complete.

- [ ] **Step 5: Run gates**

~~~powershell
.\scripts\verify_phase1.ps1
Push-Location backend
python -m pytest -m live tests/integration/test_live_pubmed.py -v
Pop-Location
git diff --check
~~~

Expected: offline gate passes. Live test must pass before public GitHub launch; a skip means publication remains blocked until BIOPAPER_NCBI_EMAIL is configured and the test succeeds.

- [ ] **Step 6: Commit**

~~~bash
git add backend/tests/integration backend/tests/fixtures scripts README.md THIRD_PARTY_NOTICES.md
git commit -m "docs: add Phase 1 truthfulness release gate"
~~~

---

## Phase 1 Completion Check

- biopaper plan works without any key.
- biopaper search --no-ai works with only BIOPAPER_NCBI_EMAIL.
- Search executes the reviewed Boolean query, not raw natural language.
- Every result has database provenance and validated source identifiers.
- The pinned SDK and native fallback have passing offline contract tests.
- Secrets are absent from diagnostics, fixtures, and exports.
- JSON and CSV preserve source URLs and partial failures.
- Offline CI passes on Python 3.11, 3.12, and 3.13.
- The live truthfulness test passes before GitHub launch.
- README claims match only implemented Phase 1 behavior.
