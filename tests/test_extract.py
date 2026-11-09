import base64
import json

import pytest

from auto_cnpscts.client import ChatResult
from auto_cnpscts.extract import (
    ExtractionError,
    SlideTask,
    extract_tasks,
    extract_tasks_batch,
    parse_tasks_json,
    validate_task,
)
from auto_cnpscts.pdf import PageImage


class FakeClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def chat(self, content_parts, system=None):
        self.calls.append({"content": content_parts, "system": system})
        return ChatResult(text=self.payloads.pop(0))


def r(payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


def img(n: int) -> PageImage:
    return PageImage(number=n, png_bytes=base64.b64encode(b"p" * 4), width=10, height=10)


def ok(raw) -> SlideTask:
    t = validate_task(raw, base=0)
    assert t is not None
    return t


def test_parse_valid_json():
    data = parse_tasks_json(r({"tasks": [{"pages": [2], "statement": "условие"}]}))
    assert data[0]["statement"] == "условие"


def test_parse_strips_code_fence():
    raw = "```json\n" + r({"tasks": [{"pages": [2]}]}) + "\n```"
    assert parse_tasks_json(raw)[0]["pages"] == [2]


def test_parse_strips_surrounding_text():
    raw = "Вот задачи: " + r({"tasks": [{"pages": [1]}]})
    assert parse_tasks_json(raw)[0]["pages"] == [1]


def test_parse_invalid_json_raises():
    with pytest.raises(ExtractionError):
        parse_tasks_json("Извините, не смог найти задачи")


def test_parse_no_tasks_key_raises():
    with pytest.raises(ExtractionError):
        parse_tasks_json(r({"foo": []}))


def test_validate_task_normalizes_fields():
    raw = {"pages": ["3", 4], "statement": "  условие  ", "has_solution": "true", "solution_text": "$x$"}
    t = ok(raw)
    assert t.id == 1
    assert t.pages == [3, 4]
    assert t.statement == "условие"
    assert t.has_solution is True
    assert t.solution_text == "$x$"


def test_validate_solution_text_implies_has_solution():
    t = ok({"pages": [1], "statement": "s", "solution_text": "решение есть"})
    assert t.has_solution is True


def test_validate_task_skips_empty_statement():
    assert validate_task({"pages": [1], "statement": ""}, base=0) is None
    assert validate_task({}, base=0) is None


def test_batch_sends_numbered_images_and_parses():
    client = FakeClient([r({"tasks": [{"pages": [2], "statement": "s1"}, {"pages": [3], "statement": "s2"}]})])
    tasks = extract_tasks_batch(client, [img(2), img(3)])

    call = client.calls[0]
    assert call["system"]  # системный промпт задан
    parts = call["content"]
    assert [p.get("type") for p in parts].count("image_url") == 2

    assert [t.id for t in tasks] == [1, 2]
    assert [t.statement for t in tasks] == ["s1", "s2"]


def test_extract_tasks_renumbers_across_batches():
    client = FakeClient(
        [
            r({"tasks": [{"pages": [1], "statement": "a"}]}),
            r({"tasks": [{"pages": [9], "statement": "b"}]}),
        ]
    )
    images = [img(i) for i in range(1, 10)]

    tasks = extract_tasks(client, images, batch_size=5)

    assert len(client.calls) == 2
    assert [t.id for t in tasks] == [1, 2]
    assert tasks[0].statement == "a"
    assert tasks[1].statement == "b"


def test_extract_tasks_skips_theory_only_batches():
    client = FakeClient([r({"tasks": []}), r({"tasks": []})])
    tasks = extract_tasks(client, [img(i) for i in range(1, 4)], batch_size=2)
    assert tasks == []


def test_extract_batch_retries_on_broken_json():
    bad = r({"tasks": [{"pages": [1], "statement": "усеч"}]})[:-2]
    good = r({"tasks": [{"pages": [1], "statement": "полная"}]})
    client = FakeClient([bad, good])
    tasks = extract_tasks_batch(client, [img(1)])
    assert [t.statement for t in tasks] == ["полная"]
    assert len(client.calls) == 2


def test_extract_batch_fails_after_all_retries():
    client = FakeClient(["мяу", "мяу", "мяу"])
    with pytest.raises(ExtractionError):
        extract_tasks_batch(client, [img(1)])
    assert len(client.calls) == 3
