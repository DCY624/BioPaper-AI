"""Application configuration loaded from environment variables."""

from typing import ClassVar

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for BioPaper AI."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="BIOPAPER_", extra="ignore"
    )

    ncbi_email: str | None = None
    ncbi_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    model: str = "gpt-5.6-luna"
    database_url: str = "sqlite:///./biopaper.db"

    @field_validator("ncbi_email", mode="before")
    @classmethod
    def blank_email_is_unconfigured(cls, value: object) -> object:
        """Treat blank environment values as absent."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def can_search_live(self) -> bool:
        """Whether requests to NCBI live services are permitted."""
        return self.ncbi_email is not None

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from the current environment."""
        return cls()

    def diagnostic_dict(self) -> dict[str, object]:
        """Return safe operational diagnostics without secret values."""
        return {
            "ncbi_email": self.ncbi_email,
            "ncbi_api_key_configured": self.ncbi_api_key is not None,
            "openai_api_key_configured": self.openai_api_key is not None,
            "can_search_live": self.can_search_live,
            "model": self.model,
            "database_url": self.database_url,
        }
