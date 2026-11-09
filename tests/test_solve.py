import base64

from auto_cnpscts.client import ChatResult
from auto_cnpscts.extract import SlideTask
from auto_cnpscts.pdf import PageImage
from auto_cnpscts.solve import solve_task


class FakeClient:
    def __init__(self, text):
        self.calls = []
        self._text = text

    def chat(self, content_parts, system=None):
        self.calls.append((system, content_parts))
        return ChatResult(text=self._text)


def png(n):
    return PageImage(number=n, png_bytes=base64.b64encode(b"p" * 4), width=10, height=10)


def task(**kwargs):
    defaults = dict(id=1, pages=[2, 3], statement="Условие задачи", has_solution=True, solution_text="Старое решение")
    return SlideTask(**{**defaults, **kwargs})


def test_solve_task_builds_prompt_with_statement_and_old_solution():
    client = FakeClient("Готовое решение")
    out = solve_task(client, task(), {2: png(2), 3: png(3)})

    assert out == "Готовое решение"
    system, content = client.calls[0]
    assert system is not None
    texts = [p["text"] for p in content if p["type"] == "text"]
    blob = "\n".join(texts)
    assert "Условие задачи" in blob
    assert "Старое решение" in blob


def test_solve_task_attaches_only_task_images():
    client = FakeClient("x")
    solve_task(client, task(pages=[2]), {2: png(2), 3: png(3), 4: png(4)})

    _, content = client.calls[0]
    assert len([p for p in content if p["type"] == "image_url"]) == 1


def test_solve_task_trims_and_skips_empty():
    assert solve_task(FakeClient("  \n"), task(), {}) is None


def test_solve_task_without_solution_text():
    client = FakeClient("решение")
    solve_task(client, task(has_solution=False, solution_text=""), {2: png(2)})
    system, content = client.calls[0]
    blob = "\n".join(p["text"] for p in content if p["type"] == "text")
    assert "Старое решение" not in blob
