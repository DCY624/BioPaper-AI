"""Secret-free atomic export of application-owned search results."""

import csv
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TextIO, cast

from biopaper_ai.application.search_papers import SearchRun

_CSV_COLUMNS = (
    "row_type",
    "run_id",
    "executed_at",
    "boolean_query",
    "pmid",
    "pmcid",
    "doi",
    "title",
    "year",
    "journal",
    "abstract",
    "source_names",
    "source_urls",
    "ranking_reasons",
    "audit_source",
    "requested_count",
    "returned_count",
    "failure_code",
    "failure_message",
    "retry_after_seconds",
    "failure_record_id",
    "ambiguous_title",
    "ambiguous_year",
    "ambiguous_paper_ids",
    "conflicting_identifier_types",
)
_Writer = Callable[[TextIO], None]


def export_search_run(run: SearchRun, format: str, destination: Path) -> Path:
    """Atomically export one run as JSON or CSV without reading configuration."""
    normalized_format = format.casefold()
    writers: dict[str, tuple[str, _Writer]] = {
        "json": ("utf-8", lambda handle: _write_json(handle, run)),
        "csv": ("utf-8-sig", lambda handle: _write_csv(handle, run)),
    }
    try:
        encoding, writer = writers[normalized_format]
    except KeyError as error:
        raise ValueError(f"unsupported export format: {format}") from error

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            newline="",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            writer(cast(TextIO, handle))
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(destination)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return destination


def _write_json(handle: TextIO, run: SearchRun) -> None:
    json.dump(
        run.model_dump(mode="json"),
        handle,
        ensure_ascii=False,
        indent=2,
    )
    handle.write("\n")


def _write_csv(handle: TextIO, run: SearchRun) -> None:
    writer = csv.DictWriter(handle, fieldnames=_CSV_COLUMNS)
    writer.writeheader()
    for hit in run.hits:
        paper = hit.paper
        writer.writerow(
            {
                **_csv_audit_base(run, "paper"),
                "pmid": paper.identifiers.pmid or "",
                "pmcid": paper.identifiers.pmcid or "",
                "doi": paper.identifiers.doi or "",
                "title": paper.title,
                "year": paper.year if paper.year is not None else "",
                "journal": paper.journal or "",
                "abstract": paper.abstract or "",
                "source_names": "|".join(record.source for record in paper.provenance),
                "source_urls": "|".join(str(record.url) for record in paper.provenance),
                "ranking_reasons": "|".join(hit.ranking_reasons),
            }
        )
    for count in run.source_counts:
        writer.writerow(
            {
                **_csv_audit_base(run, "source_count"),
                "audit_source": count.source,
                "requested_count": str(count.requested),
                "returned_count": str(count.returned),
            }
        )
    for failure in run.failures:
        writer.writerow(
            {
                **_csv_audit_base(run, "failure"),
                "audit_source": failure.source,
                "failure_code": failure.code,
                "failure_message": failure.message,
                "retry_after_seconds": (
                    ""
                    if failure.retry_after_seconds is None
                    else format(failure.retry_after_seconds, "g")
                ),
                "failure_record_id": failure.record_id or "",
            }
        )
    for ambiguous in run.ambiguous_matches:
        writer.writerow(
            {
                **_csv_audit_base(run, "ambiguity"),
                "ambiguous_title": ambiguous.normalized_title,
                "ambiguous_year": (
                    str(ambiguous.year) if ambiguous.year is not None else ""
                ),
                "ambiguous_paper_ids": "|".join(
                    paper.primary_id for paper in ambiguous.papers
                ),
                "conflicting_identifier_types": "|".join(
                    ambiguous.conflicting_identifier_types
                ),
            }
        )


def _csv_audit_base(run: SearchRun, row_type: str) -> dict[str, str]:
    return {
        "row_type": row_type,
        "run_id": str(run.run_id),
        "executed_at": run.executed_at.isoformat(),
        "boolean_query": run.plan.boolean_query,
    }
