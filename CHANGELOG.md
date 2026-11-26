# Changelog

## 0.1.0 - 2026-11-26

First release.

- DigiKey Product Information v4: `search_parts`, `get_part`, `get_price`, `find_alternatives`, `compare_parts`, `price_bom`.
- LCSC / JLCPCB search without an API key: `search_lcsc`.
- Datasheet reading: `datasheet_outline`, `datasheet_section` (with a best-effort pin table), `datasheet_search`, `datasheet_pages`, with an on-disk text cache.
- `--check` to verify DigiKey credentials.
