# Contributing to BioPaper AI

Thank you for contributing. The default test suite must run fully offline:
do not add live network calls to ordinary tests. Mark opt-in network tests with
`@pytest.mark.live`; NCBI calls require a configured `BIOPAPER_NCBI_EMAIL`.

Changes to external-source or AI contracts require deterministic contract
fixtures covering normal, empty, malformed, and partial-response cases. Never
commit credentials, API keys, or recordings containing them.

Before submitting a change, run the backend Ruff, mypy, and offline pytest
checks used by CI.
