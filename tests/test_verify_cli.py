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
        self.usage = {"requests": len(payloads), "prompt_tokens": 0, "completion_tokens": 0}

    def chat(self, content_parts, system=None):
        self.calls.append({"system": system, "content": content_parts})
        return ChatResult(text=self.payloads.pop(0))

    def close(self):
        pass



@pytest.fixture
def patched(monkeypatch, tmp_path):
    holder = {}

    def fake_client(api_key=None, **kwargs):
        holder["kwargs"] = {"api_key": api_key, **kwargs}
        holder["client"] = RecordingClient(
            [
                json.dumps({"tasks": [
                    {"pages": [1], "statement": "Двое договорились встретиться", "final_answer": "7/16", "confidence": "high"},
                    {"pages": [2], "statement": "Задача про монеты и Байеса", "final_answer": "1/4", "confidence": "medium"},
                ]}),
                json.dumps({"matches": [
                    {"friend_page": 1, "match": 1, "relation": "same", "note": ""},
                    {"friend_page": 2, "match": 0, "relation": "none", "note": ""},
                ]}),
                json.dumps({"checks": [
                    {"friend_page": 1, "verdict": "ok", "note": "совпадают"},
                ]}),
            ]
        )
        return holder["client"]

    monkeypatch.setattr(cli, "GoClient", fake_client)
    monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
    monkeypatch.chdir(tmp_path)
    return holder


def fixture_setup(tmp_path):
    make_pdf(str(tmp_path / "friend.pdf"), ["скан 1", "скан 2"])
    out = tmp_path / "presentations" / "conspecty"
    out.mkdir(parents=True)
    (out / "Лекция 1.md").write_text(
        "# Теория вероятностей 1\n\nДата: \n\n## Задача 1 *(слайд 3)*\nДвое договорились встретиться с 12 до 13\n\n### Решение\n... **Ответ:** $7/16$.\n",
        encoding="utf-8",
    )
    return out


def test_verify_writes_report(patched, tmp_path, caplog):
    out = fixture_setup(tmp_path)
    with caplog.at_level(logging.INFO, logger="auto-cnpscts"):
        rc = cli.main(["verify", "friend.pdf", "--out", str(out)])
    assert rc == 0
    report = out / "Сверка с рукописным конспектом.md"
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "задач в рукописи: 2" in text
    assert "задач у нас: 1" in text
    assert "Задача про монеты" in text
    assert "### Решение" not in text  # отчёт использует заголовки своего формата


def test_verify_report_skips_ours_on_next_load(patched, tmp_path):
    out = fixture_setup(tmp_path)
    rc = cli.main(["verify", "friend.pdf", "--out", str(out)])
    assert rc == 0
    from auto_cnpscts.verify import load_ours_from_dir

    tasks = load_ours_from_dir(out)
    assert len(tasks) == 1  # файл «Сверка...» не возвращается как источник задач


def test_verify_no_key(monkeypatch, tmp_path, patched):
    make_pdf(str(tmp_path / "friend.pdf"), ["x"])
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.setattr(cli, "ENV_CANDIDATES", (tmp_path / "_нет_env_",))
    rc = cli.main(["verify", "friend.pdf", "--out", str(tmp_path / "presentations" / "conspecty")])
    assert rc == 2
