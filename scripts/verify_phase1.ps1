$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location (Join-Path $repoRoot "backend")
try {
    python -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw "ruff check failed" }

    python -m ruff format --check .
    if ($LASTEXITCODE -ne 0) { throw "ruff format check failed" }

    python -m mypy
    if ($LASTEXITCODE -ne 0) { throw "mypy failed" }

    python -m pytest -m 'not live' --cov=biopaper_ai --cov-report=term-missing
    if ($LASTEXITCODE -ne 0) { throw "offline tests failed" }

    python -m pip check
    if ($LASTEXITCODE -ne 0) { throw "pip check failed" }

    biopaper --help
    if ($LASTEXITCODE -ne 0) { throw "biopaper --help failed" }

    biopaper doctor
    if ($LASTEXITCODE -ne 0) { throw "biopaper doctor failed" }
}
finally {
    Pop-Location
}
