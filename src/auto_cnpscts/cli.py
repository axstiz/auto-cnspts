import argparse
import logging
import os
import sys
from pathlib import Path

from .client import GoClient
from .pipeline import find_missing, run

logger = logging.getLogger("auto-cnpscts")

DEFAULT_SOURCE_DIR = Path("presentations")
ENV_CANDIDATES = (Path(".env"), Path(__file__).resolve().parents[2] / ".env")


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="auto-cnpscts",
        description="Конспекты из презентаций: задачи и решения через GLM",
    )
    parser.add_argument("pdf", nargs="?", type=Path, help="путь к одной презентации (PDF); без него — пакетный режим по папке --dir")
    parser.add_argument("--dir", type=Path, default=DEFAULT_SOURCE_DIR, help="папка с презентациями для пакетного режима (по умолчанию presentations/)")
    parser.add_argument("--out", type=Path, default=None, help="папка вывода (по умолчанию conspecty/ рядом с презентациями)")
    parser.add_argument("--model", default=None, help="модель (по умолчанию glm-5.3-flash)")
    parser.add_argument("--batch-size", type=int, default=8, help="слайдов на запрос извлечения")
    parser.add_argument("--force", action="store_true", help="в пакетном режиме перегенерировать даже существующие конспекты")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    for candidate in ENV_CANDIDATES:
        load_env_file(candidate)

    api_key = os.environ.get("OPENCODE_API_KEY", "").strip()
    if not api_key:
        logger.error("не задан OPENCODE_API_KEY (заполни .env в корне проекта или экспортируй переменную)")
        return 2

    try:
        if args.pdf is not None:
            targets = [args.pdf]
            out_dir = args.out or (args.pdf.parent / "conspecty")
            missing = [p for p in targets if not p.exists()]
            if missing:
                logger.error("файл не найден: %s", missing[0])
                return 2
        else:
            source_dir = args.dir
            if not source_dir.is_dir():
                logger.error("папка с презентациями не найдена: %s", source_dir)
                return 2
            out_dir = args.out or (source_dir / "conspecty")
            if args.force:
                targets = sorted(p for p in source_dir.glob("*.pdf") if p.is_file())
                logger.info("режим --force: перегенерирую все %d презентаций", len(targets))
            else:
                targets = find_missing(source_dir, out_dir)
                for p in sorted(p for p in source_dir.glob("*.pdf")):
                    if p not in targets:
                        logger.info("пропущен (конспект уже есть): %s", p.name)
            if not targets:
                logger.info("все конспекты уже есть — делать нечего")
                return 0
            logger.info("нужно сделать конспекты: %d — %s", len(targets), ", ".join(p.name for p in targets))

        client_kwargs = {}
        model = args.model or os.environ.get("OPENCODE_MODEL", "").strip() or None
        if model:
            client_kwargs["model"] = model
        client = GoClient(api_key=api_key, **client_kwargs)
    except Exception as e:  # noqa: BLE001
        logger.error("ошибка: %s", e)
        return 1

    try:
        failed = []
        for pdf in targets:
            if not pdf.exists():
                logger.error("файл не найден: %s", pdf)
                failed.append(pdf.name)
                continue
            try:
                path = run(pdf, client, out_dir, batch_size=args.batch_size, log=logger)
            except Exception as e:  # noqa: BLE001 — пользовательская диагностика
                logger.error("ошибка на %s: %s", pdf.name, e)
                logger.debug("stack:", exc_info=True)
                failed.append(pdf.name)
                continue
            logger.info("готово: %s", path)

        u = client.usage
        logger.info(
            "запросов: %d, токенов: %d вход / %d выход",
            u["requests"],
            u["prompt_tokens"],
            u["completion_tokens"],
        )
        if failed:
            logger.error("не удалось: %s", ", ".join(failed))
            return 1
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
