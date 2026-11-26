from fixtures import ldo_product, obsolete_product

from digikey_datasheet_mcp import normalize


def test_fix_url():
    assert normalize.fix_url("//mm.digikey.com/a.pdf") == "https://mm.digikey.com/a.pdf"
    assert normalize.fix_url("https://x/y.pdf") == "https://x/y.pdf"
    assert normalize.fix_url("") is None


def test_summary_is_compact():
    s = normalize.summarize(ldo_product())
    assert s["mpn"] == "TPS7A9933DBVR"
    assert s["manufacturer"] == "Texas Instruments"
    assert s["datasheet_url"] == "https://www.example-semi.com/lit/ds/tps7a99.pdf"
    assert s["category"].endswith("Low Drop Out (LDO) Regulators")
    assert s["key_parameters"]["Current - Output"] == "500mA"
    assert "Supplier Device Package" not in s["key_parameters"]  # "-" means no value
    assert "packaging_options" not in s


def test_full_summary():
    s = normalize.summarize(ldo_product(), full=True)
    assert s["rohs"] == "ROHS3 Compliant"
    assert s["series"] == "TPS7A99"
    assert len(s["packaging_options"]) == 3
    assert s["packaging_options"][0]["price_breaks"][1] == {"qty": 10, "unit_price": 0.98}
    assert "discontinued" in s  # False is kept, only empty values are dropped


def test_best_offer_small_quantity_uses_cut_tape():
    offer = normalize.best_offer(ldo_product(), 25)
    assert offer["best"]["packaging"] == "Cut Tape (CT)"
    assert offer["best"]["unit_price"] == 0.98
    assert offer["best"]["extended_price"] == 24.5
    assert offer["best"]["next_break"] == {"qty": 100, "unit_price": 0.71}
    # Reel needs 3000 and Digi-Reel has no standard pricing: neither is offered.
    assert offer["other_options"] == []


def test_best_offer_full_reel_is_cheaper():
    offer = normalize.best_offer(ldo_product(), 3000)
    assert offer["best"]["packaging"] == "Tape & Reel (TR)"
    assert offer["best"]["extended_price"] == 1260.0
    assert offer["other_options"][0]["packaging"] == "Cut Tape (CT)"


def test_best_offer_prefers_in_stock():
    product = ldo_product()
    product["ProductVariations"][0]["QuantityAvailableforPackageType"] = 5000
    product["ProductVariations"][1]["QuantityAvailableforPackageType"] = 0
    offer = normalize.best_offer(product, 3000)
    assert offer["best"]["packaging"] == "Cut Tape (CT)"  # pricier but available


def test_best_offer_out_of_stock_is_flagged():
    offer = normalize.best_offer(obsolete_product(), 5)
    assert offer["best"]["in_stock"] is False


def test_reels_are_sold_in_whole_reels_topped_up_with_cut_tape():
    product = ldo_product()
    product["ProductVariations"][0]["QuantityAvailableforPackageType"] = 5000
    offer = normalize.best_offer(product, 3500)
    best = offer["best"]
    # 1 reel at 0.42 + 500 cut tape at 0.71 beats 3500 on cut tape at 0.71.
    assert best["packaging"] == "1 x Tape & Reel (TR) + 500 on Cut Tape (CT)"
    assert best["extended_price"] == round(3000 * 0.42 + 500 * 0.71, 4)
    assert [line["quantity"] for line in best["lines"]] == [3000, 500]
    assert best["in_stock"] is True
    # A plain 3500-piece reel order is not offered: reels come in 3000s.
    assert all(o["packaging"] != "Tape & Reel (TR)" for o in offer["other_options"])


def test_two_full_reels():
    offer = normalize.best_offer(ldo_product(), 6000)
    assert offer["best"]["packaging"] == "Tape & Reel (TR)"
    assert offer["best"]["extended_price"] == 6000 * 0.42
