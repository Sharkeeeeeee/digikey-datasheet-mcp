"""Settings read from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_TRUE = {"1", "true", "yes", "on"}


def _default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(Path.home(), ".cache")
    return Path(base) / "digikey-datasheet-mcp"


@dataclass(frozen=True)
class Settings:
    client_id: str | None = None
    client_secret: str | None = None
    sandbox: bool = False
    site: str = "US"
    language: str = "en"
    currency: str = "USD"
    customer_id: str = "0"
    cache_dir: Path = Path(".cache")
    timeout: float = 30.0
    lcsc_url: str = "https://jlcsearch.tscircuit.com"
    max_pdf_mb: int = 50

    @property
    def has_digikey(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env

        def get(name: str, default: str) -> str:
            value = env.get(name, "").strip()
            return value or default

        cache = env.get("DIGIKEY_MCP_CACHE_DIR", "").strip()
        return cls(
            client_id=env.get("DIGIKEY_CLIENT_ID", "").strip() or None,
            client_secret=env.get("DIGIKEY_CLIENT_SECRET", "").strip() or None,
            sandbox=env.get("DIGIKEY_SANDBOX", "").strip().lower() in _TRUE,
            site=get("DIGIKEY_LOCALE_SITE", "US"),
            language=get("DIGIKEY_LOCALE_LANGUAGE", "en"),
            currency=get("DIGIKEY_LOCALE_CURRENCY", "USD"),
            customer_id=get("DIGIKEY_CUSTOMER_ID", "0"),
            cache_dir=Path(cache).expanduser() if cache else _default_cache_dir(),
            timeout=float(get("DIGIKEY_MCP_TIMEOUT", "30")),
            lcsc_url=get("LCSC_SEARCH_URL", "https://jlcsearch.tscircuit.com").rstrip("/"),
            max_pdf_mb=int(get("DATASHEET_MAX_MB", "50")),
        )
