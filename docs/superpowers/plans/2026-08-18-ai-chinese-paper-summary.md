# AI Chinese Paper Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in, source-grounded Chinese paper summaries that prefer reusable PMC full text and visibly fall back to PubMed abstracts.

**Architecture:** Keep full-text retrieval, JATS parsing, evidence construction, OpenAI summarization, and CLI orchestration behind separate application ports. Extend each immutable `SearchHit` with an optional audited summary outcome so existing searches remain compatible while JSON/CSV and Rich rendering can distinguish database content from AI-generated content.

**Tech Stack:** Python 3.11+, Pydantic 2, HTTPX 0.28, defusedxml, OpenAI Responses Structured Outputs, Typer, Rich, pytest, pytest-asyncio, respx, Ruff, strict mypy.

## Global Constraints

- BioPaper AI remains MIT licensed; `pubmed-search-mcp==0.6.2` remains an external Apache-2.0 dependency.
- Full text may be retrieved only from `https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/` with `metadataPrefix=pmc`; do not scrape HTML or publisher pages.
- PMC requests are sequential, paced to at most 3 requests/second, use 10-second connect and 30-second other timeouts, and stop after 3 attempts.
- Retry timeout, HTTP 429, and HTTP 5xx; honor numeric or HTTP-date `Retry-After` capped at 60 seconds; do not retry ordinary HTTP 4xx.
- Stream decompressed PMC responses and reject payloads larger than 20 MiB before XML parsing.
- Use `defusedxml`; never accept DTDs, external entities, entity expansion, wrong PMCID records, or unexpected OAI/JATS roots.
- Evidence sent to OpenAI is at most 100,000 Unicode characters and at most 24,000 characters per section, truncated at paragraph boundaries.
- Do not export or log PMC full text, evidence-pack text, secrets, raw upstream exceptions, raw model output, or prompts.
- AI output cannot contain paper identifiers or provenance. PMID, PMCID, DOI, authors, year, and source URL remain application-owned.
- Missing scientific information must be represented in generated fields as `原文未明确说明`, never guessed.
- `--summarize` is opt-in; default `--summary-limit` is 3; `--no-ai --summarize` means deterministic planning plus AI summarization.
- Run all non-live tests offline by default. Live PMC verification is opt-in and must not call OpenAI.
- Preserve Python 3.11, 3.12, and 3.13 compatibility, Ruff formatting, strict mypy, and the existing Phase 1 search trust boundary.

---

## File Map

### New production files

- `backend/src/biopaper_ai/domain/summary.py` — immutable summary, full-text, evidence, and outcome models.
- `backend/src/biopaper_ai/application/ports/full_text_provider.py` — full-text fetch result and provider protocol.
- `backend/src/biopaper_ai/application/ports/paper_summarizer.py` — summary provider protocol.
- `backend/src/biopaper_ai/application/evidence.py` — deterministic full-text/abstract evidence construction.
- `backend/src/biopaper_ai/application/summarize_papers.py` — per-hit summary orchestration.
- `backend/src/biopaper_ai/adapters/fulltext/__init__.py` — full-text adapter package marker.
- `backend/src/biopaper_ai/adapters/fulltext/jats.py` — safe OAI/JATS parsing and section classification.
- `backend/src/biopaper_ai/adapters/fulltext/pmc_oai.py` — paced, bounded PMC OAI-PMH client.
- `backend/src/biopaper_ai/adapters/ai/openai_summary.py` — strict OpenAI summary adapter.

### Modified production files

- `backend/src/biopaper_ai/application/search_papers.py` — optional `SearchHit.summary_outcome`.
- `backend/src/biopaper_ai/application/export_results.py` — audited summary CSV fields; JSON follows owned models.
- `backend/src/biopaper_ai/entrypoints/cli/app.py` — `--summarize`, `--summary-limit`, dependency composition, early configuration gate.
- `backend/src/biopaper_ai/entrypoints/cli/render.py` — separate AI-summary rendering.
- `backend/pyproject.toml` — version bump to `0.2.0`; no new runtime dependency.
- `README.md` and `THIRD_PARTY_NOTICES.md` — usage, privacy, PMC policy, limitations, and service attribution.

### New tests and fixtures

- `backend/tests/unit/domain/test_summary_models.py`
- `backend/tests/unit/application/test_evidence.py`
- `backend/tests/unit/application/test_summarize_papers.py`
- `backend/tests/unit/adapters/fulltext/test_jats.py`
- `backend/tests/contract/test_pmc_oai.py`
- `backend/tests/contract/test_openai_summary.py`
- `backend/tests/contract/fixtures/pmc_oai_fulltext.xml`
- `backend/tests/contract/fixtures/pmc_oai_unavailable.xml`
- `backend/tests/integration/test_live_pmc.py`

### Modified tests

- `backend/tests/unit/application/test_search_papers.py`
- `backend/tests/unit/application/test_export_results.py`
- `backend/tests/unit/cli/test_cli.py`
- `scripts/verify_phase1.ps1` — no edit required; its existing `pytest -m 'not live'` discovery automatically includes every new offline test.

---

### Task 1: Immutable Summary Models and Ports

**Files:**
- Create: `backend/src/biopaper_ai/domain/summary.py`
- Create: `backend/src/biopaper_ai/application/ports/full_text_provider.py`
- Create: `backend/src/biopaper_ai/application/ports/paper_summarizer.py`
- Modify: `backend/src/biopaper_ai/application/search_papers.py`
- Test: `backend/tests/unit/domain/test_summary_models.py`
- Test: `backend/tests/unit/application/test_search_papers.py`

**Interfaces:**
- Consumes: existing frozen `Paper`, `SearchHit`, and validated `HttpUrl` patterns.
- Produces: `SectionCategory`, `FullTextSection`, `FullTextDocument`, `EvidenceScope`, `EvidencePack`, `ChinesePaperSummary`, `SummaryStatus`, `SummaryOutcome`, `FullTextStatus`, `FullTextResult`, `FullTextProvider.fetch(paper)`, and `PaperSummarizer.summarize(paper, evidence)`.

- [ ] **Step 1: Write failing domain and compatibility tests**

Create tests that exercise the exact invariants:

```python
def test_successful_summary_outcome_requires_grounded_summary() -> None:
    summary = ChinesePaperSummary(
        brief_summary=("第一句。", "第二句。", "第三句。"),
        research_objective="研究目的",
        experimental_design="实验设计",
        main_results="主要结果",
        significance="研究意义",
        limitations="原文未明确说明",
    )
    outcome = SummaryOutcome(
        status=SummaryStatus.SUCCESS,
        evidence_scope=EvidenceScope.PMC_FULL_TEXT,
        summary=summary,
        model="test-model",
        generated_at=datetime(2026, 8, 18, tzinfo=UTC),
        evidence_digest="a" * 64,
        source_url="https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/",
        rights_statement="CC BY 4.0",
        truncated=False,
    )
    assert outcome.summary is summary


@pytest.mark.parametrize("count", [0, 1, 2, 6])
def test_brief_summary_requires_three_to_five_sentences(count: int) -> None:
    with pytest.raises(ValidationError):
        ChinesePaperSummary(
            brief_summary=tuple("句子。" for _ in range(count)),
            research_objective="目的",
            experimental_design="设计",
            main_results="结果",
            significance="意义",
            limitations="局限",
        )


def test_search_hit_without_requested_summary_remains_compatible() -> None:
    hit = SearchHit(paper=paper(), ranking_reasons=("title term match: probiotic",))
    assert hit.summary_outcome is None
```

Also assert: models are frozen; blank section/summary strings fail; available `FullTextResult` requires a document; unavailable/failed results prohibit a document; success outcome requires a non-`none` scope and all audit fields; skipped/failed outcomes prohibit a summary and require a safe note; evidence digest is exactly 64 lowercase hexadecimal characters.

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
Set-Location backend
python -m pytest tests/unit/domain/test_summary_models.py tests/unit/application/test_search_papers.py -v
```

Expected: collection fails because `biopaper_ai.domain.summary` and the new ports do not exist.

- [ ] **Step 3: Implement the minimal frozen models and protocols**

Use `StrEnum`, `ConfigDict(frozen=True)`, strict field validators, and one model-level invariant per result/outcome:

```python
class SectionCategory(StrEnum):
    ABSTRACT = "abstract"
    INTRODUCTION = "introduction"
    METHODS = "methods"
    RESULTS = "results"
    DISCUSSION = "discussion"
    LIMITATIONS = "limitations"
    CONCLUSION = "conclusion"
    OTHER = "other"


class EvidenceScope(StrEnum):
    PMC_FULL_TEXT = "pmc_full_text"
    PUBMED_ABSTRACT = "pubmed_abstract"
    NONE = "none"


class SummaryStatus(StrEnum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


class ChinesePaperSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    brief_summary: Annotated[tuple[str, ...], Field(min_length=3, max_length=5)]
    research_objective: str
    experimental_design: str
    main_results: str
    significance: str
    limitations: str
```

Define `FullTextProvider` and `PaperSummarizer` as structural protocols with these exact signatures:

```python
class FullTextProvider(Protocol):
    async def fetch(self, paper: Paper) -> FullTextResult: ...


class PaperSummarizer(Protocol):
    async def summarize(
        self, paper: Paper, evidence: EvidencePack
    ) -> ChinesePaperSummary: ...
```

Give `FullTextResult` exact `available(document)`, `unavailable(note)`, and
`failed(note)` class methods so adapters never construct contradictory status/document
combinations. Each factory must flow through the model-level invariant rather than
using `model_construct`.

Modify `SearchHit`:

```python
summary_outcome: SummaryOutcome | None = None
```

- [ ] **Step 4: Run focused tests and static checks**

Run:

```powershell
python -m pytest tests/unit/domain/test_summary_models.py tests/unit/application/test_search_papers.py -v
python -m ruff check src/biopaper_ai/domain/summary.py src/biopaper_ai/application/ports tests/unit/domain/test_summary_models.py
python -m mypy
```

Expected: all focused tests pass; Ruff and strict mypy pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/biopaper_ai/domain/summary.py backend/src/biopaper_ai/application/ports backend/src/biopaper_ai/application/search_papers.py backend/tests/unit/domain/test_summary_models.py backend/tests/unit/application/test_search_papers.py
git commit -m "feat: model grounded paper summaries"
```

---

### Task 2: Safe JATS Parsing and Deterministic Evidence Packs

**Files:**
- Create: `backend/src/biopaper_ai/adapters/fulltext/__init__.py`
- Create: `backend/src/biopaper_ai/adapters/fulltext/jats.py`
- Create: `backend/src/biopaper_ai/application/evidence.py`
- Create: `backend/tests/unit/adapters/fulltext/test_jats.py`
- Create: `backend/tests/unit/application/test_evidence.py`
- Create: `backend/tests/contract/fixtures/pmc_oai_fulltext.xml`
- Create: `backend/tests/contract/fixtures/pmc_oai_unavailable.xml`

**Interfaces:**
- Consumes: Task 1 `FullTextDocument`, `FullTextSection`, `FullTextResult`, `EvidencePack`, `EvidenceScope`, and existing `Paper`.
- Produces: `parse_pmc_oai_record(payload, requested_pmcid, source_url, retrieved_at) -> FullTextDocument`, `PmcRecordUnavailable`, `InvalidPmcResponse`, and `build_evidence_pack(paper, full_text_result) -> tuple[EvidencePack | None, str | None]`.

- [ ] **Step 1: Write a realistic reusable JATS fixture and failing parser tests**

The fixture must include OAI root/record metadata, PMCID `PMC12124693`, license URI/text, abstract, introduction, methods, results, discussion with nested limitations, conclusion, acknowledgements, and references. Use short synthetic prose rather than copyrighted article text.

Test exact extraction and exclusions:

```python
def test_parser_returns_only_requested_reusable_jats_sections() -> None:
    document = parse_pmc_oai_record(
        (FIXTURES / "pmc_oai_fulltext.xml").read_bytes(),
        requested_pmcid="PMC12124693",
        source_url=PMC_URL,
        retrieved_at=NOW,
    )
    assert document.pmcid == "PMC12124693"
    assert document.rights_statement == "CC BY 4.0"
    assert [section.category for section in document.sections] == [
        SectionCategory.ABSTRACT,
        SectionCategory.INTRODUCTION,
        SectionCategory.METHODS,
        SectionCategory.RESULTS,
        SectionCategory.DISCUSSION,
        SectionCategory.LIMITATIONS,
        SectionCategory.CONCLUSION,
    ]
    joined = " ".join(section.text for section in document.sections)
    assert "Acknowledgement sentinel" not in joined
    assert "Reference sentinel" not in joined
```

Add parametrized tests for truncated XML, forbidden entity/DOCTYPE, wrong OAI root, missing JATS article, wrong PMCID, and OAI `<error>`.

- [ ] **Step 2: Write failing evidence-pack tests**

```python
def test_full_text_evidence_is_prioritized_and_bounded() -> None:
    evidence, note = build_evidence_pack(paper_with_abstract(), available_result())
    assert evidence is not None
    assert evidence.scope is EvidenceScope.PMC_FULL_TEXT
    assert len(evidence.text) <= 100_000
    assert all(len(block) <= 24_000 for block in evidence.text.split("\n\n## "))
    assert evidence.evidence_digest == hashlib.sha256(
        evidence.text.encode("utf-8")
    ).hexdigest()
    assert note is None


def test_unavailable_full_text_falls_back_to_abstract() -> None:
    evidence, note = build_evidence_pack(paper_with_abstract(), unavailable_result())
    assert evidence is not None
    assert evidence.scope is EvidenceScope.PUBMED_ABSTRACT
    assert "仅基于摘要" in note
```

Also test paragraph-boundary truncation, category priority, missing full text plus missing abstract returning `(None, safe_note)`, and absence of full-text/evidence body in `repr` only if models customize repr; do not add custom repr unless necessary.

- [ ] **Step 3: Run tests to verify RED**

```powershell
python -m pytest tests/unit/adapters/fulltext/test_jats.py tests/unit/application/test_evidence.py -v
```

Expected: import errors for `jats` and `evidence` modules.

- [ ] **Step 4: Implement JATS parsing with defusedxml**

Use local-name helpers so namespace prefixes do not matter. Reject rather than guess:

```python
def parse_pmc_oai_record(
    payload: bytes,
    *,
    requested_pmcid: str,
    source_url: str,
    retrieved_at: datetime,
) -> FullTextDocument:
    try:
        root = DefusedElementTree.fromstring(payload)
    except (ParseError, DefusedXmlException) as error:
        raise InvalidPmcResponse from error
    if _local_name(root.tag) != "OAI-PMH":
        raise InvalidPmcResponse
    if _first_descendant(root, "error") is not None:
        raise PmcRecordUnavailable
    article = _first_descendant(root, "article")
    if article is None:
        raise PmcRecordUnavailable
    returned = _article_id(article, "pmcid")
    if returned != requested_pmcid:
        raise InvalidPmcResponse
    sections = _extract_sections(article)
    if not sections:
        raise PmcRecordUnavailable
    return FullTextDocument(
        pmcid=returned,
        source_url=source_url,
        rights_statement=_rights_statement(article),
        sections=sections,
        retrieved_at=retrieved_at,
    )
```

Normalize whitespace, preserve paragraph order, split nested limitations from discussion, and classify section titles with fixed case-folded term sets. Never use fuzzy classification.

- [ ] **Step 5: Implement deterministic evidence construction**

Use fixed category priority, a 100,000-character total limit, 24,000-character per-section limit, paragraph-boundary truncation, SHA-256, and abstract fallback. Evidence text must contain explicit delimiters such as `## Methods` but no XML.

- [ ] **Step 6: Run focused tests and static checks**

```powershell
python -m pytest tests/unit/adapters/fulltext/test_jats.py tests/unit/application/test_evidence.py -v
python -m ruff check src/biopaper_ai/adapters/fulltext src/biopaper_ai/application/evidence.py tests/unit/adapters/fulltext tests/unit/application/test_evidence.py
python -m mypy
```

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add backend/src/biopaper_ai/adapters/fulltext backend/src/biopaper_ai/application/evidence.py backend/tests/unit/adapters/fulltext backend/tests/unit/application/test_evidence.py backend/tests/contract/fixtures/pmc_oai_fulltext.xml backend/tests/contract/fixtures/pmc_oai_unavailable.xml
git commit -m "feat: build safe PMC evidence packs"
```

---

### Task 3: Bounded PMC OAI-PMH Full-Text Provider

**Files:**
- Create: `backend/src/biopaper_ai/adapters/fulltext/pmc_oai.py`
- Create: `backend/tests/contract/test_pmc_oai.py`

**Interfaces:**
- Consumes: Task 1 `FullTextProvider` result models and Task 2 `parse_pmc_oai_record` exceptions.
- Produces: `PMC_OAI_URL`, dependency-injected `PmcOaiFullTextProvider`, and `fetch(paper) -> FullTextResult`; constructor dependencies use the same `Clock`, `Sleep`, `Now`, and `Jitter` callable types as `NativePubMedProvider`.

- [ ] **Step 1: Write failing offline contract tests**

Cover successful request parameters and identity:

```python
@pytest.mark.asyncio
async def test_pmc_oai_fetches_only_the_requested_reusable_record() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(PMC_OAI_URL).mock(
            return_value=httpx.Response(200, content=FULLTEXT_FIXTURE)
        )
        async with httpx.AsyncClient() as client:
            result = await PmcOaiFullTextProvider(
                Settings(ncbi_email="maintainer@example.test"),
                client=client,
                now=lambda: NOW,
            ).fetch(paper(pmcid="PMC12124693"))
    request = route.calls[0].request
    assert request.url.params["verb"] == "GetRecord"
    assert request.url.params["identifier"] == (
        "oai:pubmedcentral.nih.gov:12124693"
    )
    assert request.url.params["metadataPrefix"] == "pmc"
    assert "maintainer@example.test" in request.headers["User-Agent"]
    assert result.status is FullTextStatus.AVAILABLE
    assert result.document is not None
    assert result.document.pmcid == "PMC12124693"
```

Add exact tests for: no PMCID produces no HTTP call; OAI unavailable record returns `UNAVAILABLE`; malformed/hostile/wrong-PMCID payload returns `FAILED` with static note; decompressed body over 20 MiB returns `FAILED`; timeout/429/500 retry exactly 3 attempts; numeric and HTTP-date Retry-After capped at 60; ordinary 400 attempted once; request/response/exception secrets absent from result and provider repr; request pacing is at least 1/3 second.

- [ ] **Step 2: Run contract tests to verify RED**

```powershell
python -m pytest tests/contract/test_pmc_oai.py -v
```

Expected: collection fails because `pmc_oai.py` does not exist.

- [ ] **Step 3: Implement the provider and streamed size boundary**

Use the exact fixed endpoint and dependency-injected clock/sleep/jitter. Build parameters locally from normalized PMCID digits. The core response path must resemble:

```python
async with client.stream("GET", PMC_OAI_URL, params=params) as response:
    response.raise_for_status()
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            return FullTextResult.failed("PMC returned an oversized response")
        chunks.append(chunk)
payload = b"".join(chunks)
```

Do not include exception type or message in public notes. Return fixed notes:

- unavailable: `PMC reusable full text was not available.`
- invalid/network failed: `PMC full text could not be retrieved safely.`

Use a private `_request` loop for timeout/429/5xx and a private lock-based `_pace` method. The default client timeout is `httpx.Timeout(30.0, connect=10.0)`.

- [ ] **Step 4: Run contract tests, Ruff, and mypy**

```powershell
python -m pytest tests/contract/test_pmc_oai.py -v
python -m ruff check src/biopaper_ai/adapters/fulltext/pmc_oai.py tests/contract/test_pmc_oai.py
python -m mypy
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/biopaper_ai/adapters/fulltext/pmc_oai.py backend/tests/contract/test_pmc_oai.py
git commit -m "feat: retrieve reusable PMC full text"
```

---

### Task 4: Strict OpenAI Chinese Summary Adapter

**Files:**
- Create: `backend/src/biopaper_ai/adapters/ai/openai_summary.py`
- Create: `backend/tests/contract/test_openai_summary.py`

**Interfaces:**
- Consumes: Task 1 `PaperSummarizer`, `Paper`, `EvidencePack`, and `ChinesePaperSummary`.
- Produces: `ChineseSummaryDraft`, `OpenAIPaperSummarizer(client, model)`, `OpenAIPaperSummarizer.from_api_key(api_key, model)`, and sanitized `BioPaperError(ErrorCode.AI_OUTPUT_INVALID, "OpenAI returned an invalid structured paper summary.")` failures.

- [ ] **Step 1: Write failing Structured Outputs contract tests**

```python
@pytest.mark.asyncio
async def test_summary_adapter_sends_only_grounded_evidence_and_returns_chinese_schema() -> None:
    draft = ChineseSummaryDraft(
        brief_summary=["研究评估了干预。", "研究采用小鼠模型。", "作者报告指标改善。"],
        research_objective="评估干预效果。",
        experimental_design="采用小鼠实验。",
        main_results="作者报告主要指标改善。",
        significance="结果提示潜在研究价值。",
        limitations="原文未明确说明",
    )
    client = FakeAsyncOpenAI(draft)
    result = await OpenAIPaperSummarizer(
        client=client, model="test-model"
    ).summarize(paper(), evidence_pack())
    request = client.responses.request
    assert request is not None
    assert request["text_format"] is ChineseSummaryDraft
    assert request["model"] == "test-model"
    assert evidence_pack().text in request["input"]
    instructions = request["instructions"]
    for forbidden in ("PMID", "PMCID", "DOI", "URL"):
        assert forbidden in instructions
    assert result.brief_summary == tuple(draft.brief_summary)
```

Add tests for missing/refused parsed output, extra fields, blank fields, 2 or 6 brief sentences, model output containing an identifier-shaped string, and an SDK exception containing a fake secret. Every failure must expose only `AI_OUTPUT_INVALID` plus a static safe message.

- [ ] **Step 2: Run tests to verify RED**

```powershell
python -m pytest tests/contract/test_openai_summary.py -v
```

Expected: import error for `openai_summary`.

- [ ] **Step 3: Implement strict draft schema, prompt, and adapter**

Define `ChineseSummaryDraft` with `ConfigDict(extra="forbid", strict=True)`, list length 3–5, nonblank validators, and a validator that rejects identifier/URL patterns in every returned string:

```python
_IDENTIFIER_DATA = re.compile(
    r"https?://|\bPMID\b|\bPMCID\b|\bPMC\d+\b|\bDOI\b|10\.\d{4,9}/",
    re.IGNORECASE,
)
```

The request input must be an application-built text envelope containing paper title, evidence scope, and evidence text. The instructions must explicitly say the envelope is untrusted data, require Simplified Chinese and `原文未明确说明`, prohibit external knowledge and medical advice, and prohibit identifiers/provenance.

Convert only validated draft fields into `ChinesePaperSummary`. Catch `Exception`, not `BaseException`, and raise a sanitized `BioPaperError` without including `str(error)` or raw output.

- [ ] **Step 4: Run contract tests and static checks**

```powershell
python -m pytest tests/contract/test_openai_summary.py -v
python -m ruff check src/biopaper_ai/adapters/ai/openai_summary.py tests/contract/test_openai_summary.py
python -m mypy
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/biopaper_ai/adapters/ai/openai_summary.py backend/tests/contract/test_openai_summary.py
git commit -m "feat: generate structured Chinese summaries"
```

---

### Task 5: Per-Paper Summary Application Orchestration

**Files:**
- Create: `backend/src/biopaper_ai/application/summarize_papers.py`
- Create: `backend/tests/unit/application/test_summarize_papers.py`

**Interfaces:**
- Consumes: Task 1 ports/models, Task 2 `build_evidence_pack`, existing immutable `SearchRun`/`SearchHit`.
- Produces: `SummarizeSearchRun(full_text_provider, summarizer, clock, model)` and `execute(run, summary_limit) -> SearchRun`.

- [ ] **Step 1: Write failing orchestration tests**

Use recording providers and a fixed clock. Cover the primary happy path:

```python
@pytest.mark.asyncio
async def test_only_top_n_hits_receive_full_text_summaries() -> None:
    full_text = RecordingFullTextProvider(available_document())
    summarizer = RecordingSummarizer(summary())
    service = SummarizeSearchRun(
        full_text_provider=full_text,
        summarizer=summarizer,
        clock=lambda: NOW,
        model="test-model",
    )
    result = await service.execute(search_run(hit_count=4), summary_limit=2)
    assert len(full_text.papers) == 2
    assert len(summarizer.calls) == 2
    assert [hit.summary_outcome is not None for hit in result.hits] == [
        True, True, False, False
    ]
    assert result.hits[0].summary_outcome.evidence_scope is (
        EvidenceScope.PMC_FULL_TEXT
    )
```

Add tests for: `summary_limit < 1` rejected before provider/clock; limit larger than hits; unavailable and failed full text both fall back to abstract with a visible note; no full text and no abstract creates `SKIPPED`; AI `BioPaperError` creates `FAILED`; an unexpected summarizer exception is sanitized; one failure does not stop later hits; original `run_id`, plan, source counts, provider failures, ambiguous matches, papers, and ranking reasons remain unchanged.

- [ ] **Step 2: Run tests to verify RED**

```powershell
python -m pytest tests/unit/application/test_summarize_papers.py -v
```

Expected: import error for `summarize_papers`.

- [ ] **Step 3: Implement sequential immutable orchestration**

```python
class SummarizeSearchRun:
    def __init__(
        self,
        *,
        full_text_provider: FullTextProvider,
        summarizer: PaperSummarizer,
        clock: Clock,
        model: str,
    ) -> None:
        self._full_text_provider = full_text_provider
        self._summarizer = summarizer
        self._clock = clock
        self._model = model

    async def execute(self, run: SearchRun, summary_limit: int) -> SearchRun:
        if summary_limit < 1:
            raise ValueError("summary_limit must be positive")
        updated = list(run.hits)
        for index, hit in enumerate(run.hits[:summary_limit]):
            updated[index] = hit.model_copy(
                update={"summary_outcome": await self._summarize_hit(hit)}
            )
        return run.model_copy(update={"hits": tuple(updated)})
```

Keep processing sequential. Generate `evidence_digest`, evidence scope, source URL, rights, truncation, model, and timestamp from application-owned values. Use only these static failure notes:

- skipped: `No reusable full text or abstract was available.`
- failed: `AI summary could not be generated safely.`
- abstract fallback: `PMC full text was unavailable; this summary is based only on the PubMed abstract.`

- [ ] **Step 4: Run focused tests, Ruff, and mypy**

```powershell
python -m pytest tests/unit/application/test_summarize_papers.py -v
python -m ruff check src/biopaper_ai/application/summarize_papers.py tests/unit/application/test_summarize_papers.py
python -m mypy
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/biopaper_ai/application/summarize_papers.py backend/tests/unit/application/test_summarize_papers.py
git commit -m "feat: orchestrate grounded paper summaries"
```

---

### Task 6: Audited JSON and CSV Summary Export

**Files:**
- Modify: `backend/src/biopaper_ai/application/export_results.py`
- Modify: `backend/tests/unit/application/test_export_results.py`

**Interfaces:**
- Consumes: Task 1 `SearchHit.summary_outcome` and nested summary models.
- Produces: JSON nested outcomes via `model_dump(mode="json")` and the 15 summary CSV columns named in the approved design.

- [ ] **Step 1: Write failing export tests**

```python
def test_csv_exports_summary_audit_without_full_text_or_evidence(tmp_path: Path) -> None:
    destination = tmp_path / "summaries.csv"
    export_search_run(summarized_run(), "csv", destination)
    rows = list(csv.DictReader(destination.open(encoding="utf-8-sig")))
    paper = next(row for row in rows if row["row_type"] == "paper")
    assert paper["summary_status"] == "success"
    assert paper["summary_evidence_scope"] == "pmc_full_text"
    assert json.loads(paper["summary_brief"]) == ["第一句。", "第二句。", "第三句。"]
    assert paper["summary_research_objective"] == "研究目的"
    exported = destination.read_text(encoding="utf-8-sig")
    assert FULL_TEXT_SENTINEL not in exported
    assert EVIDENCE_SENTINEL not in exported
    assert API_SECRET not in exported
```

Add JSON assertions for nested status, summary, model, generated_at, evidence digest, source URL, rights statement, truncation, and note. Add CSV tests for skipped/failed outcomes and for unsummarized hits producing empty summary columns. Re-run existing failure/source-count/ambiguity row tests unchanged.

- [ ] **Step 2: Run export tests to verify RED**

```powershell
python -m pytest tests/unit/application/test_export_results.py -v
```

Expected: assertions fail because summary CSV columns do not exist.

- [ ] **Step 3: Add exact CSV columns and owned serialization**

Append these names to `_CSV_COLUMNS`: `summary_status`, `summary_evidence_scope`, `summary_model`, `summary_generated_at`, `summary_evidence_digest`, `summary_source_url`, `summary_rights_statement`, `summary_truncated`, `summary_note`, `summary_brief`, `summary_research_objective`, `summary_experimental_design`, `summary_main_results`, `summary_significance`, `summary_limitations`.

Implement `_csv_summary(outcome) -> dict[str, str]`. Serialize `brief_summary` using `json.dumps(outcome.summary.brief_summary, ensure_ascii=False)`. Return all-empty values for `None`; never access evidence text because outcomes do not contain it.

- [ ] **Step 4: Run export tests and full offline application tests**

```powershell
python -m pytest tests/unit/application/test_export_results.py tests/unit/application -v
python -m ruff check src/biopaper_ai/application/export_results.py tests/unit/application/test_export_results.py
python -m mypy
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/biopaper_ai/application/export_results.py backend/tests/unit/application/test_export_results.py
git commit -m "feat: export Chinese summary audit data"
```

---

### Task 7: CLI Composition, Validation, and Separate Rendering

**Files:**
- Modify: `backend/src/biopaper_ai/entrypoints/cli/app.py`
- Modify: `backend/src/biopaper_ai/entrypoints/cli/render.py`
- Modify: `backend/tests/unit/cli/test_cli.py`

**Interfaces:**
- Consumes: Task 3 `PmcOaiFullTextProvider`, Task 4 `OpenAIPaperSummarizer`, Task 5 `SummarizeSearchRun`, Task 6 export.
- Produces: `biopaper search --summarize --summary-limit N`, early safe configuration validation, injected `SummaryService`, and separate Rich summary panels.

- [ ] **Step 1: Write failing CLI parameter and configuration tests**

```python
def test_summarize_requires_openai_key_before_plan_or_search() -> None:
    plan_service = RecordingPlanService(search_plan())
    search_service = RecordingSearchService(search_run())
    summary_service = RecordingSummaryService(search_run())
    app = _make_app(
        plan_service,
        search_service,
        summary_service=summary_service,
        settings=Settings(openai_api_key=None),
    )
    result = RUNNER.invoke(
        app,
        ["search", "probiotic", "--summarize", "--accept-plan", "--no-ai"],
    )
    assert result.exit_code == 1
    assert "BIOPAPER_OPENAI_API_KEY" in result.output
    assert "traceback" not in result.output.casefold()
    assert plan_service.calls == []
    assert search_service.calls == []
    assert summary_service.calls == []
```

Add tests that: default search never constructs/calls summary service; `--no-ai --summarize` calls deterministic planning then summary; default limit is 3; explicit limit reaches service; `--summary-limit 5` without `--summarize` exits 2 before services; zero limit exits 2; summary partial failures retain exit 0 when papers exist; output export contains summary; raw secrets/exceptions/full-text sentinel never render.

- [ ] **Step 2: Write failing renderer tests**

Use `Console(file=StringIO(), width=240, color_system=None)` and assert output includes `AI-generated Chinese summary`, `Evidence scope`, `PMC full text` or `PubMed abstract only`, all six summary fields, and fallback/failure warnings. Assert the original abstract is never labeled as AI content and the AI text is never placed in the database metadata table.

- [ ] **Step 3: Run CLI tests to verify RED**

```powershell
python -m pytest tests/unit/cli/test_cli.py -v
```

Expected: failures because options, service injection, and rendering do not exist.

- [ ] **Step 4: Add summary composition and early gates**

Add:

```python
class SummaryService(Protocol):
    async def execute(self, run: SearchRun, summary_limit: int) -> SearchRun: ...


def _summary_service(settings: Settings) -> SummaryService:
    if settings.openai_api_key is None:
        raise _SummaryConfigurationError(
            "BIOPAPER_OPENAI_API_KEY is required for AI summaries"
        )
    provider = PmcOaiFullTextProvider(settings)
    summarizer = OpenAIPaperSummarizer.from_api_key(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.model,
    )
    return SummarizeSearchRun(
        full_text_provider=provider,
        summarizer=summarizer,
        clock=lambda: datetime.now(UTC),
        model=settings.model,
    )
```

Extend `create_app` with an injected `summary_service_factory`. Add options:

```python
summarize: bool = typer.Option(False, "--summarize")
summary_limit: int = typer.Option(3, "--summary-limit", min=1)
```

Immediately after loading settings and before plan generation: reject a non-default summary limit without `--summarize`; reject missing OpenAI key when `--summarize`. After search and before render/export, call the summary service sequentially. Preserve existing search failure exit behavior.

- [ ] **Step 5: Render summaries separately**

Keep the existing search-results table. After it, render one summary panel/table per requested hit with title, AI-generated label, evidence scope, source URL, model, 3–5 brief sentences, objective, design, results, significance, limitations, and safe note. Render skipped/failed outcomes as yellow warnings without empty scientific fields.

- [ ] **Step 6: Run focused and full CLI tests**

```powershell
python -m pytest tests/unit/cli/test_cli.py tests/unit/test_cli.py -v
python -m ruff check src/biopaper_ai/entrypoints/cli tests/unit/cli
python -m mypy
biopaper search --help
```

Expected: tests, Ruff, and mypy pass; help shows both new options.

- [ ] **Step 7: Commit**

```powershell
git add backend/src/biopaper_ai/entrypoints/cli/app.py backend/src/biopaper_ai/entrypoints/cli/render.py backend/tests/unit/cli/test_cli.py
git commit -m "feat: expose opt-in Chinese summaries in CLI"
```

---

### Task 8: Live PMC Gate, Documentation, Version, and Release Verification

**Files:**
- Create: `backend/tests/integration/test_live_pmc.py`
- Modify: `README.md`
- Modify: `THIRD_PARTY_NOTICES.md`
- Modify: `backend/pyproject.toml`
- Existing gate: `scripts/verify_phase1.ps1` discovers the new offline tests without modification.

**Interfaces:**
- Consumes: complete summary feature and official PMC OAI-PMH service.
- Produces: documented `0.2.0` release, opt-in live truthfulness gate, passing full release script, and GitHub-ready commit.

- [ ] **Step 1: Write the live PMC identity test**

```python
pytestmark = [pytest.mark.live, pytest.mark.asyncio]


async def test_live_pmc_returns_the_requested_reusable_record() -> None:
    settings = Settings.from_env()
    if not settings.can_search_live:
        pytest.skip("BIOPAPER_NCBI_EMAIL is required for live PMC verification")
    result = await PmcOaiFullTextProvider(settings).fetch(
        paper_with_pmcid("PMC12124693")
    )
    assert result.status is FullTextStatus.AVAILABLE
    assert result.document is not None
    assert result.document.pmcid == "PMC12124693"
    assert result.document.sections
    assert urlsplit(str(result.document.source_url)).hostname == (
        "pmc.ncbi.nlm.nih.gov"
    )
```

The helper paper must use synthetic metadata and PubMed provenance; the test verifies PMC identity only and never calls OpenAI.

- [ ] **Step 2: Update active README feature and limitation statements**

Document exact setup and commands:

```powershell
$env:BIOPAPER_NCBI_EMAIL = "researcher@example.org"
$env:BIOPAPER_OPENAI_API_KEY = "replace-with-your-key"
biopaper search "Lactobacillus rhamnosus intestinal immunity mice" --no-ai --summarize --summary-limit 3 --output summaries.json
```

Explain: `--summarize` is opt-in and may incur OpenAI charges; evidence text is sent to the configured model service; PMC reusable full text is preferred; abstract fallback is labeled; no full text is exported; AI output is not source text, medical advice, evidence extraction, or systematic-review assessment. Replace the old statement that Phase 1 never retrieves full text with the narrower limitations that it does not persist/distribute full text and does not build evidence tables.

- [ ] **Step 3: Update third-party/service notices and version**

In `THIRD_PARTY_NOTICES.md`, add the official PMC OAI-PMH URL and state that article-specific rights remain controlling. Do not claim PMC content is MIT licensed. Change `backend/pyproject.toml` version from `0.1.0` to `0.2.0`.

- [ ] **Step 4: Run documentation and offline release gates**

```powershell
Set-Location ..
rg -n "does not implement full-text retrieval|Apache License 2.0" README.md backend/pyproject.toml
.\scripts\verify_phase1.ps1
git diff --check
```

Expected: obsolete feature/license searches return no matches; release script passes Ruff, format, strict mypy, all non-live tests, coverage, pip check, help, and doctor; `git diff --check` is clean.

- [ ] **Step 5: Run the opt-in live PMC gate with process-only contact configuration**

```powershell
Push-Location backend
$env:BIOPAPER_NCBI_EMAIL = git config user.email
python -m pytest -m live tests/integration/test_live_pmc.py -v
$liveExit = $LASTEXITCODE
Remove-Item Env:BIOPAPER_NCBI_EMAIL -ErrorAction SilentlyContinue
Pop-Location
if ($liveExit -ne 0) { exit $liveExit }
```

Expected: one live PMC test passes; no email, key, full text, or raw response is printed or written to tracked files.

- [ ] **Step 6: Run secret and scope checks**

```powershell
git status --short
git diff --check
git diff -- . ':!docs/superpowers/plans/2026-08-18-ai-chinese-paper-summary.md'
rg -n "sk-[A-Za-z0-9_-]{12,}|api[_-]?key\s*=\s*['\"][^'\"]+|postgres(?:ql)?://[^[:space:]]+:[^[:space:]@]+@" . --glob '!*.xml'
```

Expected: only planned feature/docs/test files are modified; no real secret or credential-bearing DSN is found.

- [ ] **Step 7: Commit the release completion**

```powershell
git add README.md THIRD_PARTY_NOTICES.md backend/pyproject.toml backend/tests/integration/test_live_pmc.py
git commit -m "docs: release grounded Chinese summaries"
```

- [ ] **Step 8: Request final independent review before publishing**

Provide the reviewer the full diff from the design commit through HEAD, the approved design, this implementation plan, offline gate output, live PMC output, and an explicit checklist for truth boundaries, copyright safety, secret safety, CLI compatibility, exports, and partial failures. Address only verified findings with focused red tests and new commits.

- [ ] **Step 9: Push and verify GitHub Actions**

```powershell
git push origin main
```

Expected: GitHub Actions passes for Python 3.11, 3.12, and 3.13 on the pushed HEAD. Do not call the feature released until the remote HEAD matches local HEAD and the workflow conclusion is `success`.
