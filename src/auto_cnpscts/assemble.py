import re

from .extract import SlideTask

MAX_NAME_LEN = 100
PLACEHOLDER = "_(решение не получено)_"



def build_markdown(title: str, tasks: list[SlideTask]) -> str:
    lines = [f"# {title}", "", "Дата: "]
    for t in tasks:
        note = format_pages(t.pages)
        heading = f"## Задача {t.id}" + (f" *({note})*" if note else "")
        lines += ["", heading, t.statement.strip(), "", "### Решение"]
        lines += [clean_solution(t.solution_text) or PLACEHOLDER]
    return "\n".join(lines) + "\n"


def format_pages(pages: list[int]) -> str:
    """Схлопывает подряд идущие номера: [2,3,4,9] -> «2–4, 9»."""
    if not pages:
        return ""
    ranges: list[tuple[int, int]] = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
        else:
            ranges.append((start, prev))
            start = prev = p
    ranges.append((start, prev))
    parts = [f"{a}" if a == b else f"{a}–{b}" for a, b in ranges]
    note = ", ".join(parts)
    if len(pages) == 1:
        return f"слайд {note}"
    return f"слайды {note}"


_HEADING = re.compile(r"^(?P<h>#+)\s*(?P<text>[^#].*)$")


def clean_solution(text: str) -> str:
    lines = text.strip().splitlines()
    while lines and (not lines[0].strip() or _HEADING.match(lines[0].strip())):
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    out_lines = []
    for line in lines:
        m = _HEADING.match(line.strip())
        if m and m.group("text").strip():
            out_lines.append("### " + m.group("text").strip())
        else:
            out_lines.append(line)
    return "\n".join(out_lines).strip()


def clean_theory(text: str) -> str:
    """Понижает заголовки #/## до ### (### и глубже не трогает), чистит края."""
    lines = text.strip().splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    out_lines = []
    for line in lines:
        m = _HEADING.match(line.strip())
        if m and len(m.group("h")) <= 2 and m.group("text").strip():
            out_lines.append("### " + m.group("text").strip())
        else:
            out_lines.append(line)
    return "\n".join(out_lines).strip()


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", name)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip().rstrip(". ")
    if not cleaned:
        cleaned = "конспект"
    return cleaned[:MAX_NAME_LEN]
