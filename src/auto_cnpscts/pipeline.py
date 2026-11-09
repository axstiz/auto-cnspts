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
