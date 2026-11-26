"""Read a pasted BOM (CSV/TSV from KiCad, Altium, Excel...) into part/quantity lines."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

PART_COLUMNS = (
    "manufacturer part number",
    "manufacturer part",
    "mfr part number",
    "mfr part #",
    "mfr. #",
    "mfr #",
    "mpn",
    "part number",
    "partnumber",
    "digi-key part number",
    "digikey part number",
    "digikey",
    "digi-key",
    "dk part number",
)
QTY_COLUMNS = ("quantity", "qty", "qty.", "quantity per pcb", "count", "amount")
REF_COLUMNS = ("reference", "references", "designator", "designators", "ref", "refs", "reference designators")


class BomError(ValueError):
    pass


@dataclass
class ParsedLine:
    part_number: str
    quantity: int
    reference: str | None = None


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().strip('"').lower())


def _pick(header: list[str], wanted: tuple[str, ...]) -> int | None:
    names = [_norm(h) for h in header]
    for want in wanted:  # earlier entries are preferred (MPN over DigiKey PN)
        if want in names:
            return names.index(want)
    return None


def _cell(row: list[str], index: int | None) -> str:
    return row[index].strip() if index is not None and index < len(row) else ""


def parse_bom(text: str) -> list[ParsedLine]:
    text = text.strip().lstrip("﻿")
    if not text:
        raise BomError("The BOM is empty.")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if "\t" in sample else csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise BomError("The BOM needs a header row and at least one part row.")
    header, body = rows[0], rows[1:]
    part_col = _pick(header, PART_COLUMNS)
    if part_col is None:
        raise BomError(
            "Could not find a part number column. Name it 'MPN', 'Manufacturer Part Number' or "
            f"'DigiKey Part Number'. Columns seen: {', '.join(h.strip() for h in header)}"
        )
    qty_col = _pick(header, QTY_COLUMNS)
    ref_col = _pick(header, REF_COLUMNS)
    lines: list[ParsedLine] = []
    for row in body:
        part = _cell(row, part_col)
        if not part or part.lower() in {"dnp", "dnf", "n/a", "-", "~"}:
            continue
        ref = _cell(row, ref_col) or None
        qty_text = _cell(row, qty_col)
        if qty_text:
            match = re.match(r"\d+", qty_text.replace(",", ""))
            if not match:
                raise BomError(f"Quantity {qty_text!r} for {part} is not a whole number.")
            qty = int(match.group())
        elif ref:
            qty = len([r for r in re.split(r"[,;\s]+", ref) if r])
        else:
            qty = 1
        if qty > 0:
            lines.append(ParsedLine(part, qty, ref))
    if not lines:
        raise BomError("No part rows found in the BOM.")
    return lines
