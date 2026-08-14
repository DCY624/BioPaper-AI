"""Opt-in truthfulness checks against live PubMed records."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from defusedxml import ElementTree as DefusedElementTree

from biopaper_ai.adapters.ai.deterministic_plan import DeterministicPlanGenerator
from biopaper_ai.adapters.search.native_pubmed import EFETCH_URL, NativePubMedProvider
from biopaper_ai.application.search_papers import SearchPapers
from biopaper_ai.config import Settings
from biopaper_ai.domain.identifiers import (
    normalize_doi,
    normalize_pmcid,
    normalize_pmid,
)
from biopaper_ai.domain.provenance import SourceName

pytestmark = [pytest.mark.live, pytest.mark.asyncio]

_ALLOWED_PROVENANCE_HOSTS = frozenset({"pubmed.ncbi.nlm.nih.gov"})
_TRUTH_QUERIES = Path(__file__).parents[1] / "fixtures" / "truth_queries.json"


async def test_live_pubmed_results_are_confirmed_by_efetch() -> None:
    settings = Settings.from_env()
    if not settings.can_search_live:
        pytest.skip("BIOPAPER_NCBI_EMAIL is required for live PubMed verification")

    provider = NativePubMedProvider(settings)
    search = SearchPapers(provider=provider, clock=lambda: datetime.now(UTC))
    generator = DeterministicPlanGenerator()

    for case in json.loads(_TRUTH_QUERIES.read_text(encoding="utf-8")):
        plan = await generator.generate(case["query"])
        run = await search.execute(plan, case["limit"])

        assert run.hits, f"PubMed returned no qualifying papers for {case['query']!r}"
        reported_pmids: set[str] = set()
        pubmed_provenance_count = 0
        for hit in run.hits:
            paper = hit.paper
            pmid = normalize_pmid(paper.identifiers.pmid)
            assert pmid is not None
            assert pmid not in reported_pmids
            reported_pmids.add(pmid)

            if paper.identifiers.doi is not None:
                assert normalize_doi(paper.identifiers.doi) == paper.identifiers.doi
            if paper.identifiers.pmcid is not None:
                assert (
                    normalize_pmcid(paper.identifiers.pmcid) == paper.identifiers.pmcid
                )

            assert paper.provenance
            for provenance in paper.provenance:
                assert provenance.source is SourceName.PUBMED
                assert normalize_pmid(provenance.record_id) == pmid
                assert (
                    urlsplit(str(provenance.url)).hostname in _ALLOWED_PROVENANCE_HOSTS
                )
                pubmed_provenance_count += 1

        assert pubmed_provenance_count > 0
        assert await _efetch_pmids(settings, reported_pmids) == reported_pmids


async def _efetch_pmids(settings: Settings, pmids: set[str]) -> set[str]:
    """Independently fetch all reported IDs in one request and return NCBI's PMIDs."""
    assert settings.ncbi_email is not None
    data = {
        "db": "pubmed",
        "id": ",".join(sorted(pmids, key=int)),
        "retmode": "xml",
        "tool": "BioPaperAI",
        "email": settings.ncbi_email,
    }
    if settings.ncbi_api_key is not None:
        data["api_key"] = settings.ncbi_api_key.get_secret_value()

    await asyncio.sleep(0.11 if settings.ncbi_api_key is not None else 0.34)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(EFETCH_URL, data=data)
        response.raise_for_status()

    root = DefusedElementTree.fromstring(response.content)
    return {
        pmid
        for element in root.findall("./PubmedArticle/MedlineCitation/PMID")
        if (pmid := normalize_pmid(element.text)) is not None
    }
