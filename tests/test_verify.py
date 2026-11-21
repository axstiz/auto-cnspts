import json

import pytest

from auto_cnpscts.client import ChatResult
from auto_cnpscts.conspect_parse import OurTask
from auto_cnpscts.pdf import PageImage
from auto_cnpscts.verify import (
    FriendTask,
    build_report,
    check_answers,
    extract_friend,
    extract_friend_batch,
    match_tasks,
)


class FakeClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def chat(self, content_parts, system=None):
        self.calls.append({"content": content_parts, "system": system, "n_content": len(content_parts)})
        return ChatResult(text=self.payloads.pop(0))


def r(payloads) -> str:
    return json.dumps(payloads, ensure_ascii=False)


def img(n: int) -> PageImage:
    return PageImage(number=n, png_bytes=bytes(4 * "p", "ascii"), width=10, height=10)


def ours() -> list[OurTask]:
    return [
        OurTask(id=1, slides="слайд 3", statement="Встреча с 12 до 13, ждут 15 мин. Вероятность встречи?",
                solution="", final_answer="$P=7/16$"),
        OurTask(id=2, slides="слайды 10–11", statement="Пять писем и пять конвертов. Ни одно письмо не в своём конверте.",
                solution="", final_answer=""),
    ]


def friend_json():
    return r({"tasks": [
        {"pages": [4], "statement": "Двое договорились встретиться с 12 до 13, каждый ждёт 15 минут. Вероятность встречи?",
         "final_answer": "7/16", "confidence": "high"},
        {"pages": [7], "statement": "Задача про Байеса с монетами", "final_answer": "", "confidence": "low"},
    ]})


def test_extract_friend_batch_parses():
    client = FakeClient([friend_json()])
    tasks = extract_friend_batch(client, [img(4), img(7)])

    assert [t.pages for t in tasks] == [[4], [7]]
    assert tasks[0].final_answer == "7/16"
    assert tasks[1].confidence == "low"
    assert client.calls[0]["system"]  # рукописный промпт задан


def test_extract_friend_syncs_page_offset():
    client = FakeClient([friend_json()])
    tasks = extract_friend(client, [img(i) for i in range(1, 8)], batch_size=7)
    assert len(tasks) == 2
    assert tasks[0].pages[0] == 4


def test_match_tasks_returns_matches():
    client = FakeClient([r({"matches": [
        {"friend_page": 4, "match": 1, "relation": "same", "note": "та же задача"},
        {"friend_page": 7, "match": 0, "relation": "none", "note": "нет похожей"},
    ]})])
    friend_tasks = [FriendTask(pages=[4], statement="Встреча...", final_answer="7/16", confidence="high"),
                    FriendTask(pages=[7], statement="Байес", final_answer="", confidence="low")]
    matches = match_tasks(client, friend_tasks, ours())

    assert matches[0]["match"] == 1
    assert matches[1]["match"] == 0
    assert client.calls[0]["n_content"] == 3  # заголовок + обе задачи друга в одном запросе


def test_check_answers_verdicts():
    client = FakeClient([r({"checks": [
        {"friend_page": 4, "verdict": "ok", "note": "совпадают"},
    ]})])
    friend_tasks = [FriendTask(pages=[4], statement="...", final_answer="7/16", confidence="high")]
    checks = check_answers(client, friend_tasks, matches=[{"friend_page": 4, "match": 1}], ours=ours())

    assert checks[0]["verdict"] == "ok"


def test_check_answers_only_for_matched():
    client = FakeClient([r({"checks": [{"friend_page": 4, "verdict": "ok", "note": ""}]})])
    friend_tasks = [
        FriendTask(pages=[4], statement="A", final_answer="7/16", confidence="high"),
        FriendTask(pages=[8], statement="unmatched", final_answer="", confidence="low"),
    ]
    check_answers(client, friend_tasks, matches=[{"friend_page": 4, "match": 1}, {"friend_page": 8, "match": 0}], ours=ours())
    assert len(client.calls) == 1  # unmatched не отправляли


def test_build_report_structure():
    friend_tasks = [
        FriendTask(pages=[4], statement="Встреча...", final_answer="7/16", confidence="high"),
        FriendTask(pages=[7], statement="Байес", final_answer="", confidence="low"),
    ]
    matches = [
        {"friend_page": 4, "match": 1, "relation": "same", "note": ""},
        {"friend_page": 7, "match": 0, "relation": "none", "note": "точно нет"},
    ]
    checks = [{"friend_page": 4, "verdict": "ok", "note": ""}]
    md = build_report(friend_tasks, matches, checks, ours(), friend_title="рукописный конспект, практики")

    assert md.startswith("# Сверка с рукописным конспектом")
    assert "## Задачи рукописи без аналога" in md
    assert "Байес" in md
    assert "## Наши задачи без аналога" in md
    assert "## Расхождения ответов" not in md  # расхождений нет
    assert "Неясности распознавания" in md     # low confidence отражён


def test_extract_friend_dedupes_across_batches():
    payload = r({"tasks": [{"pages": [7], "statement": "Одна и та же задача", "final_answer": "", "confidence": "high"}]})
    same = r({"tasks": [{"pages": [6], "statement": "Одна и та же задача ", "final_answer": "x", "confidence": "high"}]})
    client = FakeClient([payload, same])
    tasks = extract_friend(client, [img(i) for i in range(1, 8)], batch_size=6)
    assert len(tasks) == 1
    assert tasks[0].pages == [6, 7]
    assert tasks[0].final_answer == "x"


def test_match_tasks_splited_in_batches():
    payloads = [r({"matches": [{"friend_page": n, "match": n, "relation": "same", "note": ""}]}) for n in (1, 4, 7)]
    client = FakeClient(payloads)
    friend_tasks = [FriendTask(pages=[n], statement=f"задача {n}", final_answer="", confidence="high") for n in range(1, 9)]
    matches = match_tasks(client, friend_tasks, ours(), batch_size=3)
    assert len(client.calls) == 3
    assert len(matches) == 3
