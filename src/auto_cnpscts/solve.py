import base64

from .client import image_part, text_part
from .extract import SlideTask
from .pdf import PageImage

SOLVE_SYSTEM = """Ты — автор решений для учебного конспекта по математике/физике.
Дана задача и её слайды. Напиши ПОЛНОЕ аккуратное решение.
Правила:
- Язык — русский.
- Вся математика — в LaTeX: inline $..., выделенные формулы $$...$$.
- Решай по шагам, с пояснениями, доводи до ответа.
- Если оставлено исходное решение со слайда — перепиши его начисто и подробно, исправив неточности и опечатки.
- Не описывай теорию саму по себе; только то, что нужно для решения.
- Не начинай ответ с заголовка и не используй заголовки уровня 1 и 2 (# и ##). Внутри решения можно только заголовки уровня 3 (### ...).
- Ответ — только текст решения в markdown, без обрамляющих пояснений и без ограждений ```."""


def solve_task(client, task: SlideTask, images_by_number: dict[int, PageImage]) -> str | None:
    content = [text_part(f"# Задача {task.id}\n\n{task.statement}")]
    if task.solution_text:
        content.append(text_part("\n## Исходное решение со слайдов (перепиши начисто)\n\n" + task.solution_text))
    content.append(text_part("\n## Слайды задачи:\n"))
    for n in task.pages:
        img = images_by_number.get(n)
        if img is not None:
            content.append(image_part(base64.b64encode(img.png_bytes).decode()))
    result = client.chat(content, system=SOLVE_SYSTEM)
    text = result.text.strip()
    return text or None
