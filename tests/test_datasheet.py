import pytest
from fixtures import DATASHEET_URL
from pdfgen import LDO_PAGES, make_pdf

from digikey_datasheet_mcp import datasheet as ds
from digikey_datasheet_mcp.datasheet import DatasheetError, DatasheetStore


@pytest.fixture
def doc():
    return ds.parse_pdf(make_pdf(LDO_PAGES), DATASHEET_URL)


def test_parse_pages(doc):
    assert doc.page_count == 6
    assert "Quiescent current" in doc.pages[4]


def test_locate_sections_skips_table_of_contents(doc):
    sections = ds.locate_sections(doc)
    assert sections["pinout"]["page"] == 3
    assert sections["absolute_maximum_ratings"]["page"] == 4  # not page 2 (contents) or the "See ..." line
    assert sections["recommended_operating_conditions"]["page"] == 4
    assert sections["electrical_characteristics"]["page"] == 5
    assert sections["package"]["page"] == 6
    assert sections["features"]["page"] == 1
    assert all(v["via"] == "heading" for v in sections.values())


def test_bookmarks_win_over_headings():
    pdf = make_pdf(LDO_PAGES, bookmarks=[("7.5 Electrical Characteristics", 3)], title="TPS7A99 datasheet")
    doc = ds.parse_pdf(pdf, DATASHEET_URL)
    assert doc.title == "TPS7A99 datasheet"
    assert doc.bookmarks == [{"title": "7.5 Electrical Characteristics", "page": 4, "level": 0}]
    assert ds.locate_sections(doc)["electrical_characteristics"] == {
        "page": 4,
        "heading": "7.5 Electrical Characteristics",
        "via": "bookmark",
    }


def test_section_text_and_pins(doc):
    result = ds.section_text(doc, "pinout")
    assert result["found"] and result["pages"] == [3]
    assert result["text"].startswith("[page 3]\n5 Pin Configuration")
    pins = {p["pin"]: p["name"] for p in result["pins_guess"]}
    assert pins == {"1": "IN", "2": "GND", "3": "EN", "4": "NR/SS", "5": "OUT"}


def test_section_text_starts_at_heading_mid_page(doc):
    result = ds.section_text(doc, "recommended_operating_conditions")
    assert result["text"].startswith("[page 4]\n6.3 Recommended Operating Conditions")
    assert "Junction temperature" not in result["text"]


def test_section_text_truncates(doc):
    result = ds.section_text(doc, "features", max_chars=1000)
    assert len(result["text"]) <= 1000


def test_missing_section_lists_alternatives(doc):
    result = ds.section_text(doc, "timing")
    assert result["found"] is False
    assert result["available_sections"]["pinout"] == 3


def test_search(doc):
    hits = ds.search(doc, "dropout voltage")
    assert [h["page"] for h in hits] == [5]
    assert "180" in hits[0]["snippet"]
    assert ds.search(doc, "   ") == []
    assert ds.search(doc, "dropout zebra") == []


def test_extract_pins_needs_two_rows():
    assert ds.extract_pins("1 VIN Input") == []


def test_normalize_url():
    assert ds.normalize_url("//a.com/x.pdf") == "https://a.com/x.pdf"
    with pytest.raises(DatasheetError):
        ds.normalize_url("file:///etc/passwd")
    with pytest.raises(DatasheetError):
        ds.normalize_url("not a url")


async def test_store_downloads_and_caches(store, backend, cfg):
    backend.add_file(DATASHEET_URL, make_pdf(LDO_PAGES))
    doc = await store.get(DATASHEET_URL)
    assert doc.page_count == 6
    assert len(backend.requests) == 1
    # A fresh store (new process) reads the on-disk cache instead of downloading again.
    fresh = DatasheetStore(cfg, http=store._http)
    again = await fresh.get(DATASHEET_URL)
    assert again.pages == doc.pages
    assert len(backend.requests) == 1


async def test_store_follows_pdf_link_on_landing_page(store, backend):
    landing = "https://www.example-semi.com/product/tps7a99"
    backend.add_file(landing, b'<html><a href="/lit/ds/tps7a99.pdf">Datasheet</a></html>', "text/html")
    backend.add_file(DATASHEET_URL, make_pdf(LDO_PAGES))
    doc = await store.get(landing)
    assert doc.page_count == 6


async def test_store_rejects_html_without_pdf(store, backend):
    backend.add_file(DATASHEET_URL, b"<html>Please verify you are human</html>", "text/html")
    with pytest.raises(DatasheetError, match="did not return a PDF"):
        await store.get(DATASHEET_URL)


async def test_store_http_error(store):
    with pytest.raises(DatasheetError, match="HTTP 404"):
        await store.get("https://www.example-semi.com/missing.pdf")


async def test_store_size_limit(tmp_path, backend):
    from conftest import http_for
    from fixtures import settings

    store = DatasheetStore(settings(tmp_path, max_pdf_mb=0), http=http_for(backend))
    backend.add_file(DATASHEET_URL, make_pdf(LDO_PAGES))
    with pytest.raises(DatasheetError, match="larger than"):
        await store.get(DATASHEET_URL)


async def test_store_rejects_image_only_pdf(store, backend):
    backend.add_file(DATASHEET_URL, make_pdf([[]]))
    with pytest.raises(DatasheetError, match="no extractable text"):
        await store.get(DATASHEET_URL)


def test_section_stops_at_next_heading_on_same_page(doc):
    result = ds.section_text(doc, "absolute_maximum_ratings")
    assert result["pages"] == [4]
    assert "Junction temperature" in result["text"]
    assert "Recommended" not in result["text"]
