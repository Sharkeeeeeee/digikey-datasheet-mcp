"""The MCP server: tool definitions on top of the DigiKey, LCSC and datasheet clients."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from . import __version__, normalize
from .config import Settings
from .datasheet import DatasheetError, DatasheetStore, locate_sections, looks_like_url, search, section_text
from .digikey import DigiKeyClient, DigiKeyError, NotFoundError
from .lcsc import LcscClient, LcscError

INSTRUCTIONS = """\
Electronic component research: DigiKey part search, pricing, stock, alternatives and BOM
costing, LCSC/JLCPCB search, and reading datasheets.

Workflow tips:
- To answer questions about a part's pins, ratings or specs, use datasheet_outline then
  datasheet_section (pinout, absolute_maximum_ratings, electrical_characteristics, ...)
  instead of guessing. Quote page numbers.
- Datasheet tools accept a DigiKey/manufacturer part number or a datasheet URL.
- Prices are in the configured currency, for the quantity asked, before tax and shipping.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True, idempotent_hint=True)

SectionName = Literal[
    "pinout",
    "absolute_maximum_ratings",
    "recommended_operating_conditions",
    "electrical_characteristics",
    "thermal",
    "esd",
    "timing",
    "typical_application",
    "package",
    "ordering",
    "features",
]


class BomLine(BaseModel):
    part_number: str = Field(description="Manufacturer or DigiKey part number")
    quantity: int = Field(ge=1, description="Pieces needed")
    reference: str | None = Field(default=None, description="Optional designators, e.g. 'R1-R4'")


def build_server(
    settings: Settings | None = None,
    *,
    digikey: DigiKeyClient | None = None,
    lcsc: LcscClient | None = None,
    datasheets: DatasheetStore | None = None,
) -> MCPServer:
    settings = settings or Settings.from_env()
    dk = digikey or DigiKeyClient(settings)
    lc = lcsc or LcscClient(settings)
    ds = datasheets or DatasheetStore(settings)

    mcp = MCPServer(
        name="digikey-datasheet",
        title="DigiKey + Datasheet",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://github.com/Sharkeeeeeee/digikey-datasheet-mcp",
    )

    async def details(part_number: str) -> dict[str, Any]:
        try:
            return await dk.product_details(part_number.strip())
        except DigiKeyError as exc:
            raise ToolError(str(exc)) from exc

    async def resolve_datasheet(source: str):
        url = source
        if not looks_like_url(source):
            product = await details(source)
            url = normalize.fix_url(product.get("DatasheetUrl")) or ""
            if not url:
                raise ToolError(f"DigiKey lists no datasheet for {source!r}. Pass a datasheet URL instead.")
        try:
            return await ds.get(url)
        except DatasheetError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool(annotations=READ_ONLY)
    async def search_parts(
        query: Annotated[str, Field(description="Keywords or a part number, e.g. 'LDO 3.3V 500mA SOT-23-5'")],
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        in_stock: bool = False,
        rohs: bool = False,
        sort: Literal["relevance", "price", "stock"] = "relevance",
        manufacturer: Annotated[str | None, Field(description="Keep only this manufacturer (substring match)")] = None,
    ) -> dict[str, Any]:
        """Search DigiKey by keyword or part number. Returns stock, unit price, status, datasheet URL and key parameters."""
        options = [name for name, on in (("in_stock", in_stock), ("rohs", rohs)) if on]
        try:
            body = await dk.keyword_search(
                query, limit=limit, options=options, sort=None if sort == "relevance" else sort
            )
        except DigiKeyError as exc:
            raise ToolError(str(exc)) from exc
        exact = body.get("ExactMatches") or []
        products = exact + [p for p in body.get("Products") or [] if p not in exact]
        parts = [normalize.summarize(p) for p in products]
        if manufacturer:
            needle = manufacturer.lower()
            parts = [p for p in parts if needle in (p.get("manufacturer") or "").lower()]
        return {
            "total_matches": body.get("ProductsCount"),
            "exact_match": bool(exact),
            "parts": parts[:limit],
        }

    @mcp.tool(annotations=READ_ONLY)
    async def get_part(
        part_number: Annotated[str, Field(description="Manufacturer part number or DigiKey part number")],
    ) -> dict[str, Any]:
        """Full DigiKey record for one part: every parameter, packaging options with price breaks, stock, lifecycle, RoHS, lead time, datasheet URL."""
        return normalize.summarize(await details(part_number), full=True)

    @mcp.tool(annotations=READ_ONLY)
    async def get_price(
        part_number: str,
        quantity: Annotated[int, Field(ge=1)] = 1,
    ) -> dict[str, Any]:
        """Price a quantity of one part: picks the cheapest packaging (cut tape, tray, reel...) that covers the quantity and shows the next price break."""
        product = await details(part_number)
        offer = normalize.best_offer(product, quantity)
        offer["mpn"] = product.get("ManufacturerProductNumber")
        offer["currency"] = settings.currency
        if offer["best"] is None:
            offer["note"] = "No standard-priced packaging covers this quantity (check minimum order quantities)."
        return offer

    @mcp.tool(annotations=READ_ONLY)
    async def find_alternatives(
        part_number: str,
        limit: Annotated[int, Field(ge=1, le=25)] = 10,
    ) -> dict[str, Any]:
        """DigiKey's substitutes for a part (direct, similar, upgrade...), with stock and price. Useful for out-of-stock or obsolete parts."""
        try:
            body = await dk.substitutions(part_number.strip(), limit=limit)
        except DigiKeyError as exc:
            raise ToolError(str(exc)) from exc
        subs = []
        for s in body.get("ProductSubstitutes") or []:
            entry = {
                "mpn": s.get("ManufacturerProductNumber"),
                "manufacturer": (s.get("Manufacturer") or {}).get("Name"),
                "substitute_type": s.get("SubstituteType"),
                "description": s.get("Description"),
                "stock": s.get("QuantityAvailable"),
                "unit_price": s.get("UnitPrice"),
                "digikey_pn": s.get("DigiKeyProductNumber"),
                "product_url": normalize.fix_url(s.get("ProductUrl")),
            }
            subs.append({k: v for k, v in entry.items() if v not in (None, "")})
        return {"part_number": part_number, "count": len(subs), "alternatives": subs[:limit]}

    @mcp.tool(annotations=READ_ONLY)
    async def compare_parts(
        part_numbers: Annotated[list[str], Field(min_length=2, max_length=6)],
    ) -> dict[str, Any]:
        """Side-by-side comparison of 2-6 parts. Returns a Markdown table of the parameters they share plus price and stock."""
        products = await asyncio.gather(*(details(pn) for pn in part_numbers))
        summaries = [normalize.summarize(p, full=True) for p in products]
        keys: list[str] = []
        for s in summaries:
            for key in s.get("parameters", {}):
                if key not in keys:
                    keys.append(key)
        # Rows where at least two parts report a value are the comparable ones.
        keys = [k for k in keys if sum(k in s.get("parameters", {}) for s in summaries) >= 2]
        header = ["", *[s.get("mpn") or "?" for s in summaries]]
        rows = [
            ["Manufacturer", *[s.get("manufacturer", "") for s in summaries]],
            [f"Unit price ({settings.currency})", *[str(s.get("unit_price", "")) for s in summaries]],
            ["Stock", *[str(s.get("stock", "")) for s in summaries]],
            ["Status", *[s.get("status", "") for s in summaries]],
        ]
        rows += [[k, *[s.get("parameters", {}).get(k, "—") for s in summaries]] for k in keys]

        def md(cells: list[str]) -> str:
            return "| " + " | ".join(str(c).replace("|", "/") for c in cells) + " |"

        table = "\n".join([md(header), md(["---"] * len(header)), *map(md, rows)])
        differing = [r[0] for r in rows[4:] if len(set(r[1:])) > 1]
        return {
            "table_markdown": table,
            "differing_parameters": differing,
            "datasheets": {s.get("mpn"): s.get("datasheet_url") for s in summaries},
        }

    @mcp.tool(annotations=READ_ONLY)
    async def price_bom(
        items: Annotated[list[BomLine], Field(min_length=1, max_length=100)],
        build_quantity: Annotated[
            int, Field(ge=1, description="Number of boards; each line quantity is multiplied by this")
        ] = 1,
    ) -> dict[str, Any]:
        """Cost a bill of materials on DigiKey: best packaging per line, line totals, grand total, and warnings for missing, out-of-stock or obsolete parts."""
        sem = asyncio.Semaphore(4)

        async def cost(line: BomLine) -> dict[str, Any]:
            qty = line.quantity * build_quantity
            out: dict[str, Any] = {"part_number": line.part_number, "reference": line.reference, "quantity": qty}
            async with sem:
                try:
                    product = await dk.product_details(line.part_number.strip())
                except NotFoundError:
                    out["error"] = "not found"
                    return out
                except DigiKeyError as exc:
                    if exc.status in (None, 401, 403, 429) or exc.status >= 500:
                        raise ToolError(str(exc)) from exc
                    out["error"] = str(exc)
                    return out
            offer = normalize.best_offer(product, qty)
            out["mpn"] = product.get("ManufacturerProductNumber")
            out["status"] = normalize.status(product)
            if offer["best"]:
                best = offer["best"]
                out.update(
                    digikey_pn=best["digikey_pn"],
                    packaging=best["packaging"],
                    unit_price=best["unit_price"],
                    line_total=best["extended_price"],
                    in_stock=best["in_stock"],
                )
            else:
                out["error"] = "no standard pricing for this quantity"
            return {k: v for k, v in out.items() if v is not None}

        lines = await asyncio.gather(*(cost(item) for item in items))
        warnings = []
        for line in lines:
            label = line["part_number"]
            if "error" in line:
                warnings.append(f"{label}: {line['error']}")
            elif not line.get("in_stock"):
                warnings.append(f"{label}: not enough stock for {line['quantity']}")
            status = (line.get("status") or "").lower()
            if status and status != "active":
                warnings.append(f"{label}: lifecycle status is '{line['status']}'")
        total = round(sum(line.get("line_total", 0) for line in lines), 2)
        return {
            "currency": settings.currency,
            "build_quantity": build_quantity,
            "total": total,
            "per_board": round(total / build_quantity, 4),
            "lines": lines,
            "warnings": warnings,
        }

    @mcp.tool(annotations=READ_ONLY)
    async def search_lcsc(
        query: Annotated[str, Field(description="Keywords or part number, e.g. 'STM32F103C8T6' or '10k 0402'")],
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        package: Annotated[str | None, Field(description="Optional package filter, e.g. '0402' or 'SOT-23'")] = None,
    ) -> dict[str, Any]:
        """Search LCSC / JLCPCB assembly parts (no API key needed). Shows LCSC code, stock, price and JLCPCB basic/preferred status."""
        try:
            parts = await lc.search(query, limit=limit, package=package)
        except LcscError as exc:
            raise ToolError(str(exc)) from exc
        return {"source": "LCSC via jlcsearch", "count": len(parts), "parts": parts}

    @mcp.tool(annotations=READ_ONLY)
    async def datasheet_outline(
        source: Annotated[str, Field(description="Part number (looked up on DigiKey) or datasheet PDF URL")],
    ) -> dict[str, Any]:
        """Open a datasheet and list what is where: page count, PDF bookmarks, and the pages of key sections (pinout, absolute maximum ratings, electrical characteristics...)."""
        doc = await resolve_datasheet(source)
        return {
            "url": doc.url,
            "title": doc.title,
            "page_count": doc.page_count,
            "sections": {k: v["page"] for k, v in locate_sections(doc).items()},
            "bookmarks": [b for b in doc.bookmarks if b["level"] <= 1][:80],
        }

    @mcp.tool(annotations=READ_ONLY)
    async def datasheet_section(
        source: Annotated[str, Field(description="Part number or datasheet PDF URL")],
        section: SectionName,
        max_chars: Annotated[int, Field(ge=1000, le=40000)] = 12000,
    ) -> dict[str, Any]:
        """Return the text of one datasheet section with page numbers. For 'pinout' it also returns a best-effort pin table."""
        doc = await resolve_datasheet(source)
        return {"url": doc.url, **section_text(doc, section, max_chars=max_chars)}

    @mcp.tool(annotations=READ_ONLY)
    async def datasheet_search(
        source: Annotated[str, Field(description="Part number or datasheet PDF URL")],
        query: Annotated[
            str, Field(description="Words that must appear near each other, e.g. 'quiescent current' or 'I2C address'")
        ],
        max_hits: Annotated[int, Field(ge=1, le=40)] = 12,
    ) -> dict[str, Any]:
        """Find where a term appears in a datasheet. Returns page numbers with surrounding text."""
        doc = await resolve_datasheet(source)
        return {"url": doc.url, "query": query, "hits": search(doc, query, max_hits=max_hits)}

    @mcp.tool(annotations=READ_ONLY)
    async def datasheet_pages(
        source: Annotated[str, Field(description="Part number or datasheet PDF URL")],
        first_page: Annotated[int, Field(ge=1)],
        last_page: Annotated[int | None, Field(ge=1)] = None,
        max_chars: Annotated[int, Field(ge=1000, le=60000)] = 20000,
    ) -> dict[str, Any]:
        """Raw text of a page range (1-based, inclusive) from a datasheet."""
        doc = await resolve_datasheet(source)
        last = min(last_page or first_page, doc.page_count)
        if first_page > doc.page_count:
            raise ToolError(f"The datasheet has only {doc.page_count} pages.")
        text = "\n\n".join(f"[page {p}]\n{doc.pages[p - 1]}" for p in range(first_page, last + 1))
        return {
            "url": doc.url,
            "pages": [first_page, last],
            "page_count": doc.page_count,
            "text": text[:max_chars],
            "truncated": len(text) > max_chars,
        }

    return mcp
