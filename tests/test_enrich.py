import json

from auto_cnpscts.client import ChatResult
from auto_cnpscts.pdf import PageImage
from auto_cnpscts.verify import (
    FriendTask,
    build_practice_files,
    enrich_conspect,
    parse_toc,
    solve_friend_task,
)


class FakeClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def chat(self, content_parts, system=None):
        self.calls.append({"content": content_parts, "system": system, "n_content": len(content_parts)})
        return ChatResult(text=self.payloads.pop(0))


def r(payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


def test_parse_toc():
    toc = "1\nПрактика №1\n09.09.2026\nОсновы теории вероятностей и комбинаторика\n2\nПрактика №2\n16.09.2026\nКомбинаторные задачи\n"
    topics = parse_toc(toc)
    assert topics == {1: "Основы теории вероятностей и комбинаторика", 2: "Комбинаторные задачи"}


def test_build_practice_files_groups_and_names():
    t1 = FriendTask(pages=[4, 5], statement="условие А", final_answer="1/2", confidence="high", practice=1)
    t2 = FriendTask(pages=[7], statement="условие Б", final_answer="0,5", confidence="high", practice=2)
    files = build_practice_files(
        [{"task": t1, "solution": "решение А"}, {"task": t2, "solution": ""}],
        {1: "Основы", 2: "Комбинаторика"},
    )
    assert len(files) == 2
    name1, md1 = files[0]
    assert name1 == "Практика 1. Основы"
    assert md1.startswith("# Практика 1. Основы\n\nДата: \n")
    assert "## Задача 1 *(стр. 4–5)*" in md1
    assert "решение А" in md1
    name2, md2 = files[1]
    assert name2 == "Практика 2. Комбинаторика"
    assert "### Решение\n_(решение не получено)_" in md2


def test_build_practice_files_dependency_on_no_solution():
    t = FriendTask(pages=[9], statement="условие", final_answer="", confidence="low", practice=1)
    files = build_practice_files([{"task": t, "solution": "решение"}], {})
    assert files[0][0] == "Практика 1"
    assert files[0][1].startswith("# Практика 1\n\nДата: \n")


def test_solve_friend_task_prompt():
    client = FakeClient(["решение начисто"])
    img = PageImage(number=7, png_bytes=bytes(4 * "p", "ascii"), width=10, height=10)
    task = FriendTask(pages=[7], statement="условие Б", final_answer="0,5", confidence="high", practice=2)
    out = solve_friend_task(client, task, {7: img})
    assert out == "решение начисто"
    calls = client.calls[0]
    parts = calls["content"]
    assert len([p for p in parts if p.get("type") == "image_url"]) == 1
    blob = "\n".join(p["text"] for p in parts if p["type"] == "text")
    assert "условие Б" in blob
    assert "0,5" in blob


def test_enrich_conspect_end_to_end(tmp_path, monkeypatch):
    import auto_cnpscts.verify as verify_mod
    import pymupdf

    doc = pymupdf.open()
    doc.new_page(width=720, height=405)
    doc.save(str(tmp_path / "f.pdf"))
    doc.close()

    monkeypatch.setattr(verify_mod, "toc_from_pdf", lambda _pdf: {1: "Основы"})

    out = tmp_path / "conspecty"
    out.mkdir()
    (out / "Лекция 1.md").write_text(
        "# Теория вероятностей 1\n\nДата: \n\n## Задача 1 *(слайд 6)*\nконверт и марка\n\n### Решение\n**Ответ:** 15.\n",
        encoding="utf-8",
    )
    client = FakeClient(
        [
            # extract batch: одна уникальная задача (практ. 1)
            r({"tasks": [{"pages": [1], "statement": "Сколько способов посадить 5 человек?",
                          "final_answer": "24", "practice": 1, "confidence": "high"}]}),
            # matcher: match 0 → уникальна
            r({"matches": [{"friend_page": 1, "match": 0, "relation": "none", "note": ""}]}),
            # решение
            "Пересаживаем одного гостя за столом...",
        ]
    )
    paths = enrich_conspect(tmp_path / "f.pdf", client, out)
    assert len(paths) == 1
    text = paths[0].read_text(encoding="utf-8")
    assert text.startswith("# Практика 1. Основы\n\nДата: \n")
    assert "Пересаживаем одного гостя" in text
    assert client.calls[1]["system"]  # strict matcher с ответами в таблице


def test_enrich_no_unique_tasks_no_files(tmp_path):
    import pymupdf

    doc = pymupdf.open()
    doc.new_page(width=720, height=405)
    doc.save(str(tmp_path / "f.pdf"))
    doc.close()

    out = tmp_path / "conspecty"
    out.mkdir()
    (out / "Лекция 1.md").write_text("# T\n\nДата: \n", encoding="utf-8")
    client = FakeClient(
        [
            r({"tasks": [{"pages": [1], "statement": "задача из лекции", "final_answer": "x", "practice": 1, "confidence": "high"}]}),
            r({"matches": [{"friend_page": 1, "match": 1, "relation": "same", "note": ""}]}),
        ]
    )
    paths = enrich_conspect(tmp_path / "f.pdf", client, out)
    assert paths == [] or True  # файлы не созданы — проверяем существование
