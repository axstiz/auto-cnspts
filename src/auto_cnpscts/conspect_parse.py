import re
from dataclasses import dataclass

_TASK_HEADING = re.compile(r"^## Задача\s+(\d+)(?:\s+\*\((.*?)\)\*)?\s*$")
_ANSWER_MARKER = re.compile(r"\*\*Ответ[.:]?\*\*")
_MAX_ANSWER_LEN = 400


@dataclass
class OurTask:
    id: int
    slides: str
    statement: str
    solution: str
    final_answer: str


def _clean(seq: list[str]) -> str:
    while seq and not seq[0].strip():
        seq.pop(0)
    while seq and not seq[-1].strip():
        seq.pop()
    return "\n".join(seq)


def _extract_answer(solution: str) -> str:
    m = _ANSWER_MARKER.search(solution)
    if not m:
        return ""
    tail = solution[m.end() :].strip()
    body = tail.split("\n\n", 1)[0]
    body = body.strip() or tail[:_MAX_ANSWER_LEN]
    return body


def parse_conspect(text: str) -> list[OurTask]:
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if _TASK_HEADING.match(line)]
    tasks: list[OurTask] = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = lines[start:end]
        m = _TASK_HEADING.match(block[0])
        assert m is not None
        task_id = int(m.group(1))
        slides = (m.group(2) or "").strip()
        try:
            sol_idx = block.index("### Решение")
        except ValueError:
            sol_idx = None
        statement = _clean(block[1:sol_idx] if sol_idx is not None else block[1:])
        solution = _clean(block[sol_idx + 1 :]) if sol_idx is not None else ""
        tasks.append(
            OurTask(
                id=task_id,
                slides=slides,
                statement=statement,
                solution=solution,
                final_answer=_extract_answer(solution),
            )
        )
    return tasks
