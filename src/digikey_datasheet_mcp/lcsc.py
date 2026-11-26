"""LCSC / JLCPCB parts search through the open jlcsearch index (no API key).

jlcsearch (https://github.com/tscircuit/jlcsearch) is a community-run index of
the JLCPCB assembly parts catalogue, which mirrors LCSC stock and pricing.
Set LCSC_SEARCH_URL to point at a self-hosted instance.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import Settings


class LcscError(Exception):
    pass


def _lcsc_code(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text if text.upper().startswith("C") else f"C{text}"


def normalize(component: dict[str, Any]) -> dict[str, Any]:
    code = _lcsc_code(component.get("lcsc"))
    out = {
        "lcsc": code,
        "mpn": component.get("mfr"),
        "package": component.get("package"),
        "description": component.get("description"),
        "stock": component.get("stock"),
        "unit_price_usd": component.get("price"),
        "jlcpcb_basic_part": component.get("is_basic"),
        "jlcpcb_preferred_part": component.get("is_preferred"),
        "product_url": f"https://www.lcsc.com/product-detail/{code}.html" if code else None,
    }
    return {k: v for k, v in out.items() if v not in (None, "")}


class LcscClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._http = http or httpx.AsyncClient(timeout=settings.timeout, follow_redirects=True)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def search(self, query: str, limit: int = 10, package: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"q": query, "limit": limit}
        if package:
            params["package"] = package
        try:
            response = await self._http.get(f"{self.settings.lcsc_url}/api/search", params=params)
        except httpx.HTTPError as exc:
            raise LcscError(f"Could not reach the LCSC search index: {exc}") from exc
        if response.status_code >= 400:
            raise LcscError(f"LCSC search index returned HTTP {response.status_code}.")
        try:
            body = response.json()
        except ValueError as exc:
            raise LcscError("LCSC search index returned a response that is not JSON.") from exc
        components = body.get("components", []) if isinstance(body, dict) else body
        return [normalize(c) for c in components[:limit] if isinstance(c, dict)]
