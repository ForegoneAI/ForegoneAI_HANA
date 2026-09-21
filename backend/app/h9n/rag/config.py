"""Environment-backed settings for the H9N RAG pipeline.

Settings are loaded lazily so importing FastAPI does not require live customer
credentials. This also keeps keys out of source code and test fixtures.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


class RagConfigurationError(RuntimeError):
    """Raised when a RAG operation is attempted without safe configuration."""


def _positive_int(variable_name: str, default: int) -> int:
    """Read a positive integer setting and fail clearly on invalid input."""
    raw_value = os.getenv(variable_name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RagConfigurationError(f"{variable_name} must be an integer.") from exc

    if value <= 0:
        raise RagConfigurationError(f"{variable_name} must be greater than zero.")
    return value


@dataclass(frozen=True)
class RagSettings:
    """All runtime configuration needed by the RAG API and its providers."""

    openrouter_api_key: str | None
    supabase_url: str | None
    supabase_service_role_key: str | None
    internal_api_key: str | None
    embedding_model: str
    embedding_dimensions: int
    openrouter_referer: str | None
    openrouter_title: str | None
    storage_bucket: str
    chunk_size: int
    chunk_overlap: int
    max_upload_bytes: int
    default_match_count: int

    @classmethod
    def from_environment(cls) -> "RagSettings":
        """Load local .env values without overwriting real deployed variables."""
        load_dotenv(override=False)

        chunk_size = _positive_int("H9N_RAG_CHUNK_SIZE", 1200)
        chunk_overlap = _positive_int("H9N_RAG_CHUNK_OVERLAP", 200)
        if chunk_overlap >= chunk_size:
            raise RagConfigurationError(
                "H9N_RAG_CHUNK_OVERLAP must be smaller than H9N_RAG_CHUNK_SIZE."
            )

        return cls(
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
            supabase_url=os.getenv("SUPABASE_URL"),
            supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
            internal_api_key=os.getenv("H9N_RAG_INTERNAL_API_KEY"),
            embedding_model=os.getenv(
                "H9N_RAG_EMBEDDING_MODEL", "openai/text-embedding-3-small"
            ),
            embedding_dimensions=_positive_int("H9N_RAG_EMBEDDING_DIMENSIONS", 1536),
            openrouter_referer=os.getenv("H9N_RAG_OPENROUTER_REFERER"),
            openrouter_title=os.getenv("H9N_RAG_OPENROUTER_TITLE"),
            storage_bucket=os.getenv("H9N_RAG_BUCKET", "h9n-deal-packages"),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            max_upload_bytes=_positive_int("H9N_RAG_MAX_UPLOAD_BYTES", 26_214_400),
            default_match_count=_positive_int("H9N_RAG_DEFAULT_MATCH_COUNT", 6),
        )

    def require(self, *setting_names: str) -> None:
        """Ensure an operation has its required secrets before it starts."""
        values = {
            "OPENROUTER_API_KEY": self.openrouter_api_key,
            "SUPABASE_URL": self.supabase_url,
            "SUPABASE_SERVICE_ROLE_KEY": self.supabase_service_role_key,
            "H9N_RAG_INTERNAL_API_KEY": self.internal_api_key,
        }
        # The tracked template uses readable placeholders. Treat them exactly
        # like missing secrets so the API never tries to run against a fake URL
        # or accidentally accepts a sample access key.
        def is_configured(value: str | None) -> bool:
            return bool(value) and "replace-with" not in value and "your-project-id" not in value

        missing = [name for name in setting_names if not is_configured(values.get(name))]
        if missing:
            raise RagConfigurationError(
                "RAG is not configured. Set " + ", ".join(missing) + " in .env or the runtime environment."
            )


@lru_cache
def get_rag_settings() -> RagSettings:
    """Reuse immutable settings for the lifetime of the running API process."""
    return RagSettings.from_environment()
