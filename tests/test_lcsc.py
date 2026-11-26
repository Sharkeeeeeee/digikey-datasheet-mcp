from digikey_datasheet_mcp.lcsc import normalize


async def test_search(lcsc, backend):
    backend.lcsc_components = [
        {
            "lcsc": 8734,
            "mfr": "STM32F103C8T6",
            "package": "LQFP-48",
            "description": "ARM Cortex-M3 72MHz 64KB Flash",
            "stock": 12000,
            "price": 1.95,
            "is_basic": False,
            "is_preferred": True,
        }
    ]
    parts = await lcsc.search("STM32F103C8T6", limit=5, package="LQFP-48")
    request = backend.requests[-1]
    assert request.url.path == "/api/search"
    assert request.url.params["q"] == "STM32F103C8T6"
    assert request.url.params["package"] == "LQFP-48"
    assert parts[0]["lcsc"] == "C8734"
    assert parts[0]["product_url"] == "https://www.lcsc.com/product-detail/C8734.html"
    assert parts[0]["jlcpcb_preferred_part"] is True


def test_normalize_keeps_prefixed_codes_and_drops_empty():
    out = normalize({"lcsc": "C25804", "mfr": "0402WGF1002TCE", "description": ""})
    assert out == {
        "lcsc": "C25804",
        "mpn": "0402WGF1002TCE",
        "product_url": "https://www.lcsc.com/product-detail/C25804.html",
    }
