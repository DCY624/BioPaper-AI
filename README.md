# BioPaper AI

BioPaper AI Phase 1 is a command-line tool for turning a biomedical question
into a reviewable search plan, querying PubMed, and exporting source-grounded
metadata. It is designed to make the executed query, database identifiers,
source URLs, partial failures, and deterministic ranking reasons visible rather
than asking users to trust generated citations.

## Trust boundary

Phase 1 treats PubMed responses as the source of truth for papers and external
identifiers. Boolean syntax is built locally from a displayed `SearchPlan`, and
search executes that reviewed syntax instead of the raw natural-language
question. PMID, PMCID, DOI, titles, abstracts, and provenance URLs come from
database responses; the tool does not manufacture identifiers or infer
scientific conclusions.

OpenAI-assisted planning is optional and requires the user's own API key. Model
output can propose search concepts, but it cannot supply paper IDs, source
records, or the final Boolean syntax. The deterministic `--no-ai` path remains
available without an OpenAI key.

## Requirements and setup

- Python 3.11 or newer
- An email address supplied to NCBI for live PubMed requests
- Optionally, an NCBI API key and an OpenAI API key

From the repository root:

```powershell
Set-Location backend
python -m pip install -e . --group dev
Copy-Item ..\.env.example .env
```

The application reads these environment variable names:

- `BIOPAPER_NCBI_EMAIL` — required for live PubMed search
- `BIOPAPER_NCBI_API_KEY` — optional; enables NCBI's higher request limit
- `BIOPAPER_OPENAI_API_KEY` — optional; enables AI-assisted planning
- `BIOPAPER_MODEL` — optional OpenAI model selection
- `BIOPAPER_DATABASE_URL` — reserved configuration; Phase 1 does not persist
  search runs to a database

`.env.example` is a template, not a secret store. Export the variables into the
current shell or configure them in your environment before running commands.
Never commit credentials.

## Review, search, and export

The primary example asks in Chinese about *Lactobacillus rhamnosus*, intestinal
immunity, mice, and the years 2021–2026. Deterministic planning preserves the
Chinese text and warns that it did not translate it:

```powershell
biopaper plan "鼠李糖乳杆菌 Lactobacillus rhamnosus 改善肠道免疫 小鼠 2021-2026" --no-ai
```

Run the reviewed plan without AI. Interactive mode displays the plan and asks
for confirmation before any search request:

```powershell
biopaper search "鼠李糖乳杆菌 Lactobacillus rhamnosus 改善肠道免疫 小鼠 2021-2026" --no-ai --limit 5
```

For automation, acknowledge the plan explicitly and export by choosing a
`.json` or `.csv` destination:

```powershell
biopaper search "鼠李糖乳杆菌 Lactobacillus rhamnosus 改善肠道免疫 小鼠 2021-2026" --no-ai --limit 5 --non-interactive --accept-plan --output results.json
biopaper search "BRCA1 breast cancer review 2024" --no-ai --limit 5 --non-interactive --accept-plan --output results.csv
```

JSON preserves the plan, identifiers, provenance, failures, and ambiguous
matches. CSV provides paper metadata and source names and URLs. Ranking reasons
describe literal title matches, abstract matches, and publication year; they
are not scientific relevance scores.

## NCBI usage and release verification

BioPaper AI identifies live requests with `BIOPAPER_NCBI_EMAIL` and limits NCBI
traffic to 3 requests per second without an API key or 10 requests per second
with one. Use NCBI services responsibly and follow the current NCBI usage
guidelines.

Run the reproducible offline Phase 1 gate from the repository root:

```powershell
.\scripts\verify_phase1.ps1
```

The release script intentionally excludes live tests. To run the opt-in live
truthfulness gate after configuring `BIOPAPER_NCBI_EMAIL`:

```powershell
Push-Location backend
python -m pytest -m live tests/integration/test_live_pubmed.py -v
Pop-Location
```

The live gate performs deterministic searches, validates returned identifiers
and PubMed provenance locally, and independently batch-fetches every reported
PMID from NCBI. A skipped live test is not release approval: public publication
remains blocked until the configured live gate passes.

## Phase 1 scope and limitations

Implemented in Phase 1 are deterministic and optional OpenAI-assisted search
planning, reviewed PubMed search through a pinned upstream adapter with a native
NCBI fallback, strict identifier validation, provenance-preserving
deduplication, local filters, explainable ordering, diagnostics, and atomic JSON
or CSV export.

Phase 1 does **not** implement full-text retrieval or reading, evidence tables,
PubTator enrichment, OpenAlex or citation graphs, an MCP server or MCP tools, a
Web UI, or database persistence. It does not perform systematic-review quality
assessment, meta-analysis, or clinical interpretation.

## Four-week roadmap

1. Week 1: keep the offline contracts and live PubMed truthfulness gate stable
   across supported Python versions and upstream changes.
2. Week 2: improve plan review ergonomics and add more conservative,
   user-visible query controls without weakening provenance rules.
3. Week 3: design and test evidence-extraction boundaries against licensed,
   source-verifiable content; this is roadmap work, not a current feature.
4. Week 4: evaluate interfaces such as a Web UI or MCP only after the trusted
   search and release gates remain reliable.

## Attribution, license, and safety

The pinned `pubmed-search-mcp` adapter and other acknowledgements are documented
in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). BioPaper AI is licensed
under the [Apache License 2.0](LICENSE).

BioPaper AI is a literature-search aid, not a medical device or diagnostic
system. Its output is not medical advice and must not be used to diagnose,
treat, or make clinical decisions. Verify source records and consult qualified
professionals where appropriate.
