import json

import pytest
from conftest import http_for
from fixtures import DATASHEET_URL, settings
from mcp import Client
from pdfgen import LDO_PAGES, make_pdf

from digikey_datasheet_mcp.server import build_server


@pytest.fixture
def server(cfg, digikey, lcsc, store):
    return build_server(cfg, digikey=digikey, lcsc=lcsc, datasheets=store)


async def call(server, name, args):
    async with Client(server) as client:
        result = await client.call_tool(name, args)
    if result.is_error:
        return {"error": result.content[0].text}
    return result.structured_content or json.loads(result.content[0].text)


async def test_lists_all_tools_as_read_only(server):
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
    names = {t.name for t in tools}
    assert names == {
        "search_parts",
        "get_part",
        "get_price",
        "find_alternatives",
        "compare_parts",
        "price_bom",
        "search_lcsc",
        "datasheet_outline",
        "datasheet_section",
        "datasheet_search",
        "datasheet_pages",
    }
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)
    assert all(t.description for t in tools)


async def test_search_parts_puts_exact_match_first(server):
    out = await call(server, "search_parts", {"query": "LM1117MP-3.3/NOPB"})
    assert out["exact_match"] is True
    assert [p["mpn"] for p in out["parts"]] == ["LM1117MP-3.3/NOPB", "TPS7A9933DBVR"]


async def test_search_parts_manufacturer_filter(server):
    out = await call(server, "search_parts", {"query": "ldo", "manufacturer": "analog devices"})
    assert out["parts"] == []


async def test_get_part(server):
    out = await call(server, "get_part", {"part_number": "TPS7A9933DBVR"})
    assert out["parameters"]["Voltage - Output (Min/Fixed)"] == "3.3V"
    assert out["datasheet_url"] == DATASHEET_URL


async def test_get_price(server):
    out = await call(server, "get_price", {"part_number": "TPS7A9933DBVR", "quantity": 100})
    assert out["best"]["unit_price"] == 0.71
    assert out["currency"] == "USD"


async def test_unknown_part_is_a_tool_error(server):
    out = await call(server, "get_part", {"part_number": "NOPE"})
    assert "no product" in out["error"]


async def test_find_alternatives(server):
    out = await call(server, "find_alternatives", {"part_number": "LM1117MP-3.3/NOPB"})
    assert out["alternatives"][0]["mpn"] == "AZ1117CH-3.3TRG1"
    assert out["alternatives"][0]["product_url"] == "https://www.digikey.com/p/2"


async def test_compare_parts(server):
    out = await call(server, "compare_parts", {"part_numbers": ["TPS7A9933DBVR", "LM1117MP-3.3/NOPB"]})
    table = out["table_markdown"]
    assert table.splitlines()[0] == "|  | TPS7A9933DBVR | LM1117MP-3.3/NOPB |"
    assert "| Current - Output | 500mA | 800mA |" in table
    assert "Current - Output" in out["differing_parameters"]
    assert "Voltage - Output (Min/Fixed)" not in out["differing_parameters"]


async def test_price_bom(server):
    out = await call(
        server,
        "price_bom",
        {
            "items": [
                {"part_number": "TPS7A9933DBVR", "quantity": 2, "reference": "U1,U2"},
                {"part_number": "LM1117MP-3.3/NOPB", "quantity": 1},
                {"part_number": "DOES-NOT-EXIST", "quantity": 1},
            ],
            "build_quantity": 5,
        },
    )
    first = out["lines"][0]
    assert first["quantity"] == 10 and first["unit_price"] == 0.98 and first["line_total"] == 9.8
    assert out["total"] == round(9.8 + 5 * 1.12, 2)
    assert out["per_board"] == round(out["total"] / 5, 4)
    joined = " ".join(out["warnings"])
    assert "DOES-NOT-EXIST: not found" in joined
    assert "LM1117MP-3.3/NOPB: not enough stock" in joined
    assert "'Obsolete'" in joined


async def test_missing_credentials_message(tmp_path, backend):
    from digikey_datasheet_mcp.digikey import DigiKeyClient

    cfg = settings(tmp_path, client_id=None, client_secret=None)
    server = build_server(cfg, digikey=DigiKeyClient(cfg, http=http_for(backend)))
    out = await call(server, "search_parts", {"query": "ldo"})
    assert "DIGIKEY_CLIENT_ID" in out["error"]


async def test_search_lcsc(server, backend):
    backend.lcsc_components = [{"lcsc": 25804, "mfr": "0402WGF1002TCE", "stock": 1, "price": 0.0005}]
    out = await call(server, "search_lcsc", {"query": "10k 0402"})
    assert out["parts"][0]["lcsc"] == "C25804"


async def test_datasheet_tools_by_part_number(server, backend):
    backend.add_file(DATASHEET_URL, make_pdf(LDO_PAGES))
    outline = await call(server, "datasheet_outline", {"source": "TPS7A9933DBVR"})
    assert outline["page_count"] == 6
    assert outline["sections"]["absolute_maximum_ratings"] == 4

    section = await call(server, "datasheet_section", {"source": "TPS7A9933DBVR", "section": "pinout"})
    assert {p["name"] for p in section["pins_guess"]} == {"IN", "GND", "EN", "NR/SS", "OUT"}

    hits = await call(server, "datasheet_search", {"source": DATASHEET_URL, "query": "quiescent"})
    assert hits["hits"][0]["page"] == 5

    pages = await call(server, "datasheet_pages", {"source": DATASHEET_URL, "first_page": 5, "last_page": 9})
    assert pages["pages"] == [5, 6]
    assert "[page 6]" in pages["text"]
    # Downloaded once, then served from memory.
    assert sum(1 for r in backend.requests if str(r.url) == DATASHEET_URL) == 1


async def test_datasheet_for_part_without_datasheet(server):
    out = await call(server, "datasheet_outline", {"source": "LM1117MP-3.3/NOPB"})
    assert "lists no datasheet" in out["error"]


async def test_datasheet_page_out_of_range(server, backend):
    backend.add_file(DATASHEET_URL, make_pdf(LDO_PAGES))
    out = await call(server, "datasheet_pages", {"source": DATASHEET_URL, "first_page": 40})
    assert "only 6 pages" in out["error"]


async def test_invalid_section_name_is_rejected(server):
    out = await call(server, "datasheet_section", {"source": DATASHEET_URL, "section": "everything"})
    assert "error" in out


async def test_search_parts_local_filters_fetch_a_full_page(server, backend):
    out = await call(server, "search_parts", {"query": "ldo", "limit": 5, "min_stock": 100, "active_only": True})
    body = json.loads(backend.requests[-1].content)
    assert body["Limit"] == 50
    assert body["FilterOptionsRequest"] == {"SearchOptions": ["InStock"]}
    assert [p["mpn"] for p in out["parts"]] == ["TPS7A9933DBVR"]
    assert out["filtered_out"] == 1


async def test_search_parts_price_filter_and_empty_hint(server):
    out = await call(server, "search_parts", {"query": "ldo", "max_unit_price": 0.1})
    assert out["parts"] == [] and "hint" in out


async def test_search_parts_rejects_blank_query(server):
    assert "empty" in (await call(server, "search_parts", {"query": "  "}))["error"]


async def test_price_bom_from_csv_merges_duplicates_and_adds_spares(server):
    csv_text = "Reference,MPN,Qty\nU1,TPS7A9933DBVR,1\nU7,tps7a9933dbvr,1\nC1,NOPE-1,1\n"
    out = await call(server, "price_bom", {"bom_csv": csv_text, "build_quantity": 4, "spare_percent": 10})
    ldo = out["lines"][0]
    assert ldo["reference"] == "U1, U7"
    assert ldo["quantity"] == 9  # 2 per board x 4 boards x 1.10, rounded up
    assert ldo["unit_price"] == 1.12
    assert out["lines_priced"] == 1 and out["lines_with_problems"] == 1


async def test_price_bom_suggests_alternatives(server):
    out = await call(
        server,
        "price_bom",
        {"items": [{"part_number": "LM1117MP-3.3/NOPB", "quantity": 10}], "suggest_alternatives": True},
    )
    assert out["lines"][0]["alternative"]["mpn"] == "AZ1117CH-3.3TRG1"


async def test_price_bom_needs_exactly_one_input(server):
    assert "exactly one" in (await call(server, "price_bom", {}))["error"]
    both = {"items": [{"part_number": "A", "quantity": 1}], "bom_csv": "MPN\nA\n"}
    assert "exactly one" in (await call(server, "price_bom", both))["error"]
    assert "part number column" in (await call(server, "price_bom", {"bom_csv": "Value\n10k\n"}))["error"]


async def test_compare_parts_reports_unknown_parts(server):
    out = await call(server, "compare_parts", {"part_numbers": ["TPS7A9933DBVR", "LM1117MP-3.3/NOPB", "NOPE"]})
    assert list(out["not_found"]) == ["NOPE"]
    assert "NOPE" not in out["table_markdown"]
    only_one = await call(server, "compare_parts", {"part_numbers": ["TPS7A9933DBVR", "NOPE"]})
    assert "at least two" in only_one["error"]


async def test_datasheet_from_local_file(server, tmp_path):
    path = tmp_path / "ldo.pdf"
    path.write_bytes(make_pdf(LDO_PAGES))
    out = await call(server, "datasheet_section", {"source": str(path), "section": "absolute_maximum_ratings"})
    assert out["pages"] == [4]


async def test_datasheet_pages_rejects_reversed_range(server, backend):
    backend.add_file(DATASHEET_URL, make_pdf(LDO_PAGES))
    out = await call(server, "datasheet_pages", {"source": DATASHEET_URL, "first_page": 4, "last_page": 2})
    assert "before first_page" in out["error"]
