import io
from dataclasses import dataclass

import pypdfium2 as pdfium

DEFAULT_ZOOM = 2.0


@dataclass
class PageImage:
    number: int
    png_bytes: bytes
    width: int
    height: int


def render_pages(pdf_path, zoom: float = DEFAULT_ZOOM) -> list[PageImage]:
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        pages = []
        for i in range(len(pdf)):
            page = pdf[i]
            pil = page.render(scale=zoom).to_pil()
            buf = io.BytesIO()
            pil.save(buf, "PNG")
            pages.append(PageImage(number=i + 1, png_bytes=buf.getvalue(), width=pil.width, height=pil.height))
        return pages
    finally:
        pdf.close()


def pick_title(pdf_path) -> str:
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        page = pdf[0]
        text = page.get_textpage().get_text_range()
        for line in text.splitlines():
            line = line.strip()
            if line:
                return line
        return ""
    finally:
        pdf.close()
