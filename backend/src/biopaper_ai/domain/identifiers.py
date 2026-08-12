"""Canonical identifiers for literature records."""

import re  # noqa: I001


_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_PMID_PATTERN = re.compile(r"^\d{1,9}$")
_PMCID_PATTERN = re.compile(r"^(?:PMC)?(\d+)$", re.IGNORECASE)
_DOI_PREFIX_PATTERN = re.compile(
    r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE
)


def normalize_doi(value: str | None) -> str | None:
    """Return a lowercase DOI without a URL or ``doi:`` prefix."""
    if value is None:
        return None
    candidate = _DOI_PREFIX_PATTERN.sub("", _require_text(value, "DOI").strip())
    if not _DOI_PATTERN.fullmatch(candidate):
        raise ValueError(
            "DOI must start with 10., include a registrant, and have a suffix"
        )
    return candidate.lower()


def normalize_pmid(value: str | None) -> str | None:
    """Return a validated PubMed identifier."""
    if value is None:
        return None
    candidate = _require_text(value, "PMID").strip()
    if not _PMID_PATTERN.fullmatch(candidate):
        raise ValueError("PMID must contain 1 to 9 digits")
    return candidate


def normalize_pmcid(value: str | None) -> str | None:
    """Return a validated PMC identifier with its canonical prefix."""
    if value is None:
        return None
    match = _PMCID_PATTERN.fullmatch(_require_text(value, "PMCID").strip())
    if match is None:
        raise ValueError("PMCID must be PMC followed by digits")
    return f"PMC{match.group(1)}"


def _require_text(value: str, identifier_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{identifier_name} must be text")
    return value
