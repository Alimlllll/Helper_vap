"""Выпустить новую версию «Помощника валидации проверок»: поднять номер в VERSION и дописать CHANGELOG.md.

    python release/bump_version.py                       # спросит, что изменилось
    python release/bump_version.py -c "Новая кнопка" -c "Исправлена ошибка"
    python release/bump_version.py --minor               # 1.0.015 → 1.1.001
    python release/bump_version.py --major               # 1.0.015 → 2.0.001
    python release/bump_version.py --dry-run             # только показать

По умолчанию поднимается последняя часть: 1.0.015 → 1.0.016. Запись в
CHANGELOG.md получает сегодняшнюю дату и встаёт над предыдущей версией.
Пользователи увидят обновление, когда VERSION и CHANGELOG.md попадут в ветку
update.ref репозитория из config.yaml (коммит + push).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from updater import versioning  # noqa: E402


def ask_changes() -> list[str]:
    print("Что изменилось? По одному пункту в строке, пустая строка — конец.")
    changes = []
    while True:
        try:
            line = input("  - ").strip()
        except EOFError:
            break
        if not line:
            break
        changes.append(line.lstrip("-* ").strip())
    return [c for c in changes if c]


def insert_entry(changelog: str, version: str, day: str, changes: list[str]) -> str:
    """Новая запись — над первой записью «## <версия>» (шапка файла остаётся сверху)."""
    entry = f"## {version} — {day}\n" + "".join(f"- {c}\n" for c in changes) + "\n"
    lines = changelog.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if versioning.HEADING_RE.match(line.rstrip("\r\n")):
            return "".join(lines[:index]) + entry + "".join(lines[index:])
    head = changelog if not changelog or changelog.endswith("\n") else changelog + "\n"
    if head and not head.endswith("\n\n"):
        head += "\n"
    return (head or "# История версий «Помощника валидации проверок»\n\n") + entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Новая версия Помощника валидации")
    level = parser.add_mutually_exclusive_group()
    level.add_argument("--minor", action="store_true", help="1.0.015 → 1.1.001")
    level.add_argument("--major", action="store_true", help="1.0.015 → 2.0.001")
    parser.add_argument("-c", "--change", action="append", default=[],
                        help="пункт «что изменилось» (можно несколько раз)")
    parser.add_argument("--dry-run", action="store_true", help="ничего не записывать")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    root: Path = args.root
    version_path = root / versioning.VERSION_FILE
    changelog_path = root / versioning.CHANGELOG_FILE
    current = versioning.read_version(root)
    if current == versioning.UNKNOWN:
        print(f"Нет файла {version_path} или в нём не версия вида 1.0.001.")
        return 1
    changelog = changelog_path.read_text(encoding="utf-8-sig") if changelog_path.exists() else ""
    problems = versioning.changelog_problems(current, versioning.parse_changelog(changelog))
    if problems:
        print("Сначала поправьте VERSION и CHANGELOG.md:")
        for line in problems:
            print(f"  - {line}")
        return 1

    part = "major" if args.major else "minor" if args.minor else "patch"
    new = versioning.bump(current, part)
    print(f"Сейчас: {current}  →  новая версия: {new}")
    changes = [c.strip() for c in args.change if c.strip()] or ask_changes()
    if not changes:
        print("Не указано ни одного изменения — версия не выпущена.")
        return 1

    today = date.today().isoformat()
    updated = insert_entry(changelog, new, today, changes)
    check = versioning.changelog_problems(new, versioning.parse_changelog(updated))
    if check:                                   # не должно случаться — но проверим
        print("Что-то пошло не так, файлы не изменены:")
        for line in check:
            print(f"  - {line}")
        return 1

    print(f"\n## {new} — {today}")
    for change in changes:
        print(f"- {change}")
    if args.dry_run:
        print("\n--dry-run: файлы не записаны.")
        return 0
    changelog_path.write_text(updated, encoding="utf-8")
    version_path.write_text(new + "\n", encoding="utf-8")
    print(f"\nГотово: VERSION = {new}, запись добавлена в CHANGELOG.md.")
    print("Чтобы пользователи увидели обновление — закоммитьте и отправьте в Bitbucket")
    print("(ветка update.ref из config.yaml), например:")
    print(f'  git add -A && git commit -m "Версия {new}" && git push')
    return 0


if __name__ == "__main__":
    sys.exit(main())
