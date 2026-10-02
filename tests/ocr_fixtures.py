"""Synthetic test fixtures, generated in memory. No customer documents."""
from io import BytesIO

INVOICE_LINES = [
    "Invoice number: DEMO-001", "Supplier: Demo Services", "Customer: Example Client",
    "Issue date: 2026-10-01", "Due date: 2026-10-31", "Net amount: 100.00",
    "VAT rate: 20", "VAT amount: 20.00", "Total amount: 120.00", "Currency: EUR",
]


def make_pdf(lines=None, pages=1):
    """Small valid digital PDF using only the standard library."""
    lines = INVOICE_LINES if lines is None else lines
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    children = []
    for _ in range(pages):
        page_id, stream_id = len(objects) + 1, len(objects) + 2
        children.append(f"{page_id} 0 R")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>".encode())
        commands = ["BT /F1 15 Tf 50 790 Td 25 TL"]
        for line in lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.extend([f"({escaped}) Tj", "T*"])
        commands.append("ET")
        stream = "\n".join(commands).encode("cp1252")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(children)}] /Count {pages} >>".encode()
    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def make_image(lines=None, output_format="PNG", size=(1600, 1600)):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 38)
    except OSError:
        font = ImageFont.load_default(size=38)
    for index, line in enumerate(INVOICE_LINES if lines is None else lines):
        draw.text((60, 60 + index * 90), line, font=font, fill="black")
    buffer = BytesIO()
    image.save(buffer, format=output_format)
    return buffer.getvalue()


def make_scan_pdf():
    from PIL import Image
    image = Image.open(BytesIO(make_image()))
    buffer = BytesIO()
    image.save(buffer, "PDF", resolution=144)
    return buffer.getvalue()
