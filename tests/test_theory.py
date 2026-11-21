import logging

import pytest

from pdfgen import make_pdf

import auto_cnpscts.cli as cli
from auto_cnpscts.client import ChatResult
from auto_cnpscts.pipeline import run_theory, theory_filename


class FakeClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []
        self.usage = {"requests": len(payloads), "prompt_tokens": 0, "completion_tokens": 0}

    def chat(self, content_parts, system=None):
        self.calls.append({"system": system, "content": content_parts})
        return ChatResult(text=self.payloads.pop(0))

    def close(self):
        pass



def test_theory_filename_renames_lekciya():
    assert theory_filename("Лекция 3. Дискретные случайные величины") == "Теория 3. Дискретные случайные величины"
    assert theory_filename("Лекция 1. Основы теории вероятностей") == "Теория 1. Основы теории вероятностей"
    assert theory_filename("deck 5") == "Теория — deck 5"


def test_run_theory_writes_and_demotes_headings(tmp_path):
    p = tmp_path / "Лекция 1. Основы.pdf"
    make_pdf(str(p), ["Theory deck", "definition slide", "theorem slide"])

    client = FakeClient(
        [
            "# Введение\n\nОпределение вероятности.",
            "## Теорема Байеса\n\n$$P(A|B) = \\frac{P(B|A)P(A)}{P(B)}$$\n\n### следствие",
        ]
    )
    path = run_theory(p, client, tmp_path / "conspecty", batch_size=2)

    assert path.name == "Теория 1. Основы.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Theory deck\n\nДата: \n\n")
    assert "### Введение" in text      # # понижен
    assert "### Теорема Байеса" in text  # ## понижен
    assert "### следствие" in text     # ### не тронут
    assert "$$P(A|B)" in text


def test_theory_cli_batch_and_skip(tmp_path, monkeypatch, caplog):
    holder = {}

    def fake_client(api_key=None, **kwargs):
        holder["client"] = FakeClient(["### Определение\n\nТеорема."])
        return holder["client"]

    monkeypatch.setattr(cli, "GoClient", fake_client)
    monkeypatch.setenv("OPENCODE_API_KEY", "k")
    monkeypatch.chdir(tmp_path)

    src = tmp_path / "presentations"
    src.mkdir()
    make_pdf(str(src / "Лекция 1. Основы.pdf"), ["Theory deck", "slide2"])

    with caplog.at_level(logging.INFO, logger="auto-cnpscts"):
        rc = cli.main(["theory"])
    assert rc == 0
    text = (src / "conspecty" / "Теория 1. Основы.md").read_text(encoding="utf-8")
    assert text.startswith("# Theory deck\n\nДата: \n")
    assert "### Определение" in text

    # повторный запуск: пропуск без запросов
    holder["client"] = FakeClient(["не должно вызываться"])
    with caplog.at_level(logging.INFO, logger="auto-cnpscts"):
        rc = cli.main(["theory"])
    assert rc == 0
    assert holder["client"].calls == []
    assert "пропущен" in caplog.text


def test_theory_cli_force_regenerates(tmp_path, monkeypatch):
    holder = {}

    def fake_client(api_key=None, **kwargs):
        holder["n"] = holder.get("n", 0) + 1
        holder["client"] = FakeClient([f"часть {holder['n']}"])
        return holder["client"]

    monkeypatch.setattr(cli, "GoClient", fake_client)
    monkeypatch.setenv("OPENCODE_API_KEY", "k")
    monkeypatch.chdir(tmp_path)

    src = tmp_path / "presentations"
    src.mkdir()
    make_pdf(str(src / "Лекция 1. Основы.pdf"), ["Theory deck", "s2", "s3"])
    assert cli.main(["theory"]) == 0
    assert cli.main(["theory", "--force"]) == 0
    text = (src / "conspecty" / "Теория 1. Основы.md").read_text(encoding="utf-8")
    assert "часть 2" in text  # перегенерировано вторым вызовом
