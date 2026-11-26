"""Realistic DigiKey Product Information v4 payloads (trimmed) and a fake HTTP backend."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from urllib.parse import unquote

import httpx

from digikey_datasheet_mcp.config import Settings

DATASHEET_URL = "https://www.example-semi.com/lit/ds/tps7a99.pdf"


def ldo_product() -> dict:
    return copy.deepcopy(
        {
            "Description": {
                "ProductDescription": "IC REG LINEAR 3.3V 500MA SOT23-5",
                "DetailedDescription": "Linear Voltage Regulator IC Positive Fixed 1 Output 3.3V 500mA SOT-23-5",
            },
            "Manufacturer": {"Id": 296, "Name": "Texas Instruments"},
            "ManufacturerProductNumber": "TPS7A9933DBVR",
            "UnitPrice": 1.12,
            "ProductUrl": "https://www.digikey.com/en/products/detail/texas-instruments/TPS7A9933DBVR/1",
            "DatasheetUrl": "//www.example-semi.com/lit/ds/tps7a99.pdf",
            "PhotoUrl": "//mm.digikey.com/photo.jpg",
            "ProductVariations": [
                {
                    "DigiKeyProductNumber": "296-TPS7A9933DBVRCT-ND",
                    "PackageType": {"Id": 2, "Name": "Cut Tape (CT)"},
                    "StandardPricing": [
                        {"BreakQuantity": 1, "UnitPrice": 1.12, "TotalPrice": 1.12},
                        {"BreakQuantity": 10, "UnitPrice": 0.98, "TotalPrice": 9.8},
                        {"BreakQuantity": 100, "UnitPrice": 0.71, "TotalPrice": 71.0},
                    ],
                    "QuantityAvailableforPackageType": 1500,
                    "MinimumOrderQuantity": 1,
                    "StandardPackage": 1,
                },
                {
                    "DigiKeyProductNumber": "296-TPS7A9933DBVRTR-ND",
                    "PackageType": {"Id": 1, "Name": "Tape & Reel (TR)"},
                    "StandardPricing": [
                        {"BreakQuantity": 3000, "UnitPrice": 0.42, "TotalPrice": 1260.0},
                    ],
                    "QuantityAvailableforPackageType": 9000,
                    "MinimumOrderQuantity": 3000,
                    "StandardPackage": 3000,
                },
                {
                    "DigiKeyProductNumber": "296-TPS7A9933DBVRDKR-ND",
                    "PackageType": {"Id": 243, "Name": "Digi-Reel®"},
                    "StandardPricing": [],
                    "QuantityAvailableforPackageType": 1500,
                    "MinimumOrderQuantity": 1,
                },
            ],
            "QuantityAvailable": 10500,
            "ProductStatus": {"Id": 0, "Status": "Active"},
            "Parameters": [
                {"ParameterId": 16, "ParameterText": "Package / Case", "ValueText": "SC-74A, SOT-753"},
                {"ParameterId": 14, "ParameterText": "Output Configuration", "ValueText": "Positive"},
                {"ParameterId": 2075, "ParameterText": "Voltage - Output (Min/Fixed)", "ValueText": "3.3V"},
                {"ParameterId": 2074, "ParameterText": "Current - Output", "ValueText": "500mA"},
                {"ParameterId": 2073, "ParameterText": "Voltage Dropout (Max)", "ValueText": "0.3V @ 500mA"},
                {"ParameterId": 252, "ParameterText": "Operating Temperature", "ValueText": "-40°C ~ 125°C"},
                {"ParameterId": 999, "ParameterText": "Supplier Device Package", "ValueText": "-"},
            ],
            "Category": {
                "CategoryId": 32,
                "Name": "Integrated Circuits (ICs)",
                "ChildCategories": [
                    {
                        "CategoryId": 2049,
                        "Name": "Power Management (PMIC)",
                        "ChildCategories": [
                            {"CategoryId": 699, "Name": "Voltage Regulators - Linear, Low Drop Out (LDO) Regulators"}
                        ],
                    }
                ],
            },
            "Classifications": {"RohsStatus": "ROHS3 Compliant", "MoistureSensitivityLevel": "2 (1 Year)"},
            "ManufacturerLeadWeeks": "6",
            "Series": {"Name": "TPS7A99"},
            "Discontinued": False,
            "EndOfLife": False,
            "NormallyStocking": True,
        }
    )


def obsolete_product() -> dict:
    p = ldo_product()
    p["ManufacturerProductNumber"] = "LM1117MP-3.3/NOPB"
    p["Manufacturer"] = {"Id": 296, "Name": "Texas Instruments"}
    p["ProductStatus"] = {"Id": 4, "Status": "Obsolete"}
    p["QuantityAvailable"] = 0
    p["UnitPrice"] = 0.55
    for v in p["ProductVariations"]:
        v["QuantityAvailableforPackageType"] = 0
    p["Parameters"][2]["ValueText"] = "3.3V"
    p["Parameters"][3]["ValueText"] = "800mA"
    p["Parameters"][4]["ValueText"] = "1.2V @ 800mA"
    p["DatasheetUrl"] = ""
    return p


PRODUCTS = {
    "TPS7A9933DBVR": ldo_product,
    "296-TPS7A9933DBVRCT-ND": ldo_product,
    "LM1117MP-3.3/NOPB": obsolete_product,
}


def settings(tmp_path, **overrides) -> Settings:
    base = dict(client_id="id", client_secret="secret", cache_dir=tmp_path)
    base.update(overrides)
    return Settings(**base)


class FakeBackend:
    """Routes requests to DigiKey, LCSC and datasheet hosts; records what it saw."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_calls = 0
        self.files: dict[str, tuple[int, bytes, str]] = {}
        self.overrides: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.lcsc_components: list[dict] = []

    def add_file(self, url: str, body: bytes, content_type: str = "application/pdf", status: int = 200) -> None:
        self.files[url] = (status, body, content_type)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        for prefix, fn in self.overrides.items():
            if path.startswith(prefix):
                return fn(request)
        if request.url.host in ("api.digikey.com", "sandbox-api.digikey.com"):
            return self.digikey(request)
        if path == "/api/search":
            return httpx.Response(200, json={"components": self.lcsc_components})
        key = str(request.url)
        if key in self.files:
            status, body, ctype = self.files[key]
            return httpx.Response(status, content=body, headers={"content-type": ctype})
        return httpx.Response(404, text="not found")

    def digikey(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/oauth2/token":
            self.token_calls += 1
            form = dict(httpx.QueryParams(request.content.decode()))
            if form.get("client_secret") != "secret":
                return httpx.Response(401, json={"title": "Unauthorized", "detail": "Invalid client"})
            return httpx.Response(200, json={"access_token": f"tok{self.token_calls}", "expires_in": 599})
        if not request.headers.get("Authorization", "").startswith("Bearer tok"):
            return httpx.Response(401, json={"title": "Unauthorized"})
        if path == "/products/v4/search/keyword":
            body = json.loads(request.content)
            products = [ldo_product(), obsolete_product()]
            exact = [p for p in products if p["ManufacturerProductNumber"] == body["Keywords"]]
            return httpx.Response(200, json={"Products": products, "ProductsCount": 2, "ExactMatches": exact})
        parts = request.url.raw_path.decode().split("?")[0].split("/")
        # /products/v4/search/{pn}/{action}
        if len(parts) == 6 and parts[1:4] == ["products", "v4", "search"]:
            pn, action = unquote(parts[4]), parts[5]
            if pn not in PRODUCTS:
                return httpx.Response(404, json={"title": "Not Found", "detail": f"Product {pn} not found"})
            if action == "productdetails":
                return httpx.Response(200, json={"Product": PRODUCTS[pn]()})
            if action == "substitutions":
                return httpx.Response(
                    200,
                    json={
                        "ProductSubstitutesCount": 1,
                        "ProductSubstitutes": [
                            {
                                "SubstituteType": "Similar",
                                "ProductUrl": "//www.digikey.com/p/2",
                                "Description": "IC REG LINEAR 3.3V 800MA SOT223",
                                "Manufacturer": {"Id": 1, "Name": "Diodes Incorporated"},
                                "ManufacturerProductNumber": "AZ1117CH-3.3TRG1",
                                "DigiKeyProductNumber": "AZ1117CH-3.3TRG1DICT-ND",
                                "QuantityAvailable": 52000,
                                "UnitPrice": 0.36,
                            }
                        ],
                    },
                )
        return httpx.Response(404, json={"title": "Not Found"})
