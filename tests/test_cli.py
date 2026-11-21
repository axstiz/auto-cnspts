import logging
import json

import pytest

from pdfgen import make_pdf

import auto_cnpscts.cli as cli
from auto_cnpscts.client import ChatResult


class RecordingClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []
        self.closed = False
        self.usage = {"requests": len(payloads), "prompt_tokens": 0, "completion_tokens": 0}

    def chat(self, content_parts, system=None):
        self.calls.append({"system": system, "content": content_parts})
        return ChatResult(text=self.payloads.pop(0))

    def close(self):
        self.closed = True



@pytest.fixture
def pdf(tmp_path):
    p = tmp_path / "deck.pdf"
    make_pdf(str(p), ["Deck title", "Problem one"])
    return p


@pytest.fixture
def patched(monkeypatch):
    holder = {}

    def fake_client(api_key=None, **kwargs):
        holder["kwargs"] = {"api_key": api_key, **kwargs}
        holder["client"] = RecordingClient(
            [
                json.dumps({"tasks": [{"pages": [2], "statement": "условие"}]}),
                "решение",
            ]
        )
        return holder["client"]

    monkeypatch.setattr(cli, "GoClient", fake_client)
    monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
    return holder


def capture_out(capsys):
    err = capsys.readouterr()
    return err.err, err.out


def test_main_runs_pipeline_and_prints_path(patched, pdf, tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="auto-cnpscts"):
        rc = cli.main([str(pdf)])
    assert rc == 0
    assert (tmp_path / "conspecty" / "deck.md").exists()
    assert patched["kwargs"]["api_key"] == "test-key"
    assert "model" not in patched["kwargs"]  # модель по умолчанию задаёт GoClient
    assert patched["client"].closed
    assert "готово" in caplog.text
    assert "conspecty/deck.md" in caplog.text


def test_main_custom_out_and_model(patched, pdf, tmp_path):
    rc = cli.main([str(pdf), "--out", str(tmp_path / "docs"), "--model", "glm-5.2"])
    assert rc == 0
    assert (tmp_path / "docs" / "deck.md").exists()
    assert patched["kwargs"]["model"] == "glm-5.2"


def test_main_missing_key(patched, pdf, monkeypatch, caplog, tmp_path):
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.setattr(cli, "ENV_CANDIDATES", (tmp_path / "_нет_env_",))
    patched["client"] = None
    with caplog.at_level(logging.ERROR, logger="auto-cnpscts"):
        rc = cli.main([str(pdf)])
    assert rc == 2
    assert "OPENCODE_API_KEY" in caplog.text


def test_main_missing_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "GoClient", lambda *a, **k: pytest.fail("не должен создаваться"))
    monkeypatch.setenv("OPENCODE_API_KEY", "k")
    rc = cli.main([str(tmp_path / "nope.pdf")])
    assert rc == 2


def test_load_env_file(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n# комментарий\nOPENCODE_API_KEY = key-from-env\n\nQUOTED='v v'\nDUP=ignored\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    monkeypatch.setenv("DUP", "preset")
    cli.load_env_file(env_file)

    import os

    assert os.environ["OPENCODE_API_KEY"] == "key-from-env"
    assert os.environ["QUOTED"] == "v v"
    assert os.environ["DUP"] == "preset"


def test_batch_mode_runs_only_missing(patched, tmp_path, caplog, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_run(pdf, client, out_dir, batch_size=8, log=None):
        calls.append(pdf.name)
        return out_dir / f"{pdf.stem}.md"

    monkeypatch.setattr(cli, "run", fake_run)

    src = tmp_path / "presentations"
    src.mkdir()
    make_pdf(str(src / "b.pdf"), ["Deck B"])
    make_pdf(str(src / "a.pdf"), ["Deck A"])

    out = src / "conspecty"
    out.mkdir()
    (out / "a.md").write_text("# Deck A\n", encoding="utf-8")

    with caplog.at_level(logging.INFO, logger="auto-cnpscts"):
        rc = cli.main([])
    assert rc == 0
    assert calls == ["b.pdf"]
    assert "пропущен (конспект уже есть): a.pdf" in caplog.text


def test_batch_mode_all_done(patched, tmp_path, caplog, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_run(pdf, client, out_dir, batch_size=8, log=None):
        calls.append(pdf.name)
        return out_dir

    monkeypatch.setattr(cli, "run", fake_run)

    src = tmp_path / "presentations"
    src.mkdir()
    make_pdf(str(src / "b.pdf"), ["Deck B"])

    out = src / "conspecty"
    out.mkdir()
    (out / "b.md").write_text("# Deck B\n", encoding="utf-8")

    with caplog.at_level(logging.INFO, logger="auto-cnpscts"):
        rc = cli.main([])
    assert rc == 0
    assert calls == []
    assert "уже есть" in caplog.text


def test_batch_mode_missing_dir(patched, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["--dir", "_нет_такой_папки_"])
    assert rc == 2
