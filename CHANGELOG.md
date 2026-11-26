# Changelog

## 0.1.0 - 2026-11-26

First release.

- DigiKey Product Information v4: `search_parts`, `get_part`, `get_price`, `find_alternatives`, `compare_parts`, `price_bom`.
- LCSC / JLCPCB search without an API key: `search_lcsc`.
- Datasheet reading: `datasheet_outline`, `datasheet_section` (with a best-effort pin table), `datasheet_search`, `datasheet_pages`, with an on-disk text cache.
- `--check` to verify DigiKey credentials.

### Added after the initial push
- `get_price` / `price_bom`: full reels and trays are bought in whole packages, topped up with cut tape.
- `price_bom`: `bom_csv` (paste a KiCad/Altium/Excel BOM), duplicate rows merged, `spare_percent`, `suggest_alternatives`.
- `search_parts`: `min_stock`, `max_unit_price`, `active_only`; duplicates removed; filters fetch a full page.
- Datasheet tools read local PDFs (path or `file://`).
- `compare_parts` reports unknown parts instead of failing.

### Fixed
- Reels were priced at quantities that are not whole reels.
- Datasheet downloads now refuse localhost and private-network addresses on every redirect hop (`DATASHEET_ALLOW_PRIVATE` to opt out).
- One download per datasheet when several tool calls ask at once; in-memory cache is bounded; disk cache is versioned and written atomically.
- PDFs with bytes before `%PDF-` were rejected.
- Bad `DIGIKEY_MCP_TIMEOUT` / `DATASHEET_MAX_MB` values crash with a clear message instead of a traceback.
- Non-JSON or malformed DigiKey responses give a clean error.
- `datasheet_pages` rejects a reversed page range.
