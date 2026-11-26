# digikey-datasheet-mcp

**Ask your AI about real parts: DigiKey search, live stock and pricing, BOM costing, LCSC lookup, and datasheets it actually reads.**

[![CI](https://github.com/Sharkeeeeeee/digikey-datasheet-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/Sharkeeeeeee/digikey-datasheet-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![MCP](https://img.shields.io/badge/MCP-server-8A2BE2)

English | [繁體中文](README.zh-TW.md)

An [MCP](https://modelcontextprotocol.io) server for Claude, Cursor, VS Code and any other MCP client. It turns "find me a 3.3 V LDO in SOT-23 that's in stock" or "what's the absolute max on the EN pin?" into answers backed by DigiKey's official API and the part's own datasheet, with page numbers.

An example session (numbers are illustrative):

```text
You:     Find a 3.3 V, 500 mA LDO in SOT-23-5 under $0.50 at 100 pcs, then tell me
         its dropout voltage and what the EN pin does.

Claude:  → search_parts("LDO 3.3V 500mA SOT-23-5", in_stock=true, sort="price")
         → get_price("TPS7A2033PDBVR", 100)
         → datasheet_section("TPS7A2033PDBVR", "electrical_characteristics")
         → datasheet_section("TPS7A2033PDBVR", "pinout")

         TPS7A2033PDBVR (Texas Instruments): $0.21 each at 100 pcs on cut tape,
         41,000 in stock. Dropout is 180 mV typ / 300 mV max at 300 mA (p. 6).
         EN is pin 3, active high, and must not be left floating (p. 4)...
```

## Why this one

- **Reads datasheets, not just links to them.** Finds the pinout, absolute maximum ratings, recommended operating conditions, electrical characteristics, thermal, package and ordering sections (from PDF bookmarks, or headings when there are none) and hands the model just those pages, plus a best-effort pin table. Works on any PDF URL or a PDF on your disk, not only DigiKey's.
- **Real buying answers.** `get_price` finds the cheapest way to buy your quantity, including whole reels topped up with cut tape (3,500 pcs = one 3,000 reel + 500 cut tape), and shows the next price break. `price_bom` takes a pasted KiCad/Altium/Excel BOM, merges duplicate rows, adds attrition spares, costs it for N boards, flags missing, out-of-stock and obsolete parts, and can suggest in-stock substitutes.
- **Compare and replace.** Side-by-side parameter tables, and DigiKey's own substitutes for parts that went obsolete.
- **Works without keys too.** `search_lcsc` (LCSC / JLCPCB assembly parts) and the datasheet tools on a URL need no account. Add DigiKey keys when you want the rest.
- **Your keys stay yours.** Runs locally over stdio. Credentials go to `api.digikey.com` and nowhere else. Every tool is read-only: no carts, no orders. Datasheet downloads refuse localhost and private-network addresses, so a URL planted in a document can't probe your network.
- **Tested.** 97 tests against a mocked DigiKey API and generated PDFs, on Linux, macOS and Windows, Python 3.10 to 3.13.

## Tools

| Tool | What it does | Needs DigiKey keys |
| --- | --- | :---: |
| `search_parts` | Keyword / part-number search; filters for stock, minimum stock, max price, RoHS, active-only, manufacturer; sort by price or stock | ✓ |
| `get_part` | Every parameter, packaging options and price breaks, lifecycle, RoHS, lead time | ✓ |
| `get_price` | Best price for a quantity across packaging types (incl. reel + cut tape), with the next price break | ✓ |
| `find_alternatives` | DigiKey substitutes (direct, similar, upgrade) with stock and price | ✓ |
| `compare_parts` | Markdown comparison table of 2 to 6 parts, highlighting what differs | ✓ |
| `price_bom` | Cost a BOM (items or pasted CSV, up to 100 distinct parts) for N boards with spares, warnings and optional substitutes | ✓ |
| `search_lcsc` | LCSC / JLCPCB parts: LCSC code, stock, price, basic/preferred status | |
| `datasheet_outline` | Page count, bookmarks and where each key section starts | for part numbers |
| `datasheet_section` | Text of one section (pinout, absolute_maximum_ratings, electrical_characteristics, ...) | for part numbers |
| `datasheet_search` | Find a term (e.g. "I2C address", "quiescent current") with page numbers | for part numbers |
| `datasheet_pages` | Raw text of a page range | for part numbers |

The datasheet tools take a part number (looked up on DigiKey), a datasheet URL, or a local PDF path such as `C:\datasheets\lm358.pdf` (no keys needed for the last two).

## Install

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). `uvx` downloads and runs the server, so there is nothing else to install.

### Claude Code

```bash
claude mcp add digikey \
  -e DIGIKEY_CLIENT_ID=your-client-id \
  -e DIGIKEY_CLIENT_SECRET=your-client-secret \
  -- uvx digikey-datasheet-mcp
```

### Claude Desktop, Cursor, VS Code, Windsurf...

Add this to the client's MCP config (`claude_desktop_config.json`, `.cursor/mcp.json`, ...):

```json
{
  "mcpServers": {
    "digikey": {
      "command": "uvx",
      "args": ["digikey-datasheet-mcp"],
      "env": {
        "DIGIKEY_CLIENT_ID": "your-client-id",
        "DIGIKEY_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

Leave out `env` to start with only the LCSC and datasheet-URL tools.

<details>
<summary>Run straight from GitHub (latest main)</summary>

```json
"args": ["--from", "git+https://github.com/Sharkeeeeeee/digikey-datasheet-mcp", "digikey-datasheet-mcp"]
```
</details>

## Get DigiKey API keys (free, about 3 minutes)

1. Sign in at [developer.digikey.com](https://developer.digikey.com) with a DigiKey account.
2. **Organizations** → create one (any name) → **Production Apps** → **Create Production App**.
3. Give it a name, any OAuth callback URL (e.g. `https://localhost`), and tick **ProductInformation V4**.
4. Open the app and copy the **Client ID** and **Client Secret**.
5. Check them:

   ```bash
   DIGIKEY_CLIENT_ID=... DIGIKEY_CLIENT_SECRET=... uvx digikey-datasheet-mcp --check
   # OK: DigiKey production API reachable, 1234 results for NE555 (site US, USD).
   ```

DigiKey's default quota for a new app is around 1,000 requests per day, plenty for interactive use. This server uses the 2-legged (client credentials) flow, so there is no browser login.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `DIGIKEY_CLIENT_ID` / `DIGIKEY_CLIENT_SECRET` | | Your DigiKey app credentials |
| `DIGIKEY_LOCALE_SITE` | `US` | DigiKey site, e.g. `TW`, `DE`, `UK`, `JP`, `CN` |
| `DIGIKEY_LOCALE_CURRENCY` | `USD` | Price currency, e.g. `TWD`, `EUR`, `GBP`, `JPY` |
| `DIGIKEY_LOCALE_LANGUAGE` | `en` | Description language, e.g. `zht`, `de`, `ja` |
| `DIGIKEY_CUSTOMER_ID` | `0` | Your customer number, for account-specific pricing |
| `DIGIKEY_SANDBOX` | `false` | `true` to use a Sandbox app |
| `DIGIKEY_MCP_CACHE_DIR` | `~/.cache/digikey-datasheet-mcp` | Where extracted datasheet text is cached |
| `DATASHEET_MAX_MB` | `50` | Largest PDF to download |
| `DATASHEET_ALLOW_PRIVATE` | `false` | `true` to allow datasheet URLs on localhost / your intranet |
| `LCSC_SEARCH_URL` | `https://jlcsearch.tscircuit.com` | LCSC index; point at a self-hosted [jlcsearch](https://github.com/tscircuit/jlcsearch) if you like |

## How datasheet reading works

1. The PDF is downloaded once (following a landing page to its PDF link if needed) and its text is cached on disk, page by page.
2. Sections are located from the PDF's bookmarks when present. Otherwise the server looks for heading-like lines (`6.1 Absolute Maximum Ratings`) and ignores the table of contents and in-sentence mentions ("see Absolute Maximum Ratings").
3. `datasheet_section` returns the section from its heading up to the next known section, across page breaks, with `[page N]` markers so answers can cite pages.

Limits worth knowing: scanned (image-only) PDFs have no text and are reported as such; tables come out as text rows, so the model reads columns from context; the pin table is a heuristic and is labelled `pins_guess`. Some manufacturer sites block automated downloads; then pass a direct PDF link.

## Example prompts

- "Cost this BOM for 50 boards with 5% spares, and suggest replacements for anything out of stock:" followed by a pasted CSV BOM
- "Read ~/Downloads/ADS1115.pdf and give me the I2C address options."
- "Compare TPS7A2033PDBVR, AP2112K-3.3TRG1 and MCP1700T-3302E/TT for a battery-powered sensor."
- "LM1117 is obsolete in my design. What are drop-in replacements in stock?"
- "From the STM32F103C8 datasheet, list the 5 V tolerant pins."
- "Find a JLCPCB basic part for a 10 kΩ 0402 resistor."

## Development

```bash
git clone https://github.com/Sharkeeeeeee/digikey-datasheet-mcp
cd digikey-datasheet-mcp
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Try it in the MCP Inspector: `npx @modelcontextprotocol/inspector uv run digikey-datasheet-mcp`.

## License

MIT. Not affiliated with or endorsed by DigiKey, LCSC or JLCPCB. Product data comes from their services and is subject to their terms.
