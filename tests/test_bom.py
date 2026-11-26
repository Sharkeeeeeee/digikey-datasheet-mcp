import pytest

from digikey_datasheet_mcp.bom import BomError, parse_bom


def test_kicad_style_csv():
    text = (
        '"Reference","Value","Footprint","Qty","MPN"\n'
        '"C1,C2,C3","100n","C_0402","3","GRM155R71C104KA88D"\n'
        '"R1","10k","R_0402","1","RC0402FR-0710KL"\n'
        '"J1","USB-C","","1","DNP"\n'
    )
    lines = parse_bom(text)
    assert [(line.part_number, line.quantity, line.reference) for line in lines] == [
        ("GRM155R71C104KA88D", 3, "C1,C2,C3"),
        ("RC0402FR-0710KL", 1, "R1"),
    ]


def test_tab_separated_with_bom_and_digikey_column():
    text = "\ufeffDesignator\tDigi-Key Part Number\tQuantity\nU1\t296-TPS7A9933DBVRCT-ND\t1,000\n"
    lines = parse_bom(text)
    assert lines[0].part_number == "296-TPS7A9933DBVRCT-ND"
    assert lines[0].quantity == 1000


def test_quantity_from_references_when_no_qty_column():
    lines = parse_bom("Reference;Manufacturer Part Number\nR1 R2 R5;RC0402FR-0710KL\n")
    assert lines[0].quantity == 3


def test_mpn_preferred_over_digikey_column():
    lines = parse_bom("DigiKey Part Number,MPN,Qty\nX-ND,ABC123,2\n")
    assert lines[0].part_number == "ABC123"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "empty"),
        ("MPN,Qty\n", "header row and at least one"),
        ("Value,Qty\n10k,1\n", "part number column"),
        ("MPN,Qty\nABC,lots\n", "not a whole number"),
        ("MPN,Qty\nDNP,1\n", "No part rows"),
    ],
)
def test_errors(text, message):
    with pytest.raises(BomError, match=message):
        parse_bom(text)
