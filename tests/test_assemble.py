from auto_cnpscts.assemble import build_markdown, clean_solution, format_pages, sanitize_filename
from auto_cnpscts.extract import SlideTask


def t(i, statement="условие", solution="решение", pages=None):
    return SlideTask(id=i, pages=pages or [i], statement=statement, has_solution=bool(solution), solution_text=solution)


def test_build_markdown_header_and_date():
    md = build_markdown("Кратные интегралы", [])
    assert md.startswith("# Кратные интегралы\n\nДата: \n")


def test_build_markdown_task_sections():
    md = build_markdown("T", [t(1, "условие 1", "решение 1", pages=[4])])
    target = "# T\n\nДата: \n\n## Задача 1 *(слайд 4)*\nусловие 1\n\n### Решение\nрешение 1\n"
    assert md == target


def test_format_pages_collapses_ranges():
    assert format_pages([5]) == "слайд 5"
    assert format_pages([2, 3, 4]) == "слайды 2–4"
    assert format_pages([2, 3, 5, 6, 9]) == "слайды 2–3, 5–6, 9"
    assert format_pages([]) == ""
    assert format_pages([12, 13]) == "слайды 12–13"


def test_build_markdown_multiple_tasks():
    md = build_markdown("T", [t(1, "a", "b"), t(2, "c", "d")])
    assert "## Задача 2 *" in md
    assert md.index("a") < md.index("b") < md.index("c") < md.index("d")


def test_build_markdown_missing_solution_placeholder():
    md = build_markdown("T", [t(1, "у", solution="")])
    assert "### Решение\n_(решение не получено)_\n" in md


def test_clean_solution_strips_leading_headings():
    raw = "## Решение\n\nтело решения\n"
    assert clean_solution(raw) == "тело решения"


def test_clean_solution_strips_fancy_leading_header():
    raw = "# Решение. Парадокс Бертрана\n\nтело\n"
    assert clean_solution(raw) == "тело"


def test_clean_solution_demotes_low_headings():
    raw = "тело\n\n# Подзаголовок\n\n## Способ 2: разбор\n\nдальше\n\n### уже глубоко\n"
    out = clean_solution(raw)
    assert "### Подзаголовок" in out
    assert "### Способ 2: разбор" in out
    assert "### уже глубоко" in out
    assert "\n# " not in out and "\n## " not in out
    assert not out.startswith("#")


def test_build_markdown_duplicate_solution_header_removed():
    md = build_markdown("T", [t(1, "у", "## Решение\n\nтекст")])
    assert md.count("### Решение") == 1
    assert "текст" in md


def test_sanitize_filename_replaces_invalid_chars():
    assert sanitize_filename('Название: "ф"/x') == "Название ф x"


def test_sanitize_filename_collapses_ws_and_dots():
    assert sanitize_filename("  a\nb   c..  ") == "a b c"


def test_sanitize_filename_empty_fallback():
    assert sanitize_filename("   ") == "конспект"


def test_sanitize_filename_truncates():
    long = "x" * 200
    assert len(sanitize_filename(long)) == 100
