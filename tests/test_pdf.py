from pdfgen import make_pdf

from auto_cnpscts.pdf import pick_title, render_pages


def test_render_pages_counts_and_order(tmp_path):
    p = tmp_path / "deck.pdf"
    make_pdf(str(p), ["Hello deck", "Theory page", "Problem one"])
    images = render_pages(p)
    assert len(images) == 3
    assert [img.number for img in images] == [1, 2, 3]
    for img in images:
        assert img.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert img.width > 0 and img.height > 0


def test_page1_text(tmp_path):
    p = tmp_path / "deck.pdf"
    make_pdf(str(p), ["Hello deck", "Theory page", "Problem one"])
    assert pick_title(p) == "Hello deck"


def test_pick_title_skips_empty_lines(tmp_path):
    p = tmp_path / "t.pdf"
    make_pdf(str(p), ["\n\nThe title"])
    assert pick_title(p) == "The title"


def test_pick_title_empty_when_no_text(tmp_path):
    p = tmp_path / "t.pdf"
    make_pdf(str(p), [""])
    assert pick_title(p) == ""


def test_render_scale_affects_size(tmp_path):
    p = tmp_path / "deck.pdf"
    make_pdf(str(p), ["Hello deck"])
    small = render_pages(p, zoom=1.0)
    big = render_pages(p, zoom=3.0)
    assert big[0].width > small[0].width
