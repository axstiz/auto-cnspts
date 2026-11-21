import base64
import json
from dataclasses import dataclass

from .client import image_part, text_part
from .conspect_parse import OurTask, parse_conspect
from .pdf import PageImage


FRIEND_EXTRACT_SYSTEM = """Ты читаешь по фотографиям страниц рукописного конспекта практических занятий (математика) и выписываешь ЗАДАЧИ с их условиями.
Правила:
- Выписывай только постановки задач; решения и выкладки не пересказывай.
- Условие переписывай человеческим языком, полностью, со всеми числами. Вся математика — в LaTeX ($...$).
- Если виден финальный ответ задачи (обычно с пометкой «Ответ» или обведён) — впиши его в final_answer как есть; иначе "".
- Одна задача — одна запись даже если тянется на несколько страниц: указывай все её страницы.
- Если на странице виден заголовок «Практика №N» (или тема практики из оглавления) — проставь practice: N (число). Если не виден или не уверен — practice: 0.
- confidence: "high" — рукопись читается ясно; "medium" — часть слов угадал; "low" — сильно не уверен.
Верни только JSON без пояснений:
{"tasks": [{"pages": [номера страниц], "statement": "...", "final_answer": "...", "practice": N, "confidence": "high|medium|low"}]}"""


MATCH_SYSTEM_TMPL = """{our_list}

{purpose}
Критерии:
- "same" — одна и та же задача (совпадает по смыслу и числам).
- "variant" — та же задача, но с изменёнными числами.
- Если близких нет — match: 0, relation: "none". Сопоставляй осторожно.
Верни только JSON:
{{"matches": [{{"friend_page": номер первой страницы задачи рукописи, "match": id или 0, "relation": "same|variant|none", "note": "кратко"}}]}}"""


ANSWER_SYSTEM = """Ты проверяешь, совпадают ли ФИНАЛЬНЫЕ ответы двух решений одной и той же математической задачи.
- Сравнивай значения, а не способ записи: $\dfrac{7}{16}$ и $0{,}4375$ есть одно и то же.
- Если у одного ответ отсутствует или неоднозначен — verdict "unclear".
- Если значения объективно разные — "different".
Верни только JSON:
{"checks": [{"friend_page": N, "verdict": "ok|different|unclear", "note": "кратко"}]}"""


@dataclass
class FriendTask:
    pages: list[int]
    statement: str
    final_answer: str
    confidence: str
    practice: int = 0


def _images_content(images: list[PageImage]) -> list[dict]:
    content = [text_part(f"Страницы рукописного конспекта {images[0].number}–{images[-1].number}, пронумерованы ниже:")]
    for image in images:
        content.append(text_part(f"страница {image.number}:"))
        content.append(image_part(base64.b64encode(image.png_bytes).decode()))
    return content


def _json_payload(text: str, key: str) -> list:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("модель не вернула JSON")
    data = json.loads(text[start : end + 1])
    raw = data.get(key)
    return raw if isinstance(raw, list) else []


def extract_friend_batch(client, images: list[PageImage], attempts: int = 3) -> list[FriendTask]:
    content = _images_content(images)
    last_err: Exception | None = None
    raw_tasks = None
    for _ in range(attempts):
        result = client.chat(content, system=FRIEND_EXTRACT_SYSTEM)
        try:
            raw_tasks = _json_payload(result.text, "tasks")
            break
        except Exception as e:  # noqa: BLE001 — ошибки модели/JSON
            last_err = e
    if raw_tasks is None:
        raise RuntimeError(f"не удалось получить задачи из рукописи: {last_err}")

    out = []
    for raw in raw_tasks:
        statement = str(raw.get("statement", "")).strip()
        if not statement:
            continue
        pages = [int(p) for p in raw.get("pages", []) if str(p).strip().lstrip("-").isdigit()]
        out.append(
            FriendTask(
                pages=pages or [images[0].number],
                statement=statement,
                final_answer=str(raw.get("final_answer", "")).strip(),
                confidence=str(raw.get("confidence", "medium")).strip() or "medium",
                practice=_practice_from_raw(raw),
            )
        )
    return out


def _norm_statement(s: str) -> str:
    return " ".join(s.split())


def _practice_from_raw(raw: dict) -> int:
    try:
        val = int(str(raw.get("practice", 0)).strip().lstrip("№").strip())
        return val if val > 0 else 0
    except ValueError:
        return 0


def _dedup_friend_tasks(tasks: list[FriendTask]) -> list[FriendTask]:
    """Сливает записи с одинаковым условием (задачи у границ батчей)."""
    out: list[FriendTask] = []
    seen: dict[str, FriendTask] = {}
    for task in tasks:
        key = _norm_statement(task.statement)
        if key in seen:
            prev = seen[key]
            merged_pages = prev.pages + [p for p in task.pages if p not in prev.pages]
            prev.pages = sorted(merged_pages)
            if len(task.final_answer) > len(prev.final_answer):
                prev.final_answer = task.final_answer
            if not prev.practice and task.practice:
                prev.practice = task.practice
            continue
        seen[key] = task
        out.append(task)
    return out


def extract_friend(client, images: list[PageImage], batch_size: int = 6, log=None) -> list[FriendTask]:
    tasks: list[FriendTask] = []
    for i in range(0, len(images), batch_size):
        batch = images[i : i + batch_size]
        if log:
            log.info("friend: страницы %d–%d", batch[0].number, batch[-1].number)
        tasks.extend(extract_friend_batch(client, batch))
    before = len(tasks)
    tasks = _dedup_friend_tasks(tasks)
    if log and before != len(tasks):
        log.info("friend: слил %d дубликатов задач", before - len(tasks))
    return tasks


def _ours_table(ours: list[OurTask], with_answers: bool = False) -> str:
    lines = ["# Задачи из конспекта лекций (id, слайды, условие)"]
    for t in ours:
        answer = f" [ответ: {t.final_answer}]" if with_answers else ""
        lines.append(f"- id {t.id} ({t.slides}): {t.statement}{answer}")
    return "\n".join(lines)


MATCH_SOFT_RULES = (
    '- "same" — одна и та же задача (совпадает по смыслу и числам)\n'
    '- "variant" — та же задача, но с изменёнными числами'
)
MATCH_STRICT_RULES = (
    '- "same" — та же задача: совпадает условие по смыслу И совпадает финальный ответ (значение/число). Ответы различаются или у одного нет ответа — это НЕ same\n'
    '- "variant" — похожая задача, но считай её другой: изменены числа, часть условия или ответы не совпадают'
)


def _strict_purpose() -> str:
    return "Сверху приведён список задач конспекта лекций (id, слайды, условие, [ответ]). Ты сопоставляешь с ними задачи из рукописного конспекта студента (список ниже)."


def match_tasks(client, friend_tasks: list[FriendTask], ours: list[OurTask], batch_size: int = 12, log=None, strict: bool = False) -> list[dict]:
    rules = MATCH_STRICT_RULES if strict else MATCH_SOFT_RULES
    system = MATCH_SYSTEM_TMPL.format(
        our_list=_ours_table(ours, with_answers=strict),
        purpose=_strict_purpose() if strict else "Сверху приведён список задач конспекта лекций (id, слайды, условие). Ты сопоставляешь с ними задачи из рукописного конспекта студента (список ниже).",
        strict_rules=rules,
    )
    out: list[dict] = []
    for i in range(0, len(friend_tasks), batch_size):
        chunk = friend_tasks[i : i + batch_size]
        if log:
            log.info("match: задачи %d–%d", i + 1, i + len(chunk))
        content = [text_part("Задачи из рукописного конспекта студента:")]
        for j, task in enumerate(chunk, start=i):
            content.append(text_part(f"[{j}] страницы {task.pages}: {task.statement}"))
        result = client.chat(content, system=system)
        raw = _json_payload(result.text, "matches")
        for k, m in enumerate(raw):
            default_page = chunk[k].pages[0] if k < len(chunk) else 0
            relation = str(m.get("relation", "none"))
            out.append(
                {
                    "friend_page": int(m.get("friend_page", default_page) or default_page),
                    "match": int(m.get("match", 0) or 0),
                    "relation": relation if relation in ("same", "variant", "none") else "none",
                    "note": str(m.get("note", "")),
                }
            )
    return out


def check_answers(client, friend_tasks: list[FriendTask], matches: list[dict], ours: list[OurTask], log=None) -> list[dict]:
    candidates = []
    for m in matches:
        if not m["match"] or m.get("relation", "same") == "none":
            continue
        friend = next((t for t in friend_tasks if t.pages and t.pages[0] == m["friend_page"]), None)
        our = next((t for t in ours if t.id == m["match"]), None)
        if friend and our:
            candidates.append((friend, our, m))

    if not candidates:
        return []

    content = []
    for friend, our, m in candidates:
        content.append(
            text_part(
                f"[{m['friend_page']}] Условие: {friend.statement}\n"
                f"Ответ в рукописи: {friend.final_answer or '(не виден)'}\n"
                f"Ответ у нас: {our.final_answer or '(нет в конспекте)'}"
            )
        )

    result = client.chat(content, system=ANSWER_SYSTEM)
    raw = _json_payload(result.text, "checks")
    out = []
    for c in raw:
        verdict = c.get("verdict", "unclear")
        out.append(
            {
                "friend_page": int(c.get("friend_page", 0) or 0),
                "verdict": verdict if verdict in ("ok", "different", "unclear") else "unclear",
                "note": str(c.get("note", "")),
            }
        )
    return out


def build_report(
    friend_tasks: list[FriendTask],
    matches: list[dict],
    checks: list[dict],
    ours: list[OurTask],
    friend_title: str = "рукописный конспект",
) -> str:
    lines = [f"# Сверка с рукописным конспектом ({friend_title})", "", "Дата: "]

    matched = [m for m in matches if m["match"] and m["relation"] in ("same", "variant")]
    same = [m for m in matched if m["relation"] == "same"]
    variant = [m for m in matched if m["relation"] == "variant"]
    nomatch = [m for m in matches if m["relation"] == "none" or not m["match"]]
    covered = {m["match"] for m in matched}
    our_extra = [t for t in ours if t.id not in covered]

    lines += [
        "",
        "## Сводка",
        "",
        f"- задач в рукописи: {len(friend_tasks)}",
        f"- задач у нас: {len(ours)}",
        f"- совпало: same {len(same)}, variant {len(variant)}",
        f"- в рукописи без аналога: {len(nomatch)}",
        f"- у нас без аналога в рукописи: {len(our_extra)}",
    ]

    lines += ["", "## Задачи рукописи без аналога", ""]
    for m in nomatch:
        task = next((t for t in friend_tasks if t.pages and t.pages[0] == m["friend_page"]), None)
        if task is not None:
            lines.append(f"- стр. {task.pages[0]}: {task.statement}")

    lines += ["", "## Наши задачи без аналога в рукописи", ""]
    for t in our_extra:
        lines.append(f"- задача {t.id} ({t.slides}): {t.statement}")

    diff = [c for c in checks if c["verdict"] == "different"]
    if diff:
        lines += ["", "## Расхождения ответов", ""]
        for c in diff:
            friend = next((t for t in friend_tasks if t.pages and t.pages[0] == c["friend_page"]), None)
            if friend is not None:
                lines.append(f"- стр. {c['friend_page']}: ответ в рукописи `{friend.final_answer}` — {c['note']}")

    unclear_conf = [t for t in friend_tasks if t.confidence == "low"]
    if unclear_conf:
        lines += ["", "## Неясности распознавания", ""]
        for t in unclear_conf:
            lines.append(f"- стр. {t.pages[0]}: рукопись распознана неуверенно, стоит проверить глазами")

    return "\n".join(lines) + "\n"


def load_ours_from_dir(out_dir, log=None) -> list[OurTask]:
    """Читает все конспекты из out_dir, перенумеровывая id глобально."""
    from pathlib import Path

    tasks: list[OurTask] = []
    for md in sorted(Path(out_dir).glob("*.md")):
        if md.name.startswith("Сверка"):
            continue
        parsed = parse_conspect(md.read_text(encoding="utf-8"))
        if log and parsed:
            log.info("ours: %s — %d задач", md.name, len(parsed))
        tasks.extend(parsed)
    for n, t in enumerate(tasks):
        t.id = n + 1
    return tasks

def verify_conspect(friend_pdf, client, out_dir, batch_size: int = 6, log=None) -> "Path":
    from pathlib import Path
    from .pdf import render_pages

    info = (lambda msg, *a: log.info(msg, *a)) if log is not None else (lambda msg, *a: None)
    friend_pdf = Path(friend_pdf)
    out_dir = Path(out_dir)

    images = render_pages(friend_pdf)
    if not images:
        raise RuntimeError("в PDF рукописи нет страниц")
    ours = load_ours_from_dir(out_dir, log=log)
    if not ours:
        raise RuntimeError(f"в {out_dir} нет задач наших конспектов")

    friend_tasks = extract_friend(client, images, batch_size=batch_size, log=log)
    info("в рукописи найдено задач: %d", len(friend_tasks))

    matches = match_tasks(client, friend_tasks, ours, log=log)
    info("совпало: %d (same+variant)", sum(1 for m in matches if m["match"]))

    checks = check_answers(client, friend_tasks, matches, ours, log=log)
    info("проверено ответов: %d", len(checks))

    md = build_report(friend_tasks, matches, checks, ours, friend_title=friend_pdf.stem.split(" _")[0])
    path = out_dir / "Сверка с рукописным конспектом.md"
    path.write_text(md, encoding="utf-8")
    info("итог: %s", path)
    return path


FRIEND_SOLVE_SYSTEM = """Ты — автор решений для учебного практикума по математике (теория вероятностей).
Дана задача из рукописного конспекта студента и её страницы.
Правила:
- Язык — русский.
- Вся математика — в LaTeX: inline $..., выделенные формулы $$...$$.
- Если на страницах видно решение студента — перепиши его начисто и подробно, исправив арифметические опечатки и неточности записи (сам ход сохраняй).
- Если решение не видно или неполное — реши задачу полностью сам.
- Не описывай теорию саму по себе; только то, что нужно для решения.
- Не используй заголовки уровня 1 и 2 (# и ##); внутри решений можно только заголовки уровня 3 (### ...).
- Ответ — только текст решения в markdown, без обрамляющих пояснений и без ограждений ```."""


def solve_friend_task(client, task: FriendTask, images_by_number: dict[int, PageImage]) -> str | None:
    content = [text_part(f"# Задача (практика {task.practice or '?'}, стр. {task.pages})\n\n{task.statement}")]
    if task.final_answer:
        content.append(text_part(f"\nОтвет со страницы (проверь его корректность): {task.final_answer}"))
    content.append(text_part("\n## Страницы задачи:\n"))
    for n in task.pages:
        img = images_by_number.get(n)
        if img is not None:
            content.append(image_part(base64.b64encode(img.png_bytes).decode()))
    result = client.chat(content, system=FRIEND_SOLVE_SYSTEM)
    text = result.text.strip()
    return text or None


def parse_toc(text: str) -> dict[int, str]:
    """Оглавление вида «Практика №1 / дата / тема» -> {1: тема, ...}.

    Дата и тема могут быть на одной строке с номером или на следующих
    строках (порядок строк зависит от текстового слоя).
    """
    import re

    topics: dict[int, str] = {}
    date_or_number = re.compile(r"(\d{2}\.\d{2}\.\d{4}|\d+)")
    for m in re.finditer(r"Практика\s*№\s*(\d+)", text):
        n = int(m.group(1))
        if n in topics:
            continue
        for line in re.split(r"[\r\n]+", text[m.end() :]):
            line = line.strip()
            if not line or date_or_number.fullmatch(line):
                continue
            topics[n] = line
            break
    return topics


def toc_from_pdf(pdf_path) -> dict[int, str]:
    """
    Темы практик из текстового слоя страницы оглавления (обычно стр. 2).
    Ищем страницу с наибольшим числом распарсенных тем среди первых четырёх.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        best: dict[int, str] = {}
        for i in range(min(4, len(pdf))):
            text = pdf[i].get_textpage().get_text_range()
            parsed = parse_toc(text)
            if len(parsed) > len(best):
                best = parsed
        return best
    finally:
        pdf.close()


def _compress_ranges(pages: list[int]) -> str:
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
    parts = [str(a) if a == b else f"{a}–{b}" for a, b in ranges]
    return ", ".join(parts)


def pages_note(pages: list[int]) -> str:
    if not pages:
        return ""
    joined = _compress_ranges(sorted(set(pages)))
    return f"стр. {joined}" if len(set(pages)) == 1 else f"стр. {joined}"


def _infer_practice_in_place(tasks: list[FriendTask]) -> None:
    last = 0
    for task in sorted(tasks, key=lambda t: t.pages[0] if t.pages else 0):
        if task.practice:
            last = task.practice
        else:
            task.practice = last


def build_practice_files(entries: list[dict], topics: dict[int, str]) -> list[tuple[str, str]]:
    """entries: {"task": FriendTask, "solution": str}. Возвращает [(имя_файла, markdown)]."""
    from collections import defaultdict

    from .assemble import PLACEHOLDER, clean_solution

    groups: dict[int, list[dict]] = defaultdict(list)
    for e in entries:
        groups[e["task"].practice or 0].append(e)
    out = []
    for practice in sorted(groups):
        topic = topics.get(practice, "")
        title = f"# Практика {practice}" + (f". {topic}" if topic else "")
        lines = [title, "", "Дата: "]
        for n, e in enumerate(groups[practice], start=1):
            task: FriendTask = e["task"]
            note = pages_note(task.pages)
            heading = f"## Задача {n}" + (f" *({note})*" if note else "")
            lines += ["", heading, task.statement.strip(), "", "### Решение"]
            lines += [clean_solution(e["solution"]) or PLACEHOLDER]
        md = "\n".join(lines) + "\n"
        name = sanitize_name(f"Практика {practice}. {topic}" if topic else f"Практика {practice}")
        out.append((name, md))
    return out


def sanitize_name(name: str) -> str:
    from .assemble import sanitize_filename

    return sanitize_filename(name)


def enrich_conspect(friend_pdf, client, out_dir, batch_size: int = 6, log=None) -> list["Path"]:
    from pathlib import Path
    from .pdf import render_pages

    info = (lambda msg, *a: log.info(msg, *a)) if log is not None else (lambda msg, *a: None)
    friend_pdf = Path(friend_pdf)
    out_dir = Path(out_dir)

    images = render_pages(friend_pdf)
    if not images:
        raise RuntimeError("в PDF рукописи нет страниц")
    images_by_number = {img.number: img for img in images}

    topics = toc_from_pdf(friend_pdf)
    if topics:
        info("темы практик: %s", ", ".join(f"№{n} {t}" for n, t in sorted(topics.items())))

    friend_tasks = extract_friend(client, images, batch_size=batch_size, log=log)
    _infer_practice_in_place(friend_tasks)
    info("в рукописи найдено задач: %d", len(friend_tasks))

    ours = load_ours_from_dir(out_dir, log=log)
    matches = match_tasks(client, friend_tasks, ours, log=log, strict=True)
    by_page: dict[int, FriendTask] = {}
    for task in friend_tasks:
        by_page.setdefault(task.pages[0], task)
    seen_ids = set()
    unique = []
    for m in matches:
        if m["match"] and m["relation"] == "same":
            continue
        task = by_page.get(m["friend_page"])
        if task is None or id(task) in seen_ids:
            continue
        seen_ids.add(id(task))
        unique.append(task)
    info("уникальных задач друга (нет в лекциях): %d", len(unique))

    paths: list[Path] = []
    entries = []
    for task in unique:
        info("решаю задачу друга (практ. %s, стр. %s)", task.practice, task.pages)
        solution = solve_friend_task(client, task, images_by_number) or ""
        entries.append({"task": task, "solution": solution})

    files = build_practice_files(entries, topics)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, md in files:
        path = out_dir / f"{name}.md"
        path.write_text(md, encoding="utf-8")
        info("итог: %s", path)
        paths.append(path)
    if not paths:
        info("уникальных задач нет — файлы практик не создавались")
    return paths
