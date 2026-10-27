"""Выпуск новой базы для пользователей: собрать → поднять версию → (по желанию) commit и push.

    publish.bat                              # спросит, что ещё изменилось, и про push
    publish.bat --llm qwen2.5:7b             # аргументы сборки передаются в precompute.py
    publish.bat --no-build                   # база уже собрана — только версия и push

Пользователи получат базу кнопкой «Обновить и перезапустить»: обновление
приходит, когда в Bitbucket поднят номер VERSION.
"""
import shutil, sqlite3, subprocess, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
APP = BASE.parent
DB = APP / "base" / "hints.db"


def run(cmd, **kw):
    print(">", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, **kw)


def main(argv):
    no_build = "--no-build" in argv
    build_args = [a for a in argv if a != "--no-build"]
    if not no_build:
        if run([sys.executable, str(BASE / "precompute.py"), *build_args]).returncode != 0:
            print("Сборка не удалась — версия не поднята.")
            return 1
    if not DB.exists():
        print(f"Нет базы {DB}")
        return 1
    meta = dict(sqlite3.connect(f"file:{DB}?mode=ro", uri=True).execute("SELECT key, value FROM meta"))
    msg = f"Обновлена база подсказок: {meta.get('checks')} проверок, сборка {meta.get('built_at')}"
    print(f"\nПункт истории: {msg}")
    extra = input("Что ещё изменилось? (Enter — ничего): ").strip()
    cmd = [sys.executable, str(APP / "release" / "bump_version.py"), "-c", msg]
    if extra:
        cmd += ["-c", extra]
    if run(cmd).returncode != 0:
        return 1

    git = shutil.which("git")
    if not git or not (APP / ".git").exists():
        print("\nТеперь закоммитьте и отправьте в Bitbucket папку приложения:")
        print('  git add base/hints.db VERSION CHANGELOG.md && git commit -m "Новая база" && git push')
        return 0
    version = (APP / "VERSION").read_text(encoding="utf-8").strip()
    if input(f"\nСделать commit и push версии {version}? [y/N]: ").strip().lower() not in ("y", "д", "да", "yes"):
        print("Не отправлено. Вручную: git add base/hints.db VERSION CHANGELOG.md && git commit && git push")
        return 0
    for cmd in (["add", "base/hints.db", "VERSION", "CHANGELOG.md"],
                ["commit", "-m", f"Версия {version}: {msg}"], ["push"]):
        if run([git, "-C", str(APP), *cmd]).returncode != 0:
            print("git завершился ошибкой — проверьте вывод выше.")
            return 1
    print(f"\nГотово: версия {version} в Bitbucket. Пользователи увидят обновление при следующем открытии.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
