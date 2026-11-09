import pymupdf
import pytest

from auto_cnpscts.pdf import pick_title, render_pages


def make_pdf(path, pages):
    doc = pymupdf.open()
    for i, text in enumerate(pages):
        page = doc.new_page(width=720, height=405)
        if text:
            page.insert_text((50, 50), text, fontsize=18)
    doc.save(path)
    doc.close()


@pytest.fixture
def pdf(tmp_path):
    p = tmp_path / "slide_deck.pdf"
    make_pdf(str(p), ["Multiple integrals", "Theory: definition", "Problem 1"])
    return p


def test_render_pages_counts_and_order(pdf):
    images = render_pages(pdf)
    assert len(images) == 3
    assert [img.number for img in images] == [1, 2, 3]
    for img in images:
        assert img.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert img.width > 0 and img.height > 0


def test_page1_text(pdf):
    assert pick_title(pdf) == "Multiple integrals"


def test_pick_title_skips_empty_lines(tmp_path):
    p = tmp_path / "t.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=720, height=405)
    page.insert_text((50, 50), "\n\n", fontsize=18)
    page.insert_text((50, 80), "The title", fontsize=18)
    doc.save(str(p))
    doc.close()
    assert pick_title(p) == "The title"


def test_pick_title_empty_when_no_text(tmp_path):
    p = tmp_path / "t.pdf"
    make_pdf(str(p), [""])
    assert pick_title(p) == ""


def test_render_scale_affects_size(pdf):
    small = render_pages(pdf, zoom=1.0)
    big = render_pages(pdf, zoom=3.0)
    assert big[0].width > small[0].width
