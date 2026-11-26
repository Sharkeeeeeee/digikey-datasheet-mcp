"""Small async client for the DigiKey Product Information API v4.

Docs: https://developer.digikey.com/products/product-information-v4
Authentication is the OAuth2 client-credentials ("2-legged") flow, so only a
client ID and secret from a DigiKey developer app are needed.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import quote

import httpx

from .config import Settings

SEARCH_OPTIONS = {
    "in_stock": "InStock",
    "rohs": "RohsCompliant",
    "has_datasheet": "HasDatasheet",
    "normally_stocking": "NormallyStocking",
    "new": "NewProduct",
}

SORT_FIELDS = {
    "price": ("Price", "Ascending"),
    "stock": ("QuantityAvailable", "Descending"),
    "manufacturer": ("Manufacturer", "Ascending"),
}


class DigiKeyError(Exception):
    """An error talking to DigiKey, with a message fit to show the user."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class NotConfiguredError(DigiKeyError):
    def __init__(self) -> None:
        super().__init__(
            "DigiKey API credentials are not set. Create a free app at "
            "https://developer.digikey.com (Production app, enable 'ProductInformation V4'), "
            "then set DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET in the MCP server's env. "
            "The search_lcsc and datasheet_* tools (with a URL) work without keys."
        )


class NotFoundError(DigiKeyError):
    pass


def _problem_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:300] or response.reason_phrase
    if isinstance(body, dict):
        parts = [body.get("title"), body.get("detail") or body.get("ErrorMessage")]
        details = body.get("ErrorDetails") or body.get("errors")
        if details:
            parts.append(str(details)[:300])
        message = " - ".join(str(p) for p in parts if p)
        if message:
            return message
    return str(body)[:300]


class DigiKeyClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._http = http or httpx.AsyncClient(timeout=settings.timeout)
        self._token: str | None = None
        self._token_expiry = 0.0
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        host = "sandbox-api.digikey.com" if self.settings.sandbox else "api.digikey.com"
        return f"https://{host}"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get_token(self, force: bool = False) -> str:
        if not self.settings.has_digikey:
            raise NotConfiguredError()
        async with self._lock:
            if not force and self._token and time.monotonic() < self._token_expiry:
                return self._token
            try:
                response = await self._http.post(
                    f"{self.base_url}/v1/oauth2/token",
                    data={
                        "client_id": self.settings.client_id,
                        "client_secret": self.settings.client_secret,
                        "grant_type": "client_credentials",
                    },
                )
            except httpx.HTTPError as exc:
                raise DigiKeyError(f"Could not reach DigiKey: {exc}") from exc
            if response.status_code >= 400:
                raise DigiKeyError(
                    "DigiKey rejected the client ID/secret "
                    f"(HTTP {response.status_code}: {_problem_message(response)}). "
                    "Check the credentials and that the app is a Production app "
                    "(or set DIGIKEY_SANDBOX=true for a Sandbox app).",
                    response.status_code,
                )
            body = response.json()
            self._token = body["access_token"]
            # Refresh a minute early so a token never expires mid-request.
            self._token_expiry = time.monotonic() + max(int(body.get("expires_in", 600)) - 60, 30)
            return self._token

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for attempt in range(2):
            token = await self._get_token(force=attempt > 0)
            headers = {
                "Authorization": f"Bearer {token}",
                "X-DIGIKEY-Client-Id": self.settings.client_id or "",
                "X-DIGIKEY-Locale-Site": self.settings.site,
                "X-DIGIKEY-Locale-Language": self.settings.language,
                "X-DIGIKEY-Locale-Currency": self.settings.currency,
                "X-DIGIKEY-Customer-Id": self.settings.customer_id,
                "Accept": "application/json",
            }
            try:
                response = await self._http.request(
                    method, f"{self.base_url}{path}", params=params, json=json, headers=headers
                )
            except httpx.HTTPError as exc:
                raise DigiKeyError(f"Could not reach DigiKey: {exc}") from exc
            if response.status_code == 401 and attempt == 0:
                continue  # token revoked or expired early: get a new one once
            break
        status = response.status_code
        if status == 404:
            raise NotFoundError(f"DigiKey has no product matching that number ({_problem_message(response)}).", 404)
        if status == 429:
            retry = response.headers.get("Retry-After")
            hint = f" Retry after {retry} s." if retry else ""
            raise DigiKeyError(f"DigiKey rate limit reached (HTTP 429).{hint}", 429)
        if status >= 400:
            raise DigiKeyError(f"DigiKey API error HTTP {status}: {_problem_message(response)}", status)
        if not response.content:
            return {}
        return response.json()

    async def keyword_search(
        self,
        keywords: str,
        *,
        limit: int = 10,
        offset: int = 0,
        options: list[str] | None = None,
        sort: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"Keywords": keywords, "Limit": limit, "Offset": offset}
        if options:
            body["FilterOptionsRequest"] = {"SearchOptions": [SEARCH_OPTIONS[o] for o in options]}
        if sort and sort in SORT_FIELDS:
            field, order = SORT_FIELDS[sort]
            body["SortOptions"] = {"Field": field, "SortOrder": order}
        return await self.request("POST", "/products/v4/search/keyword", json=body)

    async def product_details(self, part_number: str) -> dict[str, Any]:
        body = await self.request("GET", f"/products/v4/search/{quote(part_number, safe='')}/productdetails")
        product = body.get("Product")
        if not product:
            raise NotFoundError(f"DigiKey returned no product for {part_number!r}.", 404)
        return product

    async def substitutions(self, part_number: str, limit: int = 10) -> dict[str, Any]:
        return await self.request(
            "GET",
            f"/products/v4/search/{quote(part_number, safe='')}/substitutions",
            params={"limit": limit},
        )
