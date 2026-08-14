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


def test_diagnostics_never_expose_database_url():
    database_secret = "database-password-must-not-escape"
    database_url = f"postgresql://user:{database_secret}@database.test/biopaper"

    diagnostics = Settings(database_url=database_url).diagnostic_dict()

    assert "database_url" not in diagnostics
    assert diagnostics["database_configured"] is True
    assert database_secret not in repr(diagnostics)
    assert database_url not in repr(diagnostics)
