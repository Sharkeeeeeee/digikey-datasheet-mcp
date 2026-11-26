"""Build small text PDFs for tests, so no binary fixtures live in the repo."""

from __future__ import annotations

import io

from pypdf import PdfReader, PdfWriter


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[list[str]], bookmarks: list[tuple[str, int]] | None = None, title: str | None = None) -> bytes:
    objects: list[bytes] = []
    n_pages = len(pages)
    page_ids = [4 + 2 * i for i in range(n_pages)]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, lines in enumerate(pages):
        content_id = page_ids[i] + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        ops = ["BT", "/F1 10 Tf", "12 TL", "40 760 Td"]
        for line in lines:
            ops.append(f"({_escape(line)}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    data = out.getvalue()
    if not bookmarks and not title:
        return data
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    for name, page_index in bookmarks or []:
        writer.add_outline_item(title=name, page_number=page_index)
    if title:
        writer.add_metadata({"/Title": title})
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


LDO_PAGES = [
    [
        "TPS7A99 500-mA Low-Noise LDO Regulator",
        "1 Features",
        "Input voltage range: 2.5 V to 6.5 V",
        "Ultra-low noise: 6 uVrms",
    ],
    [
        "Table of Contents",
        "1 Features ............................................. 1",
        "5 Pin Configuration and Functions ...................... 3",
        "6.1 Absolute Maximum Ratings ........................... 4",
        "6.3 Recommended Operating Conditions ................... 4",
        "6.5 Electrical Characteristics ......................... 5",
        "9 Package Information .................................. 6",
    ],
    [
        "5 Pin Configuration and Functions",
        "PIN NAME I/O DESCRIPTION",
        "1 IN I Input supply voltage",
        "2 GND - Ground",
        "3 EN I Enable input. Drive high to turn on the regulator",
        "4 NR/SS - Noise reduction and soft-start capacitor",
        "5 OUT O Regulated output voltage",
        "See Absolute Maximum Ratings for the limits on EN.",
    ],
    [
        "6 Specifications",
        "6.1 Absolute Maximum Ratings",
        "Voltage IN -0.3 7.0 V",
        "Voltage EN -0.3 7.0 V",
        "Junction temperature -40 150 C",
        "6.3 Recommended Operating Conditions",
        "VIN Input voltage 2.5 6.5 V",
    ],
    [
        "6.5 Electrical Characteristics",
        "IQ Quiescent current IOUT = 0 mA 250 400 uA",
        "VDO Dropout voltage IOUT = 500 mA 180 300 mV",
        "PSRR Power-supply rejection ratio f = 1 kHz 70 dB",
    ],
    [
        "9 Package Information",
        "DBV (SOT-23-5) package outline",
    ],
]
