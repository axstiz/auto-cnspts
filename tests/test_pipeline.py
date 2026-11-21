import json
import pytest

from pdfgen import make_pdf

from auto_cnpscts.client import ChatResult
from auto_cnpscts.pipeline import run


class FakeClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def chat(self, content_parts, system=None):
        self.calls.append({"system": system, "content": content_parts})
        return ChatResult(text=self.payloads.pop(0))



@pytest.fixture
def pdf(tmp_path):
    p = tmp_path / "deck.pdf"
    make_pdf(str(p), ["Deck title", "Theory page", "Problem one"])
    return p


def test_run_end_to_end_writes_markdown(pdf, tmp_path):
    client = FakeClient(
        [
            json.dumps({"tasks": [{"pages": [3], "statement": "Найдите $x$", "has_solution": False}]}, ensure_ascii=False),
            "$x = 42$",
        ]
    )
    out = tmp_path / "conspecty"
    path = run(pdf, client, out)

    assert path.exists()
    assert path.name == "deck.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Deck title\n\nДата: \n")
    assert "## Задача 1" in text
    assert "$x = 42$" in text
    assert len(client.calls) == 2


def test_run_falls_back_to_title_from_first_slide(tmp_path):
    p = tmp_path / "no_text.pdf"
    make_pdf(str(p), ["", "Task"])

    client = FakeClient(
        [
            "Распознанный заголовок",
            json.dumps({"tasks": [{"pages": [2], "statement": "условие"}]}),
            "решение",
        ]
    )
    out = tmp_path / "conspecty"
    path = run(p, client, out)

    assert path.name == "no_text.md"
    assert client.calls[0]["system"] is not None


def test_run_theory_only_pdf(tmp_path):
    p = tmp_path / "theory.pdf"
    make_pdf(str(p), ["Only theory"])

    client = FakeClient([json.dumps({"tasks": []})])
    path = run(p, client, tmp_path / "conspecty")

    text = path.read_text(encoding="utf-8")
    assert text == "# Only theory\n\nДата: \n"


def test_run_no_pages_raises(tmp_path, monkeypatch):
    import auto_cnpscts.pipeline as pl

    p = tmp_path / "empty.pdf"
    make_pdf(str(p), ["x"])
    monkeypatch.setattr(pl, "render_pages", lambda *a, **k: [])
    with pytest.raises(RuntimeError):
        run(p, FakeClient([]), tmp_path / "conspecty")


def test_find_missing_skips_existing_by_stem(tmp_path):
    from auto_cnpscts.pipeline import find_missing

    src = tmp_path / "presentations"
    src.mkdir()
    make_pdf(str(src / "Лекция 1.pdf"), ["Deck Title"])
    make_pdf(str(src / "Лекция 2.pdf"), ["Other deck"])

    out = src / "conspecty"
    out.mkdir()
    (out / "Лекция 1.md").write_text("# Deck Title\n", encoding="utf-8")

    missing = find_missing(src, out)
    assert [p.name for p in missing] == ["Лекция 2.pdf"]


def test_find_missing_skips_by_pdf_stem_when_no_text(tmp_path):
    from auto_cnpscts.pipeline import find_missing

    src = tmp_path / "presentations"
    src.mkdir()
    make_pdf(str(src / "Лекция 9.pdf"), [""])  # текст на 1-м слайде пуст

    out = src / "conspecty"
    out.mkdir()
    (out / "Лекция 9.md").write_text("# x\n", encoding="utf-8")

    assert find_missing(src, out) == []


def test_find_missing_sorted_and_full_dir(tmp_path):
    from auto_cnpscts.pipeline import find_missing

    src = tmp_path / "presentations"
    src.mkdir()
    make_pdf(str(src / "b.pdf"), ["B"])
    make_pdf(str(src / "a.pdf"), ["A"])
    make_pdf(str(src / "notes.txt"), ["x"])

    missing = find_missing(src, src / "conspecty")
    assert [p.name for p in missing] == ["a.pdf", "b.pdf"]
