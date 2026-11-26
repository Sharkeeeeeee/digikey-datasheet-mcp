import json

import httpx
import pytest
from conftest import http_for
from fixtures import settings

from digikey_datasheet_mcp.digikey import DigiKeyClient, DigiKeyError, NotConfiguredError, NotFoundError


async def test_token_is_fetched_once_and_sent_with_locale_headers(digikey, backend):
    await digikey.product_details("TPS7A9933DBVR")
    await digikey.product_details("TPS7A9933DBVR")
    assert backend.token_calls == 1
    api = [r for r in backend.requests if "productdetails" in r.url.path]
    assert len(api) == 2
    headers = api[0].headers
    assert headers["Authorization"] == "Bearer tok1"
    assert headers["X-DIGIKEY-Client-Id"] == "id"
    assert headers["X-DIGIKEY-Locale-Currency"] == "USD"
    assert headers["X-DIGIKEY-Locale-Site"] == "US"


async def test_token_request_is_client_credentials(digikey, backend):
    await digikey.product_details("TPS7A9933DBVR")
    token_req = backend.requests[0]
    assert token_req.url.path == "/v1/oauth2/token"
    form = dict(httpx.QueryParams(token_req.content.decode()))
    assert form == {"client_id": "id", "client_secret": "secret", "grant_type": "client_credentials"}


async def test_part_numbers_with_slashes_are_escaped(digikey, backend):
    product = await digikey.product_details("LM1117MP-3.3/NOPB")
    assert product["ManufacturerProductNumber"] == "LM1117MP-3.3/NOPB"
    assert b"LM1117MP-3.3%2FNOPB" in backend.requests[-1].url.raw_path


async def test_keyword_search_body(digikey, backend):
    await digikey.keyword_search("ldo 3.3v", limit=5, options=["in_stock", "rohs"], sort="price")
    body = json.loads(backend.requests[-1].content)
    assert body["Keywords"] == "ldo 3.3v" and body["Limit"] == 5
    assert body["FilterOptionsRequest"] == {"SearchOptions": ["InStock", "RohsCompliant"]}
    assert body["SortOptions"] == {"Field": "Price", "SortOrder": "Ascending"}


async def test_expired_token_is_refreshed_once(digikey, backend):
    calls = {"n": 0}

    def flaky(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(401, json={"title": "Bearer token expired"})
        return backend.digikey(request)

    backend.overrides["/products/"] = flaky
    product = await digikey.product_details("TPS7A9933DBVR")
    assert product["ManufacturerProductNumber"] == "TPS7A9933DBVR"
    assert backend.token_calls == 2


async def test_not_found(digikey):
    with pytest.raises(NotFoundError):
        await digikey.product_details("NOPE-123")


async def test_rate_limit_message(digikey, backend):
    backend.overrides["/products/"] = lambda r: httpx.Response(429, headers={"Retry-After": "30"})
    with pytest.raises(DigiKeyError, match="Retry after 30"):
        await digikey.product_details("TPS7A9933DBVR")


async def test_server_error_includes_problem_details(digikey, backend):
    backend.overrides["/products/"] = lambda r: httpx.Response(
        503, json={"title": "Service Unavailable", "detail": "maintenance"}
    )
    with pytest.raises(DigiKeyError, match="503.*maintenance"):
        await digikey.product_details("TPS7A9933DBVR")


async def test_bad_credentials(tmp_path, backend):
    client = DigiKeyClient(settings(tmp_path, client_secret="wrong"), http=http_for(backend))
    with pytest.raises(DigiKeyError, match="rejected the client ID/secret"):
        await client.product_details("TPS7A9933DBVR")


async def test_missing_credentials(tmp_path, backend):
    client = DigiKeyClient(settings(tmp_path, client_id=None, client_secret=None), http=http_for(backend))
    with pytest.raises(NotConfiguredError, match="developer.digikey.com"):
        await client.product_details("TPS7A9933DBVR")
    assert backend.requests == []


async def test_sandbox_host(tmp_path, backend):
    client = DigiKeyClient(settings(tmp_path, sandbox=True), http=http_for(backend))
    await client.product_details("TPS7A9933DBVR")
    assert {r.url.host for r in backend.requests} == {"sandbox-api.digikey.com"}


async def test_non_json_success_is_a_clean_error(digikey, backend):
    backend.overrides["/products/"] = lambda r: httpx.Response(200, text="<html>maintenance</html>")
    with pytest.raises(DigiKeyError, match="not JSON"):
        await digikey.product_details("TPS7A9933DBVR")


async def test_malformed_token_response(digikey, backend):
    backend.overrides["/v1/oauth2/token"] = lambda r: httpx.Response(200, json={"oops": 1})
    with pytest.raises(DigiKeyError, match="unexpected token"):
        await digikey.product_details("TPS7A9933DBVR")
