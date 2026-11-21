"""Минимальный генератор PDF для тестов: текст на страницах, без внешних зависимостей."""

import re

_PAGE_W, _PAGE_H = 720, 405


def _esc(text: str) -> str:
    return re.sub(r"([()\\])", r"\\\1", text)


def make_pdf(path, pages) -> None:
    """pages: список строк (текст страницы) или None/'' (пустая страница)."""
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids = []
    for text in pages:
        page_id = add(b"")  # placeholder
        stream_parts = [b"BT /F1 14 Tf"]
        y = _PAGE_H - 50
        if text:
            for line in text.splitlines() or [text]:
                stream_parts.append(f"50 {y} Td ({_esc(line)}) Tj".encode("cp1252", "replace"))
                y -= 24
        stream_parts.append(b"ET")
        stream = b" ".join(stream_parts)
        content_id = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        objects[page_id - 1] = (
            f"<< /Type /Page /Parent PARENT /MediaBox [0 0 {_PAGE_W} {_PAGE_H}] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode()
        kids.append(page_id)

    kids_ids = " ".join(f"{k} 0 R" for k in kids)
    pages_id = add(f"<< /Type /Pages /Kids [{kids_ids}] /Count {len(kids)} >>".encode())
    for k in kids:
        objects[k - 1] = objects[k - 1].replace(b"/Parent PARENT", f"/Parent {pages_id} 0 R".encode())
    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    with open(path, "wb") as f:
        f.write(bytes(out))
