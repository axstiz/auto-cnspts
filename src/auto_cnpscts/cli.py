import argparse
import logging
import os
import sys
from pathlib import Path

from .client import GoClient
from .pipeline import find_missing, run, run_theory
from .verify import enrich_conspect, verify_conspect

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
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == "verify":
        return verify_main(argv[1:])
    if argv and argv[0] == "enrich":
        return enrich_main(argv[1:])
    if argv and argv[0] == "theory":
        return theory_main(argv[1:])

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


def verify_main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="auto-cnpscts verify",
        description="Сверка наших конспектов с конспектом друга (PDF)",
    )
    parser.add_argument("friend_pdf", type=Path, help="путь к конспекту друга (PDF)")
    parser.add_argument("--out", type=Path, default=Path("presentations") / "conspecty", help="папка с нашими конспектами (по умолчанию presentations/conspecty)")
    parser.add_argument("--model", default=None)
    parser.add_argument("--batch-size", type=int, default=6, help="страниц рукописи на запрос")
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
        logger.error("не задан OPENCODE_API_KEY (заполни .env в корне проекта)")
        return 2
    if not args.friend_pdf.exists():
        logger.error("файл не найден: %s", args.friend_pdf)
        return 2
    if not args.out.is_dir():
        logger.error("папка с конспектами не найдена: %s", args.out)
        return 2

    client_kwargs = {}
    model = args.model or os.environ.get("OPENCODE_MODEL", "").strip() or None
    if model:
        client_kwargs["model"] = model
    client = GoClient(api_key=api_key, **client_kwargs)

    try:
        report_path = verify_conspect(args.friend_pdf, client, args.out, batch_size=args.batch_size, log=logger)
        u = client.usage
        logger.info(
            "готово: %s (запросов: %d, токенов: %d вход / %d выход)",
            report_path, u["requests"], u["prompt_tokens"], u["completion_tokens"],
        )
        return 0
    except Exception as e:  # noqa: BLE001
        logger.error("ошибка: %s", e)
        logger.debug("stack:", exc_info=True)
        return 1
    finally:
        client.close()


def enrich_main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="auto-cnpscts enrich",
        description="Файлы практик из рукописного конспекта друга: только задачи, которых нет в лекциях",
    )
    parser.add_argument("friend_pdf", type=Path, help="путь к конспекту друга (PDF)")
    parser.add_argument("--out", type=Path, default=Path("presentations") / "conspecty", help="папка вывода (по умолчанию presentations/conspecty)")
    parser.add_argument("--model", default=None)
    parser.add_argument("--batch-size", type=int, default=6)
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
        logger.error("не задан OPENCODE_API_KEY (заполни .env в корне проекта)")
        return 2
    if not args.friend_pdf.exists():
        logger.error("файл не найден: %s", args.friend_pdf)
        return 2

    client_kwargs = {}
    model = args.model or os.environ.get("OPENCODE_MODEL", "").strip() or None
    if model:
        client_kwargs["model"] = model
    client = GoClient(api_key=api_key, **client_kwargs)

    try:
        paths = enrich_conspect(args.friend_pdf, client, args.out, batch_size=args.batch_size, log=logger)
        u = client.usage
        logger.info(
            "готово: %d файла(ов) (запросов: %d, токенов: %d вход / %d выход)",
            len(paths), u["requests"], u["prompt_tokens"], u["completion_tokens"],
        )
        return 0
    except Exception as e:  # noqa: BLE001
        logger.error("ошибка: %s", e)
        logger.debug("stack:", exc_info=True)
        return 1
    finally:
        client.close()


def theory_main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="auto-cnpscts theory",
        description="Теория из презентаций: только определения/теоремы/формулы, без задач",
    )
    parser.add_argument("--dir", type=Path, default=DEFAULT_SOURCE_DIR, help="папка с презентациями (по умолчанию presentations/)")
    parser.add_argument("--out", type=Path, default=None, help="папка вывода (по умолчанию conspecty/ рядом с презентациями)")
    parser.add_argument("--force", action="store_true", help="перегенерировать даже существующие файлы теории")
    parser.add_argument("--model", default=None)
    parser.add_argument("--batch-size", type=int, default=8)
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
        logger.error("не задан OPENCODE_API_KEY (заполни .env в корне проекта)")
        return 2
    if not args.dir.is_dir():
        logger.error("папка с презентациями не найдена: %s", args.dir)
        return 2

    out_dir = args.out or (args.dir / "conspecty")
    pdfs = sorted(p for p in args.dir.glob("*.pdf") if p.is_file())
    if not pdfs:
        logger.error("в %s нет PDF", args.dir)
        return 2

    client_kwargs = {}
    model = args.model or os.environ.get("OPENCODE_MODEL", "").strip() or None
    if model:
        client_kwargs["model"] = model
    client = GoClient(api_key=api_key, **client_kwargs)

    try:
        from .pipeline import theory_filename

        failed = []
        done = 0
        for pdf in pdfs:
            path = out_dir / f"{theory_filename(pdf.stem)}.md"
            if path.exists() and not args.force:
                logger.info("пропущен (теория уже есть): %s", pdf.name)
                continue
            try:
                result = run_theory(pdf, client, out_dir, batch_size=args.batch_size, log=logger)
            except Exception as e:  # noqa: BLE001
                logger.error("ошибка на %s: %s", pdf.name, e)
                logger.debug("stack:", exc_info=True)
                failed.append(pdf.name)
                continue
            if result is not None:
                done += 1
                logger.info("готово: %s", result)
        u = client.usage
        logger.info(
            "готово файлов: %d (запросов: %d, токенов: %d вход / %d выход)",
            done, u["requests"], u["prompt_tokens"], u["completion_tokens"],
        )
        if failed:
            logger.error("не удалось: %s", ", ".join(failed))
            return 1
        return 0
    finally:
        client.close()
