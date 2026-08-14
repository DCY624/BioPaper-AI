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
    "pmid",
    "pmcid",
    "doi",
    "title",
    "year",
    "journal",
    "abstract",
    "source_names",
    "source_urls",
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
                "pmid": paper.identifiers.pmid or "",
                "pmcid": paper.identifiers.pmcid or "",
                "doi": paper.identifiers.doi or "",
                "title": paper.title,
                "year": paper.year if paper.year is not None else "",
                "journal": paper.journal or "",
                "abstract": paper.abstract or "",
                "source_names": "|".join(record.source for record in paper.provenance),
                "source_urls": "|".join(str(record.url) for record in paper.provenance),
            }
        )
