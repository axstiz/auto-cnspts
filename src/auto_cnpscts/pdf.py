from dataclasses import dataclass

import pymupdf

DEFAULT_ZOOM = 2.0


@dataclass
class PageImage:
    number: int
    png_bytes: bytes
    width: int
    height: int


def render_pages(pdf_path, zoom: float = DEFAULT_ZOOM) -> list[PageImage]:
    doc = pymupdf.open(str(pdf_path))
    try:
        pages = []
        mat = pymupdf.Matrix(zoom, zoom)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=mat)
            pages.append(
                PageImage(
                    number=i + 1,
                    png_bytes=pix.tobytes("png"),
                    width=pix.width,
                    height=pix.height,
                )
            )
        return pages
    finally:
        doc.close()


def pick_title(pdf_path) -> str:
    doc = pymupdf.open(str(pdf_path))
    try:
        for line in doc[0].get_text("text").splitlines():
            line = line.strip()
            if line:
                return line
        return ""
    finally:
        doc.close()
