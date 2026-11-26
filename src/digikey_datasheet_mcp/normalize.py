"""Turn verbose DigiKey v4 product JSON into compact, model-friendly dicts."""

from __future__ import annotations

from typing import Any


def fix_url(url: str | None) -> str | None:
    """DigiKey often returns protocol-relative URLs ("//mm.digikey.com/...")."""
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    return url


def _name(obj: Any, key: str = "Name") -> str | None:
    if isinstance(obj, dict):
        value = obj.get(key)
        return str(value) if value else None
    return None


def category_path(category: dict[str, Any] | None) -> list[str]:
    """Follow the first child at each level: Category > Child > Grandchild."""
    path: list[str] = []
    while isinstance(category, dict):
        name = category.get("Name")
        if name:
            path.append(name)
        children = category.get("ChildCategories") or []
        category = children[0] if children else None
    return path


def parameters(product: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for param in product.get("Parameters") or []:
        key = param.get("ParameterText")
        value = param.get("ValueText")
        if key and value not in (None, "", "-"):
            out[str(key)] = str(value)
    return out


def price_breaks(variation: dict[str, Any]) -> list[dict[str, float]]:
    breaks = [
        {"qty": int(p["BreakQuantity"]), "unit_price": float(p["UnitPrice"])}
        for p in variation.get("StandardPricing") or []
        if p.get("BreakQuantity") is not None and p.get("UnitPrice") is not None
    ]
    return sorted(breaks, key=lambda b: b["qty"])


def variations(product: dict[str, Any], max_breaks: int | None = None) -> list[dict[str, Any]]:
    out = []
    for v in product.get("ProductVariations") or []:
        breaks = price_breaks(v)
        out.append(
            {
                "digikey_pn": v.get("DigiKeyProductNumber"),
                "packaging": _name(v.get("PackageType")),
                "stock": v.get("QuantityAvailableforPackageType"),
                "min_order_qty": v.get("MinimumOrderQuantity"),
                "standard_package": v.get("StandardPackage"),
                "price_breaks": breaks[:max_breaks] if max_breaks else breaks,
            }
        )
    return out


def status(product: dict[str, Any]) -> str | None:
    s = product.get("ProductStatus")
    if isinstance(s, dict):
        return s.get("Status")
    return s


def summarize(product: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
    """Compact summary. `full=True` adds every parameter and all price breaks."""
    desc = product.get("Description") or {}
    classifications = product.get("Classifications") or {}
    out: dict[str, Any] = {
        "mpn": product.get("ManufacturerProductNumber"),
        "manufacturer": _name(product.get("Manufacturer")),
        "description": desc.get("ProductDescription"),
        "detailed_description": desc.get("DetailedDescription"),
        "stock": product.get("QuantityAvailable"),
        "unit_price": product.get("UnitPrice"),
        "status": status(product),
        "datasheet_url": fix_url(product.get("DatasheetUrl")),
        "product_url": fix_url(product.get("ProductUrl")),
        "category": " > ".join(category_path(product.get("Category"))) or None,
    }
    packs = variations(product, max_breaks=None if full else 3)
    out["digikey_pns"] = [p["digikey_pn"] for p in packs if p["digikey_pn"]]
    if full:
        out.update(
            {
                "series": _name(product.get("Series")),
                "base_product": _name(product.get("BaseProductNumber")),
                "photo_url": fix_url(product.get("PhotoUrl")),
                "rohs": classifications.get("RohsStatus"),
                "reach": classifications.get("ReachStatus"),
                "moisture_sensitivity": classifications.get("MoistureSensitivityLevel"),
                "lead_time_weeks": product.get("ManufacturerLeadWeeks"),
                "end_of_life": product.get("EndOfLife"),
                "discontinued": product.get("Discontinued"),
                "normally_stocking": product.get("NormallyStocking"),
                "parameters": parameters(product),
                "packaging_options": packs,
            }
        )
    else:
        params = parameters(product)
        # The first few parameters (package, key ratings) are what a reader scans for.
        out["key_parameters"] = dict(list(params.items())[:8])
    return {k: v for k, v in out.items() if v not in (None, "", [], {})}


def unit_price_at(breaks: list[dict[str, float]], qty: int) -> float | None:
    unit = None
    for b in breaks:
        if b["qty"] <= qty:
            unit = b["unit_price"]
    return unit


def best_offer(product: dict[str, Any], qty: int) -> dict[str, Any]:
    """Cheapest packaging option for `qty` pieces, using standard price breaks.

    Packaging that needs more than `qty` pieces (a full reel, say) is skipped, and so is
    packaging with no standard pricing (Digi-Reel, which adds a reeling fee).
    """
    options = []
    for v in variations(product):
        breaks = v["price_breaks"]
        moq = int(v["min_order_qty"] or (breaks[0]["qty"] if breaks else 1))
        if not breaks or qty < moq:
            continue
        unit = unit_price_at(breaks, qty)
        if unit is None:
            continue
        next_break = next((b for b in breaks if b["qty"] > qty), None)
        options.append(
            {
                "digikey_pn": v["digikey_pn"],
                "packaging": v["packaging"],
                "unit_price": unit,
                "extended_price": round(unit * qty, 4),
                "stock": v["stock"],
                "in_stock": v["stock"] is not None and v["stock"] >= qty,
                "next_break": next_break,
            }
        )
    options.sort(key=lambda o: (not o["in_stock"], o["extended_price"]))
    return {
        "quantity": qty,
        "best": options[0] if options else None,
        "other_options": options[1:],
    }
