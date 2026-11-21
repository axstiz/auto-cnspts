from pathlib import Path

from .assemble import build_markdown, sanitize_filename
from .client import GoClient, image_part, text_part
from .extract import extract_tasks
from .pdf import PageImage, pick_title, render_pages
from .solve import solve_task

TITLE_SYSTEM = "Определи по слайду назывной заголовок презентации на русском языке. Ответь только заголовком, без кавычек и пояснений."


def title_from_image(client: GoClient, image: PageImage) -> str:
    result = client.chat(
        [text_part("Титульный слайд презентации:"), image_part(image_b64(image))],
        system=TITLE_SYSTEM,
    )
    return result.text.strip()


def image_b64(image: PageImage) -> str:
    import base64

    return base64.b64encode(image.png_bytes).decode()


def existing_connspect(out_dir: Path, pdf_path: Path) -> Path | None:
    """Конспект называется по имени PDF."""
    path = out_dir / f"{sanitize_filename(pdf_path.stem)}.md"
    return path if path.exists() else None


def find_missing(source_dir: Path, out_dir: Path) -> list[Path]:
    """PDF-презентации, для которых в out_dir ещё нет конспекта."""
    pdfs = sorted(p for p in source_dir.glob("*.pdf") if p.is_file())
    return [p for p in pdfs if existing_connspect(out_dir, p) is None]


def run(
    pdf_path: Path,
    client,
    out_dir: Path,
    batch_size: int = 8,
    log=None,
) -> Path:
    info = (lambda msg, *a: log.info(msg, *a)) if log is not None else (lambda msg, *a: None)
    images = render_pages(pdf_path)
    if not images:
        raise RuntimeError("в PDF нет страниц")

    title = pick_title(pdf_path)
    if not title:
        info("текст на 1-м слайде не найден, распознаю заголовок по картинке")
        title = title_from_image(client, images[0])
    info("заголовок: %s", title)

    tasks = extract_tasks(client, images, batch_size=batch_size, log=log)
    info("найдено задач: %d", len(tasks))

    images_by_number = {img.number: img for img in images}
    for t in tasks:
        info("решаю задачу %d (слайды %s)", t.id, t.pages)
        t.solution_text = (solve_task(client, t, images_by_number) or "").strip()

    md = build_markdown(title, tasks)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{sanitize_filename(pdf_path.stem)}.md"
    path.write_text(md, encoding="utf-8")
    info("итог: %s", path)
    return path


THEORY_SYSTEM = """Ты составляешь теоретическую часть учебного конспекта по математике из слайдов презентации.
Правила:
- Выписывай ТОЛЬКО теорию: определения, теоремы, свойства, ключевые формулы, замечания и пояснения к ним.
- Задачи, упражнения, примеры с числовыми данными и их решения — полностью исключай; слайд целиком про задачу — пропускай.
- Если к задаче прилагаются общие пояснения/разбор модели (маргинальные вероятности, условная независимость и т.п.) — включай их как теорию, но без упоминания номера задачи: заголовки вида «Задача N» не используй, называй по теме.
- Сохраняй порядок слайдов; для каждой темы — заголовок уровня 3 (### Название темы).
- Вся математика — в LaTeX: inline $..., выделенные формулы $$...$$.
- Не выдумывай теорию, которой нет на слайдах.
- Ответ — только markdown без обрамляющих пояснений и без ограждений ```."""


def theory_filename(pdf_stem: str) -> str:
    from .assemble import sanitize_filename

    if pdf_stem.startswith("Лекция "):
        name = "Теория " + pdf_stem[len("Лекция ") :]
    elif pdf_stem.startswith("Лекция"):
        name = "Теория " + pdf_stem[len("Лекция") :]
    else:
        name = f"Теория — {pdf_stem}"
    return sanitize_filename(name)


def run_theory(
    pdf_path: Path,
    client,
    out_dir: Path,
    batch_size: int = 8,
    log=None,
) -> Path | None:
    """Извлекает теорию из презентации; возвращает None, если файл уже есть."""
    from .assemble import clean_theory

    info = (lambda msg, *a: log.info(msg, *a)) if log is not None else (lambda msg, *a: None)
    images = render_pages(pdf_path)
    if not images:
        raise RuntimeError("в PDF нет страниц")

    title = pick_title(pdf_path)
    if not title:
        info("текст на 1-м слайде не найден, распознаю заголовок по картинке")
        title = title_from_image(client, images[0])
    info("заголовок: %s", title)

    parts: list[str] = []
    for i in range(0, len(images), batch_size):
        batch = images[i : i + batch_size]
        info("theory: слайды %d–%d", batch[0].number, batch[-1].number)
        content = [text_part(f"Слайды {batch[0].number}–{batch[-1].number}, пронумерованы ниже:")]
        for image in batch:
            content.append(text_part(f"слайд {image.number}:"))
            content.append(image_part(image_b64(image)))
        result = client.chat(content, system=THEORY_SYSTEM)
        text = result.text.strip()
        if text:
            parts.append(clean_theory(text))
    if not parts:
        info("теории на слайдах не нашлось")
        parts = ["_(теория не извлечена)_"]

    md = f"# {title}\n\nДата: \n\n" + "\n\n".join(parts) + "\n"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{theory_filename(pdf_path.stem)}.md"
    path.write_text(md, encoding="utf-8")
    info("итог: %s", path)
    return path
