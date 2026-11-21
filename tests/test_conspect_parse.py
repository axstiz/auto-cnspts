from pathlib import Path

import pytest

from auto_cnpscts.assemble import build_markdown
from auto_cnpscts.conspect_parse import OurTask, parse_conspect
from auto_cnpscts.extract import SlideTask


def md():
    tasks = [
        SlideTask(id=1, pages=[3], statement="Найдите $P(A|B)$.", has_solution=True,
                  solution_text="Считаем:\n$$x=1.$$\n\n**Ответ:** $P=1/3$."),
        SlideTask(id=2, pages=[7, 8], statement="Вторая задача без ответа.", has_solution=True,
                  solution_text="Решение и всё."),
        SlideTask(id=3, pages=[9], statement="Третья задача с блоком ответа.", has_solution=True,
                  solution_text="Итак\n$$y=2.$$\n\n**Ответ:**\n$$y = 2.$$\n\nЗаметим, что это просто."),
    ]
    return build_markdown("Демо", tasks)


def test_parse_ids_and_types():
    tasks = parse_conspect(md())
    assert [t.id for t in tasks] == [1, 2, 3]
    assert all(isinstance(t, OurTask) for t in tasks)


def test_parse_statements():
    tasks = parse_conspect(md())
    assert tasks[0].statement == "Найдите $P(A|B)$."
    assert tasks[1].statement == "Вторая задача без ответа."


def test_parse_inline_answer():
    tasks = parse_conspect(md())
    assert "$P=1/3$." in tasks[0].final_answer


def test_parse_block_answer_stops_before_comment():
    tasks = parse_conspect(md())
    assert "$$y = 2.$$" in tasks[2].final_answer
    assert "Заметим" not in tasks[2].final_answer


def test_parse_answer_absent_is_empty():
    tasks = parse_conspect(md())
    assert tasks[1].final_answer == ""


def test_parse_slides_note():
    tasks = parse_conspect(md())
    assert tasks[0].slides == "слайд 3"
    assert tasks[1].slides == "слайды 7–8"


def test_parse_ignores_header_and_date():
    text = md()
    tasks = parse_conspect(text)
    assert "# Демо" not in [s.statement for s in tasks]
    assert tasks[0].statement.startswith("Найдите")


def test_parse_real_conspect_file():
    p = Path("presentations/conspecty/Лекция 1. Основы теории вероятностей.md")
    if not p.exists():
        pytest.skip("конспект отсутствует")
    tasks = parse_conspect(p.read_text(encoding="utf-8"))
    assert len(tasks) >= 8
    assert all(t.statement for t in tasks)
