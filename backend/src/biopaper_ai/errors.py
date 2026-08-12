"""Typed domain errors surfaced by BioPaper AI."""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable machine-readable BioPaper AI error codes."""

    SOURCE_UNAVAILABLE = "source_unavailable"
    RATE_LIMITED = "rate_limited"
    PAPER_NOT_FOUND = "paper_not_found"
    AI_KEY_MISSING = "ai_key_missing"
    AI_OUTPUT_INVALID = "ai_output_invalid"
    PARTIAL_RESULT = "partial_result"
    INVALID_SEARCH_PLAN = "invalid_search_plan"


class BioPaperError(Exception):
    """An expected application failure with a stable error code."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after_seconds = retry_after_seconds
