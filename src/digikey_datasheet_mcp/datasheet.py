"""Download datasheet PDFs, cache their text, and find the sections engineers ask about.

The goal is to hand the model the *right pages* (pinout, absolute maximum ratings,
electrical characteristics...) instead of a 120-page PDF. Sections are located from the
PDF's bookmarks when it has them, and from heading-like lines otherwise.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import ipaddress
import json
import re
import socket
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

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


def local_pdf_path(text: str) -> Path | None:
    """A local PDF given as a path or file:// URL, else None."""
    text = text.strip().strip('"')
    if text.lower().startswith("file://"):
        parsed = urlparse(text)
        raw = unquote(parsed.path)
        # file:///C:/x.pdf -> C:/x.pdf on Windows
        if re.match(r"^/[A-Za-z]:/", raw):
            raw = raw[1:]
        text = raw
    if not text.lower().endswith(".pdf"):
        return None
    # Absolute (POSIX or Windows drive / UNC), home-relative or explicitly relative paths only,
    # so a part number that happens to end in ".pdf" is never mistaken for a file.
    if not re.match(r"^(?:[A-Za-z]:[\\/]|[\\/]|~|\.{1,2}[\\/])", text):
        return None
    return Path(text).expanduser()


def _is_private_address(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host.strip("[]").split("%")[0])
    except ValueError:
        return False
    return not ip.is_global


async def check_public_url(url: str) -> None:
    """Refuse URLs pointing at this machine or the local network (SSRF guard).

    A datasheet URL can come from text the model read, so it must not be able to reach
    127.0.0.1, router admin pages or cloud metadata endpoints.
    """
    host = (urlparse(url).hostname or "").lower()
    if not host:
        raise DatasheetError(f"Not an http(s) URL: {url!r}")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or _is_private_address(host):
        raise DatasheetError(
            f"Refusing to fetch {host}: it is a local or private address. "
            "Set DATASHEET_ALLOW_PRIVATE=true to allow intranet datasheet servers."
        )
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return  # let the HTTP client report the DNS failure
    for info in infos:
        if _is_private_address(str(info[4][0])):
            raise DatasheetError(
                f"Refusing to fetch {host}: it resolves to a private address. "
                "Set DATASHEET_ALLOW_PRIVATE=true to allow intranet datasheet servers."
            )


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


CACHE_VERSION = 2
MEMORY_DOCS = 12
MAX_REDIRECTS = 8


class DatasheetStore:
    """Fetches PDFs (or reads local ones) and caches extracted text, keyed by URL."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._http = http or httpx.AsyncClient(
            timeout=max(settings.timeout, 60),
            headers={
                # Several manufacturer sites refuse requests without a browser-like agent.
                "User-Agent": "Mozilla/5.0 (compatible; digikey-datasheet-mcp; +https://github.com/Sharkeeeeeee/digikey-datasheet-mcp)",
                "Accept": "application/pdf,text/html;q=0.8,*/*;q=0.5",
            },
        )
        self._memory: OrderedDict[str, Document] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()[:24]
        return self.settings.cache_dir / "datasheets" / f"{digest}.json"

    def _load_cached(self, url: str) -> Document | None:
        path = self._cache_path(url)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("version") != CACHE_VERSION or data.get("url") != url:
                return None
            return Document(url=url, pages=data["pages"], title=data.get("title"), bookmarks=data.get("bookmarks", []))
        except (OSError, ValueError, KeyError, AttributeError):
            return None

    def _save_cached(self, doc: Document) -> None:
        path = self._cache_path(doc.url)
        payload = {
            "version": CACHE_VERSION,
            "url": doc.url,
            "title": doc.title,
            "pages": doc.pages,
            "bookmarks": doc.bookmarks,
        }
        tmp = path.with_suffix(".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(path)  # atomic, so a crash never leaves a half-written cache file
        except OSError:
            pass  # caching is an optimisation only

    def _remember(self, key: str, doc: Document) -> Document:
        self._memory[key] = doc
        self._memory.move_to_end(key)
        while len(self._memory) > MEMORY_DOCS:
            self._memory.popitem(last=False)
        return doc

    async def _fetch(self, url: str) -> tuple[bytes, str]:
        """GET with manual redirects so every hop passes the private-address check."""
        limit = self.settings.max_pdf_mb * 1024 * 1024
        for _ in range(MAX_REDIRECTS + 1):
            if not self.settings.allow_private_urls:
                await check_public_url(url)
            try:
                async with self._http.stream("GET", url, follow_redirects=False) as response:
                    if response.is_redirect and response.headers.get("location"):
                        url = normalize_url(urljoin(url, response.headers["location"]))
                        continue
                    if response.status_code >= 400:
                        raise DatasheetError(f"Datasheet download failed: HTTP {response.status_code} for {url}")
                    declared = response.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > limit:
                        raise DatasheetError(f"Datasheet is larger than {self.settings.max_pdf_mb} MB.")
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise DatasheetError(f"Datasheet is larger than {self.settings.max_pdf_mb} MB.")
                        chunks.append(chunk)
                    return b"".join(chunks), url
            except httpx.HTTPError as exc:
                raise DatasheetError(f"Could not download the datasheet: {exc}") from exc
        raise DatasheetError("Too many redirects while downloading the datasheet.")

    async def _download(self, url: str) -> bytes:
        for _ in range(2):  # the URL itself, then at most one PDF link found in an HTML page
            data, final_url = await self._fetch(url)
            if b"%PDF-" in data[:1024]:
                return data
            link = _find_pdf_link(data[:500_000].decode("utf-8", "replace"), final_url)
            if not link:
                break
            url = normalize_url(link)
        raise DatasheetError(
            "The URL did not return a PDF (probably a landing page or a bot check). "
            "Open it in a browser and pass the direct PDF link instead, or download it and pass the file path."
        )

    @staticmethod
    def _check_text(doc: Document) -> Document:
        if not any(p.strip() for p in doc.pages):
            raise DatasheetError(
                "The PDF has no extractable text (it is probably scanned images). OCR is not supported."
            )
        return doc

    async def _get_local(self, path: Path) -> Document:
        try:
            stat = path.stat()
        except OSError as exc:
            raise DatasheetError(f"Cannot open {path}: {exc.strerror or exc}") from exc
        key = f"file://{path.resolve()}?{stat.st_mtime_ns}-{stat.st_size}"
        if key in self._memory:
            self._memory.move_to_end(key)
            return self._memory[key]
        if stat.st_size > self.settings.max_pdf_mb * 1024 * 1024:
            raise DatasheetError(f"Datasheet is larger than {self.settings.max_pdf_mb} MB.")
        data = await asyncio.to_thread(path.read_bytes)
        if b"%PDF-" not in data[:1024]:
            raise DatasheetError(f"{path} is not a PDF file.")
        doc = await asyncio.to_thread(parse_pdf, data, str(path))
        return self._remember(key, self._check_text(doc))

    async def get(self, source: str) -> Document:
        """Open a datasheet from an http(s) URL, a file:// URL or a local .pdf path."""
        local = local_pdf_path(source)
        if local is not None:
            return await self._get_local(local)
        url = normalize_url(source)
        if url in self._memory:
            self._memory.move_to_end(url)
            return self._memory[url]
        # One download per URL even when several tool calls ask for it at once.
        lock = self._locks.setdefault(url, asyncio.Lock())
        async with lock:
            if url in self._memory:
                return self._memory[url]
            doc = self._load_cached(url)
            if doc is None:
                data = await self._download(url)
                doc = self._check_text(await asyncio.to_thread(parse_pdf, data, url))
                self._save_cached(doc)
            self._remember(url, doc)
        self._locks.pop(url, None)
        return doc
