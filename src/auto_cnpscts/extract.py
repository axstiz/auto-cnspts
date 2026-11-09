import base64
import json
import logging
from dataclasses import dataclass, field

from .client import image_part, text_part
from .pdf import PageImage

EXTRACT_SYSTEM = """Ты работаешь со слайдами учебной презентации (математика/физика и т.п.).
Задача — найти на слайдах задачи (упражнения) и аккуратно выписать их условия.
Правила:
- Каждая задача — отдельная запись. Объединяй слайды ТОЛЬКО если это одна и та же задача, продолжение её условия или решение задачи тянется на несколько слайдов. Отдельные разные задачи на соседних слайдах не объединяй — для них делай отдельные записи с соответствующим каждой слайдом.
- Задача продолжается на следующем слайде, если условие обрывается или там начинается её доказательство/решение — тогда относись к ней все её слайды.
- Если на слайде несколько независимых задач — выписывай каждую отдельно. Мини-упражнения серией (например «сколькими способами...» несколько подряд) можно сгруппировать в одну запись, если они объединены тематически и это явно серия упражнений из одной задачи — иначе отдельно.
- Чистую теорию, титульные слайды и определения задачами не считай.
- Условие переписывай человеческим языком, полностью, со всеми данными задачи.
- Вся математика — в LaTeX: inline $..., формулы выделенные $$...$$.
- Если на слайдах задачи есть её решение, отметь это и перепиши решение исходника как есть.
Формат ответа — только JSON без пояснений:
{"tasks": [{"pages": [номера слайдов], "statement": "условие", "has_solution": bool, "solution_text": "решение или пусто"}]}"""


@dataclass
class SlideTask:
    id: int
    pages: list[int]
    statement: str
    has_solution: bool
    solution_text: str


class ExtractionError(RuntimeError):
    pass


def parse_tasks_json(text: str) -> list[dict]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ExtractionError("модель не вернула JSON")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise ExtractionError(f"не удалось распарсить JSON: {e}")
    if not isinstance(data, dict) or "tasks" not in data or not isinstance(data["tasks"], list):
        raise ExtractionError("ожидается объект с ключом tasks")
    return data["tasks"]


def validate_task(raw: dict, base: int = 0) -> SlideTask | None:
    statement = str(raw.get("statement", "")).strip()
    if not statement:
        return None
    pages = [int(p) for p in raw.get("pages", []) if str(p).strip().lstrip("-").isdigit()]
    solution_text = str(raw.get("solution_text", "")).strip()
    has_raw = raw.get("has_solution")
    has_solution = bool(has_raw) if has_raw is not None else bool(solution_text)
    return SlideTask(
        id=base + 1,
        pages=pages or [1],
        statement=statement,
        has_solution=has_solution,
        solution_text=solution_text,
    )


def extract_tasks_batch(client, images: list[PageImage], attempts: int = 3) -> list[SlideTask]:
    content = [text_part(f"Слайды {images[0].number}–{images[-1].number}, пронумерованы ниже:")]
    for image in images:
        content.append(text_part(f"слайд {image.number}:"))
        content.append(image_part(base64.b64encode(image.png_bytes).decode()))

    last_err: Exception | None = None
    for _ in range(attempts):
        result = client.chat(content, system=EXTRACT_SYSTEM)
        try:
            raw_tasks = parse_tasks_json(result.text)
            break
        except ExtractionError as e:
            last_err = e
    else:
        raise last_err if last_err is not None else ExtractionError("не удалось получить JSON")

    out = []
    for idx, raw in enumerate(raw_tasks):
        t = validate_task(raw, base=idx)
        if t is not None:
            out.append(t)
    return out


def extract_tasks(client, images: list[PageImage], batch_size: int = 8, log: logging.Logger | None = None) -> list[SlideTask]:
    tasks: list[SlideTask] = []
    for i in range(0, len(images), batch_size):
        batch = images[i : i + batch_size]
        if log:
            log.info("extract: слайды %d–%d", batch[0].number, batch[-1].number)
        for t in extract_tasks_batch(client, batch):
            t.id = len(tasks) + 1
            tasks.append(t)
    return tasks
