# digikey-datasheet-mcp

**讓 AI 查真正買得到的零件：DigiKey 搜尋、即時庫存與價格、BOM 報價、LCSC 查詢，還會真的去讀 datasheet。**

[![CI](https://github.com/Sharkeeeeeee/digikey-datasheet-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/Sharkeeeeeee/digikey-datasheet-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![MCP](https://img.shields.io/badge/MCP-server-8A2BE2)

[English](README.md) | 繁體中文

這是一個 [MCP](https://modelcontextprotocol.io) 伺服器，可接上 Claude、Cursor、VS Code 等任何 MCP 用戶端。像「幫我找一顆有現貨、SOT-23 包裝的 3.3 V LDO」或「EN 腳的絕對最大額定是多少？」這類問題，答案會來自 DigiKey 官方 API 和該零件自己的 datasheet，並附上頁碼。

範例對話（數字僅供示意）：

```text
你：     幫我找 SOT-23-5、3.3 V、500 mA 的 LDO，100 顆單價低於 0.5 美元，
         再告訴我它的 dropout 電壓和 EN 腳的功能。

Claude： → search_parts("LDO 3.3V 500mA SOT-23-5", in_stock=true, sort="price")
         → get_price("TPS7A2033PDBVR", 100)
         → datasheet_section("TPS7A2033PDBVR", "electrical_characteristics")
         → datasheet_section("TPS7A2033PDBVR", "pinout")

         TPS7A2033PDBVR（Texas Instruments）：剪帶包裝 100 顆每顆 $0.21，
         庫存 41,000。Dropout 在 300 mA 時典型 180 mV、最大 300 mV（第 6 頁）。
         EN 是第 3 腳，高電位致能，不可浮接（第 4 頁）……
```

## 特色

- **真的讀 datasheet，不只給連結。** 自動找出腳位（pinout）、絕對最大額定、建議操作條件、電氣特性、熱特性、封裝、訂購資訊等章節（優先用 PDF 書籤，沒有書籤就找標題），只把那幾頁交給模型，另附自動解析的腳位表。任何 PDF 網址都能用，不限 DigiKey。
- **能直接拿來採購的答案。** `get_price` 會依數量挑最便宜的包裝（剪帶或整捲，略過要加收捲帶費的 Digi-Reel），並顯示下一個價格級距。`price_bom` 可以算 N 片板子的整份 BOM 成本，標出找不到、缺貨與停產的料。
- **比較與替代料。** 並排比較參數表，停產料直接查 DigiKey 官方的替代建議。
- **沒有金鑰也能用。** `search_lcsc`（LCSC／JLCPCB 組裝料）和用網址讀 datasheet 都不需要帳號，之後再加 DigiKey 金鑰即可解鎖其他功能。
- **金鑰只在你手上。** 在本機以 stdio 執行，憑證只會送到 `api.digikey.com`。所有工具都是唯讀，不會加入購物車或下單。
- **有完整測試。** 58 個測試，以模擬的 DigiKey API 和自動產生的 PDF 執行，涵蓋 Linux、macOS、Windows 與 Python 3.10 到 3.13。

## 工具一覽

| 工具 | 功能 | 需要 DigiKey 金鑰 |
| --- | --- | :---: |
| `search_parts` | 關鍵字或料號搜尋，可篩選有庫存、RoHS、排序、製造商 | ✓ |
| `get_part` | 完整參數、各種包裝與價格級距、生命週期、RoHS、交期 | ✓ |
| `get_price` | 指定數量的最佳價格（跨包裝比較）與下一個價格級距 | ✓ |
| `find_alternatives` | DigiKey 替代料（直接替代、相似、升級），含庫存與價格 | ✓ |
| `compare_parts` | 2 到 6 顆零件的 Markdown 比較表，標出差異參數 | ✓ |
| `price_bom` | 計算最多 100 行 BOM、N 片板子的成本並給出警告 | ✓ |
| `search_lcsc` | LCSC／JLCPCB 零件：C 編號、庫存、價格、基礎庫／優選庫 | |
| `datasheet_outline` | 頁數、書籤、各重要章節的起始頁 | 用料號時需要 |
| `datasheet_section` | 取出單一章節文字（pinout、absolute_maximum_ratings、electrical_characteristics…） | 用料號時需要 |
| `datasheet_search` | 在 datasheet 中搜尋詞彙（如「I2C address」）並回傳頁碼 | 用料號時需要 |
| `datasheet_pages` | 取出指定頁範圍的原始文字 | 用料號時需要 |

datasheet 工具可以輸入料號（透過 DigiKey 查出 datasheet）或直接輸入 PDF 網址（不需金鑰）。

## 安裝

先安裝 [uv](https://docs.astral.sh/uv/getting-started/installation/)。`uvx` 會自動下載並執行伺服器，不用另外安裝其他東西。

### Claude Code

```bash
claude mcp add digikey \
  -e DIGIKEY_CLIENT_ID=你的-client-id \
  -e DIGIKEY_CLIENT_SECRET=你的-client-secret \
  -e DIGIKEY_LOCALE_SITE=TW \
  -e DIGIKEY_LOCALE_CURRENCY=TWD \
  -- uvx digikey-datasheet-mcp
```

### Claude Desktop、Cursor、VS Code、Windsurf…

加入用戶端的 MCP 設定檔（`claude_desktop_config.json`、`.cursor/mcp.json` 等）：

```json
{
  "mcpServers": {
    "digikey": {
      "command": "uvx",
      "args": ["digikey-datasheet-mcp"],
      "env": {
        "DIGIKEY_CLIENT_ID": "你的-client-id",
        "DIGIKEY_CLIENT_SECRET": "你的-client-secret",
        "DIGIKEY_LOCALE_SITE": "TW",
        "DIGIKEY_LOCALE_CURRENCY": "TWD"
      }
    }
  }
}
```

不填 `env` 也能啟動，此時只有 LCSC 與 datasheet 網址相關工具可用。

<details>
<summary>直接從 GitHub 執行（最新 main）</summary>

```json
"args": ["--from", "git+https://github.com/Sharkeeeeeee/digikey-datasheet-mcp", "digikey-datasheet-mcp"]
```
</details>

## 申請 DigiKey API 金鑰（免費，約 3 分鐘）

1. 用 DigiKey 帳號登入 [developer.digikey.com](https://developer.digikey.com)。
2. **Organizations** → 建立一個組織（名稱隨意）→ **Production Apps** → **Create Production App**。
3. 填入名稱、任意 OAuth callback URL（例如 `https://localhost`），並勾選 **ProductInformation V4**。
4. 打開這個 app，複製 **Client ID** 和 **Client Secret**。
5. 驗證：

   ```bash
   DIGIKEY_CLIENT_ID=... DIGIKEY_CLIENT_SECRET=... uvx digikey-datasheet-mcp --check
   # OK: DigiKey production API reachable, 1234 results for NE555 (site US, USD).
   ```

新 app 的預設額度大約每天 1,000 次請求，互動使用綽綽有餘。本伺服器使用 2-legged（client credentials）流程，不需要瀏覽器登入。

## 設定

| 環境變數 | 預設值 | 說明 |
| --- | --- | --- |
| `DIGIKEY_CLIENT_ID` / `DIGIKEY_CLIENT_SECRET` | | DigiKey app 憑證 |
| `DIGIKEY_LOCALE_SITE` | `US` | DigiKey 站點，台灣用 `TW` |
| `DIGIKEY_LOCALE_CURRENCY` | `USD` | 幣別，新台幣用 `TWD` |
| `DIGIKEY_LOCALE_LANGUAGE` | `en` | 描述語言，繁中用 `zht` |
| `DIGIKEY_CUSTOMER_ID` | `0` | 客戶編號，用於帳號專屬價格 |
| `DIGIKEY_SANDBOX` | `false` | 使用 Sandbox app 時設為 `true` |
| `DIGIKEY_MCP_CACHE_DIR` | `~/.cache/digikey-datasheet-mcp` | datasheet 文字快取位置 |
| `DATASHEET_MAX_MB` | `50` | 可下載的 PDF 大小上限 |
| `LCSC_SEARCH_URL` | `https://jlcsearch.tscircuit.com` | LCSC 索引來源，可改成自架的 [jlcsearch](https://github.com/tscircuit/jlcsearch) |

## datasheet 解析原理

1. PDF 只下載一次（若網址是產品頁，會自動找出其中的 PDF 連結），逐頁文字快取在本機。
2. 有書籤就用書籤定位章節；沒有的話，找像 `6.1 Absolute Maximum Ratings` 這樣的標題行，並略過目錄頁與句中提及（例如「see Absolute Maximum Ratings」）。
3. `datasheet_section` 從章節標題一路取到下一個已知章節，可跨頁，並加上 `[page N]` 標記，讓回答能引用頁碼。

限制：掃描圖檔型 PDF 沒有文字，會直接回報；表格會變成文字列，由模型依上下文判讀欄位；腳位表是啟發式解析，欄位名稱為 `pins_guess`。部分原廠網站會擋自動下載，此時請改給 PDF 直連網址。

## 提示詞範例

- 「幫我算這份 BOM 做 50 片的成本，並告訴我哪些缺貨：」後面貼上 BOM
- 「比較 TPS7A2033PDBVR、AP2112K-3.3TRG1、MCP1700T-3302E/TT，用在電池供電的感測器上哪個好？」
- 「我設計裡的 LM1117 停產了，有哪些有現貨的 pin-to-pin 替代料？」
- 「根據 STM32F103C8 的 datasheet，列出所有 5 V tolerant 的腳位。」
- 「找一顆 JLCPCB 基礎庫的 0402 10 kΩ 電阻。」

## 開發

```bash
git clone https://github.com/Sharkeeeeeee/digikey-datasheet-mcp
cd digikey-datasheet-mcp
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

用 MCP Inspector 試玩：`npx @modelcontextprotocol/inspector uv run digikey-datasheet-mcp`。

## 授權

MIT。本專案與 DigiKey、LCSC、JLCPCB 無任何關聯，也未經其背書。產品資料來自上述服務，並受其使用條款約束。
