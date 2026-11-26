"""Download datasheet PDFs, cache their text, and find the sections engineers ask about.

The goal is to hand the model the *right pages* (pinout, absolute maximum ratings,
electrical characteristics...) instead of a 120-page PDF. Sections are located from the
PDF's bookmarks when it has them, and from heading-like lines otherwise.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from pypdf import PdfReader

from .config import Settings

SECTIONS: dict[str, str] = {
    "pinout": r"pin\s*(?:-\s*)?(?:out|configurations?|descriptions?|assignments?|functions?|definitions?)"
    r"|terminal\s+(?:configuration|functions?)|ball\s+(?:map|assignments?)|signal\s+descriptions?",
    "absolute_maximum_ratings": r"absolute\s+maximum\s+ratings?",
    "recommended_operating_conditions": r"recommended\s+operating\s+conditions?",
    "electrical_characteristics": r"(?:dc\s+|ac\s+)?electrical\s+(?:characteristics|specifications)"
    r"|dc\s+characteristics",
    "thermal": r"thermal\s+(?:information|characteristics|resistance|data)",
    "esd": r"esd\s+(?:ratings?|protection|sensitivity)",
    "timing": r"(?:switching|timing)\s+(?:characteristics|requirements|diagrams?)",
    "typical_application": r"(?:typical\s+)?applications?\s+(?:information|circuits?|schematic)|typical\s+application",
    "package": r"package\s+(?:information|outlines?|dimensions|drawings?)|mechanical\s+(?:data|dimensions|drawings?)",
    "ordering": r"ordering\s+(?:information|guide)|order\s+codes?|device\s+marking",
    "features": r"(?:key\s+)?features\s*$",
}
SECTION_RE = {name: re.compile(rx, re.IGNORECASE) for name, rx in SECTIONS.items()}
_TOC_LINE = re.compile(r"\.{4,}|(?:\s\.){4,}|…{2,}")
_PIN_ROW = re.compile(
    r"^\s*(?P<pin>\d{1,3}|[A-HJ-NPR-Y]{1,2}\d{1,2})(?:\s*,\s*\d{1,3})*\s+"
    r"(?P<name>[A-Za-z][A-Za-z0-9_/\-\.\+#()]{0,24})\s+(?P<rest>.*)$"
)


_NOT_PIN_NAMES = {"pin", "pins", "page", "figure", "table", "see", "note", "v", "ma", "mv", "khz", "mhz"}


class DatasheetError(Exception):
    pass


@dataclass
class Document:
    url: str
    pages: list[str]
    title: str | None = None
    bookmarks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)


def normalize_url(url: str) -> str:
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise DatasheetError(f"Not an http(s) URL: {url!r}")
    return url


def looks_like_url(text: str) -> bool:
    text = text.strip()
    return text.startswith(("http://", "https://", "//"))


def _find_pdf_link(html: str, base: str) -> str | None:
    """Many 'datasheet URLs' are landing pages. Pull the first PDF link out of one."""
    for pattern in (
        r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]+url=([^"'>\s]+)""",
        r"""<(?:iframe|embed)[^>]+src=["']([^"']+)["']""",
        r"""href=["']([^"']+\.pdf(?:\?[^"']*)?)["']""",
    ):
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return urljoin(base, match.group(1))
    return None


def _clean(text: str) -> str:
    text = text.replace("\x00", "").replace("­", "")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_pdf(data: bytes, url: str = "") -> Document:
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [_clean(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:  # pypdf raises many types on damaged files
        raise DatasheetError(f"Could not read the PDF: {exc}") from exc
    title = None
    try:
        meta = reader.metadata
        title = (meta.title or "").strip() or None if meta else None
    except Exception:
        pass
    bookmarks: list[dict[str, Any]] = []

    def walk(items: list[Any], depth: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, depth + 1)
                continue
            try:
                page = reader.get_destination_page_number(item) + 1
                bookmarks.append({"title": str(item.title).strip(), "page": page, "level": depth})
            except Exception:
                continue

    with contextlib.suppress(Exception):
        walk(reader.outline, 0)
    return Document(url=url, pages=pages, title=title, bookmarks=bookmarks)


def _is_toc_page(text: str) -> bool:
    lines = text.splitlines()
    dotted = sum(1 for line in lines if _TOC_LINE.search(line))
    return dotted >= 5 or bool(re.search(r"\b(table of )?contents\b", text[:400], re.IGNORECASE)) and dotted >= 2


def locate_sections(doc: Document) -> dict[str, dict[str, Any]]:
    """Map section name -> {page, heading, via} using bookmarks first, then headings."""
    found: dict[str, dict[str, Any]] = {}
    for mark in doc.bookmarks:
        for name, rx in SECTION_RE.items():
            if name not in found and rx.search(mark["title"]):
                found[name] = {"page": mark["page"], "heading": mark["title"], "via": "bookmark"}
    for index, text in enumerate(doc.pages):
        if _is_toc_page(text):
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or len(stripped) > 90 or _TOC_LINE.search(stripped):
                continue
            for name, rx in SECTION_RE.items():
                if name in found:
                    continue
                match = rx.search(stripped)
                # A heading starts with the phrase (after an optional "7.1" style number)
                # instead of mentioning it mid-sentence ("see Absolute Maximum Ratings").
                prefix = stripped[: match.start()] if match else ""
                if match and re.fullmatch(r"[\d.\s]*(?:table\s+\d+[.:]?\s*)?", prefix, re.IGNORECASE):
                    found[name] = {"page": index + 1, "heading": stripped, "via": "heading"}
    return dict(sorted(found.items(), key=lambda kv: kv[1]["page"]))


def section_text(doc: Document, section: str, max_chars: int = 12000) -> dict[str, Any]:
    sections = locate_sections(doc)
    if section not in sections:
        return {
            "section": section,
            "found": False,
            "available_sections": {k: v["page"] for k, v in sections.items()},
            "hint": "Try datasheet_search with a keyword, or datasheet_pages for a page range.",
        }
    info = sections[section]
    start, heading = info["page"], info["heading"]
    # Other sections' headings, so the excerpt can stop where the next section begins.
    others = [v for k, v in sections.items() if k != section and v["page"] >= start]

    def cut_at_next_heading(page: int, text: str, after: int) -> tuple[str, bool]:
        low = text.lower()
        cuts = [
            pos
            for v in others
            if v["page"] == page and v["via"] == "heading"
            for pos in [low.find(v["heading"].lower(), max(after, 0))]
            if pos > after
        ]
        if cuts:
            return text[: min(cuts)].rstrip(), True
        return text, any(v["page"] == page for v in others) and page != start

    first = doc.pages[start - 1]
    pos = first.lower().find(heading.lower()) if info["via"] == "heading" else -1
    pos = max(pos, 0)
    text, stopped = cut_at_next_heading(start, first[pos:], 1)
    chunks, pages = [text], [start]
    page = start + 1
    # Tables like electrical characteristics often run over two or three pages.
    while not stopped and page <= doc.page_count and page - start < 4 and sum(map(len, chunks)) < max_chars:
        full = doc.pages[page - 1]
        text, stopped = cut_at_next_heading(page, full, -1)
        # Skip a page whose only contribution before the next section is a stray chapter title.
        if text.strip() and (text == full or len(text.strip()) >= 40):
            chunks.append(text)
            pages.append(page)
        page += 1
    text = "\n\n".join(f"[page {p}]\n{c}" for p, c in zip(pages, chunks, strict=True))
    truncated = len(text) > max_chars
    result: dict[str, Any] = {
        "section": section,
        "found": True,
        "heading": heading,
        "pages": pages,
        "text": text[:max_chars],
        "truncated": truncated,
    }
    if section == "pinout":
        pins = extract_pins(text)
        if pins:
            result["pins_guess"] = pins
            result["pins_note"] = "Heuristic parse of the pin table; check it against `text`."
    return result


def extract_pins(text: str, limit: int = 200) -> list[dict[str, str]]:
    """Best-effort parse of rows like '3  VIN  I  Input supply voltage'."""
    pins: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        match = _PIN_ROW.match(line)
        if not match:
            continue
        pin, name, rest = match.group("pin"), match.group("name"), match.group("rest").strip()
        if name.lower() in _NOT_PIN_NAMES or (pin, name) in seen:
            continue
        if len(name) >= 4 and name.isalpha() and name[0].isupper() and name[1:].islower():
            continue  # an English word ("Voltage", "Absolute"), not a signal name
        seen.add((pin, name))
        pins.append({"pin": pin, "name": name, "description": rest[:160]})
        if len(pins) >= limit:
            break
    return pins if len(pins) >= 2 else []


def search(doc: Document, query: str, max_hits: int = 12, context: int = 220) -> list[dict[str, Any]]:
    terms = [t for t in re.split(r"\s+", query.strip().lower()) if t]
    if not terms:
        return []
    hits: list[dict[str, Any]] = []
    for index, text in enumerate(doc.pages):
        low = text.lower()
        start = 0
        while len(hits) < max_hits:
            pos = low.find(terms[0], start)
            if pos < 0:
                break
            window = low[max(0, pos - context) : pos + context]
            if all(t in window for t in terms[1:]):
                a, b = max(0, pos - context), min(len(text), pos + context)
                hits.append({"page": index + 1, "snippet": text[a:b].replace("\n", " ⏎ ")})
                start = pos + context  # one hit per neighbourhood
            else:
                start = pos + 1
        if len(hits) >= max_hits:
            break
    return hits


class DatasheetStore:
    """Fetches PDFs and caches extracted text on disk, keyed by URL."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._http = http or httpx.AsyncClient(
            timeout=max(settings.timeout, 60),
            follow_redirects=True,
            headers={
                # Several manufacturer sites refuse requests without a browser-like agent.
                "User-Agent": "Mozilla/5.0 (compatible; digikey-datasheet-mcp; +https://github.com/Sharkeeeeeee/digikey-datasheet-mcp)",
                "Accept": "application/pdf,text/html;q=0.8,*/*;q=0.5",
            },
        )
        self._memory: dict[str, Document] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()[:24]
        return self.settings.cache_dir / "datasheets" / f"{digest}.json"

    def _load_cached(self, url: str) -> Document | None:
        path = self._cache_path(url)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Document(url=url, pages=data["pages"], title=data.get("title"), bookmarks=data.get("bookmarks", []))
        except (OSError, ValueError, KeyError):
            return None

    def _save_cached(self, doc: Document) -> None:
        path = self._cache_path(doc.url)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"url": doc.url, "title": doc.title, "pages": doc.pages, "bookmarks": doc.bookmarks}
            path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass  # caching is an optimisation only

    async def _download(self, url: str) -> bytes:
        limit = self.settings.max_pdf_mb * 1024 * 1024
        for _ in range(2):  # the URL itself, then at most one PDF link found in an HTML page
            try:
                async with self._http.stream("GET", url) as response:
                    if response.status_code >= 400:
                        raise DatasheetError(f"Datasheet download failed: HTTP {response.status_code} for {url}")
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise DatasheetError(f"Datasheet is larger than {self.settings.max_pdf_mb} MB.")
                        chunks.append(chunk)
                    final_url = str(response.url)
            except httpx.HTTPError as exc:
                raise DatasheetError(f"Could not download the datasheet: {exc}") from exc
            data = b"".join(chunks)
            if data.lstrip()[:5] == b"%PDF-":
                return data
            link = _find_pdf_link(data[:500_000].decode("utf-8", "replace"), final_url)
            if not link:
                break
            url = normalize_url(link)
        raise DatasheetError(
            "The URL did not return a PDF (probably a landing page or a bot check). "
            "Open it in a browser and pass the direct PDF link instead."
        )

    async def get(self, url: str) -> Document:
        url = normalize_url(url)
        if url in self._memory:
            return self._memory[url]
        doc = self._load_cached(url)
        if doc is None:
            doc = parse_pdf(await self._download(url), url)
            if not any(p.strip() for p in doc.pages):
                raise DatasheetError(
                    "The PDF has no extractable text (it is probably scanned images). OCR is not supported."
                )
            self._save_cached(doc)
        self._memory[url] = doc
        return doc
