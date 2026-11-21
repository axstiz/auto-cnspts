# auto-cnpscts

Пайплайн учебных конспектов из презентаций (PDF) через мультимодальную LLM
(по умолчанию `glm-5.3-flash` через [OpenCode Go](https://opencode.ai/console)):

- **конспекты задач** — модель извлекает задачи со слайдов (и переписывает
  начисто готовые решения), оформляет всё в LaTeX; чистая теория исключается;
- **теория** — наоборот: определения/теоремы/формулы без задач;
- **сверка с конспектом друга** (рукописный PDF-скан): матчинг задач и
  финальных ответов;
- **задачи практик** — задачи из рукописи, которых нет на слайдах.

## Установка

```fish
git clone https://github.com/axstiz/auto-cnspts.git
cd auto-cnspts
uv sync
printf 'OPENCODE_API_KEY=ключ\n' > .env   # ключ OpenCode Go; .env в git-игноре
```

Требования: Python 3.12+, `uv`. Ключ берётся из `.env`
(`OPENCODE_API_KEY`, опционально `OPENCODE_MODEL`) или из окружения.

## Команды

Все команды на NixOS запускаются так (см. раздел NixOS ниже):

```fish
set LIB (nix-build '<nixpkgs>' -A stdenv.cc.cc.lib --no-out-link)
env LD_LIBRARY_PATH=$LIB/lib uv run auto-cnpscts …
```

### Конспекты задач

```fish
uv run auto-cnpscts презентация.pdf   # одна презентация
uv run auto-cnpscts                   # пакетно: все *.pdf из presentations/ без конспекта
uv run auto-cnpscts --force           # пакетно и перегенерировать всё
```

Результат: `presentations/conspecty/<имя PDF>.md`. Заголовок внутри md —
название с 1-го слайда (если текст не извлекается — модель распознаёт его
по картинке); поле даты оставлено пустым.

```markdown
# Название презентации

Дата: 

## Задача 1 *(слайд 3)*
Условие

### Решение
Решение с LaTeX ($x^2$)
```

Заголовки 1–2 уровня из ответов модели автоматически срезаются/понижаются
до `###`, чтобы структура файла не ломалась.

### Теория

```fish
uv run auto-cnpscts theory            # все презентации → Теория N. Тема.md
uv run auto-cnpscts theory --force    # перегенерировать
```

Выдаёт `presentations/conspecty/Теория N. Тема.md`: только определения,
теоремы, свойства, формулы; задачи и решения исключены. Готовые файлы
пропускаются при повторном запуске.

### Сверка с конспектом друга

```fish
uv run auto-cnpscts verify "конспект друга/....pdf"
```

Извлекает задачи из рукописи (GLM по сканам), сопоставляет с нашими
конспектами, сверяет финальные ответы и пишет отчёт
`presentations/conspecty/Сверка с конспектом друга.md`: сводка,
задачи друга без аналога, наши без аналога, расхождения ответов,
неясности распознавания.

### Задачи практик (то, чего нет на слайдах)

```fish
uv run auto-cnpscts enrich "конспект друга/....pdf"
```

Жёсткий критерий покрытия (совпадать должны и условие, и ответ): всё, что
не совпало с лекциями, решается/переписывается начисто по рукописи и
выкладывается в `Практика N. Тема.md` (темы берутся из оглавления
рукописи). Формат: `## Задача N *(стр. X–Y)*` → `### Решение`.

## Общие опции

```text
--dir DIR         папка презентаций (по умолчанию presentations/)
--out DIR         папка вывода (по умолчанию conspecty/ рядом с презентациями)
--force           перегенерировать даже существующие файлы
--model NAME      модель (по умолчанию glm-5.3-flash; можно OPENCODE_MODEL в .env)
--batch-size N    слайдов/страниц на запрос (по умолчанию 8; verify/enrich — 6)
-v                детальные логи
```

## Структура проекта

```text
src/auto_cnpscts/
  pdf.py             # PDF → PNG слайды, титул с 1-го слайда
  client.py          # OpenCode Go: auth, User-Agent, x-opencode-session, ретраи
  extract.py         # задачи со слайдов (батчи, JSON, дедуп по границам батчей)
  solve.py           # решения/переписывание задач
  assemble.py        # сборка md: заголовок, «Дата: », чистка заголовков
  pipeline.py        # оркестрация: batch + theory
  conspect_parse.py  # разбор сгенерированных конспектов (для сверки)
  verify.py          # verify/enrich: задачи друга, матчинг, отчёты, файлы практик
  cli.py             # CLI: batch | verify | enrich | theory
tests/               # pytest, все запросы к API замоканы
```

## NixOS: libstdc++

PyMuPDF линкует `libstdc++.so.6`, которого нет в системе:

```fish
set LIB (nix-build '<nixpkgs>' -A stdenv.cc.cc.lib --no-out-link)
env LD_LIBRARY_PATH=$LIB/lib uv run pytest -q
env LD_LIBRARY_PATH=$LIB/lib uv run auto-cnpscts …
```

## Тесты

```fish
env LD_LIBRARY_PATH=$LIB/lib uv run pytest -q   # 86 тестов
```

Все запросы к API в тестах замоканы; реальный API дёргается только при
ручном прогоне.
