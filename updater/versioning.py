"""Версия «Помощника валидации проверок» и история версий (перенесено из Toolbox ARM).

Версия — в файле ``VERSION`` в корне проекта, одна строка вида ``1.0.003``
(``X.Y.NNN``: последняя часть — минимум три цифры). Сравниваются числа, не
строки: ``1.0.010`` новее ``1.0.009``, после ``1.0.999`` идёт ``1.0.1000``.

История — ``CHANGELOG.md`` рядом, новые версии сверху::

    ## 1.0.003 — 2026-10-16
    - что изменилось
    - ещё одно изменение

Тот же разбор используют самообновление (что показать в окне «Доступно
обновление») и ``release/bump_version.py`` (выпуск новой версии).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = "VERSION"
CHANGELOG_FILE = "CHANGELOG.md"
UNKNOWN = "0.0.000"

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d{3,})$")
HEADING_RE = re.compile(r"^##\s+(\d+\.\d+\.\d+)\s*(?:[—–-]+\s*(.*?))?\s*$")
ITEM_RE = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")


def parse(text: str | None) -> tuple[int, int, int] | None:
    """«1.0.003» → (1, 0, 3); не версия — None."""
    match = VERSION_RE.match(str(text or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def is_valid(text: str | None) -> bool:
    return parse(text) is not None


def format_version(parts: tuple[int, int, int]) -> str:
    major, minor, patch = parts
    return f"{major}.{minor}.{patch:03d}"


def newer(a: str | None, b: str | None) -> bool:
    """a новее b. Непонятная b считается самой старой, непонятная a — не новее."""
    pa, pb = parse(a), parse(b)
    if pa is None:
        return False
    return pb is None or pa > pb


def bump(version: str, part: str = "patch") -> str:
    """Следующая версия: patch — 1.0.003 → 1.0.004; minor — 1.1.001; major — 2.0.001."""
    parts = parse(version)
    if parts is None:
        raise ValueError(f"не версия: {version!r} (нужно X.Y.NNN, например 1.0.001)")
    major, minor, patch = parts
    if part == "major":
        return format_version((major + 1, 0, 1))
    if part == "minor":
        return format_version((major, minor + 1, 1))
    return format_version((major, minor, patch + 1))


def read_version(root: Path = ROOT) -> str:
    """Версия из VERSION; нет файла или в нём не версия — UNKNOWN."""
    try:
        text = (Path(root) / VERSION_FILE).read_text(encoding="utf-8-sig").strip()
    except OSError:
        return UNKNOWN
    return text if is_valid(text) else UNKNOWN


def parse_changelog(text: str) -> list[dict]:
    """CHANGELOG.md → [{"version", "date", "changes": [...]}, ...] в порядке файла.

    Всё до первого заголовка «## <версия>» (название, пояснения) пропускается.
    Строка, не начинающаяся с «-» или «*», продолжает предыдущий пункт.
    """
    entries: list[dict] = []
    current: dict | None = None
    for line in (text or "").splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            current = {"version": heading.group(1), "date": (heading.group(2) or "") or None,
                       "changes": []}
            entries.append(current)
            continue
        if current is None or not line.strip():
            continue
        if line.startswith("#"):          # другой заголовок — запись кончилась
            current = None
            continue
        item = ITEM_RE.match(line)
        if item:
            current["changes"].append(item.group(1))
        elif current["changes"]:
            current["changes"][-1] += " " + line.strip()
        else:
            current["changes"].append(line.strip())
    return entries


def read_changelog(root: Path = ROOT) -> list[dict]:
    try:
        return parse_changelog((Path(root) / CHANGELOG_FILE).read_text(encoding="utf-8-sig"))
    except OSError:
        return []


def entries_between(entries: list[dict], installed: str | None, latest: str | None) -> list[dict]:
    """Записи новее installed и не новее latest, новые сверху — «что нового»."""
    result = [e for e in entries
              if newer(e["version"], installed) and not newer(e["version"], latest)]
    return sorted(result, key=lambda e: parse(e["version"]) or (0, 0, 0), reverse=True)


def changelog_problems(version: str, entries: list[dict]) -> list[str]:
    """Что не так с VERSION и историей (для тестов и bump_version)."""
    problems = []
    if not is_valid(version):
        problems.append(f"VERSION: «{version}» — не версия вида X.Y.NNN")
    if not entries:
        problems.append("CHANGELOG.md: нет ни одной записи «## <версия> — <дата>»")
        return problems
    if entries[0]["version"] != version:
        problems.append(f"верхняя запись CHANGELOG.md — {entries[0]['version']}, "
                        f"а в VERSION — {version}")
    seen = set()
    for previous, entry in zip(entries, entries[1:]):
        if not newer(previous["version"], entry["version"]):
            problems.append(f"CHANGELOG.md: {previous['version']} стоит выше "
                            f"{entry['version']}, но не новее её")
    for entry in entries:
        if not is_valid(entry["version"]):
            problems.append(f"CHANGELOG.md: «{entry['version']}» — не версия вида X.Y.NNN")
        if entry["version"] in seen:
            problems.append(f"CHANGELOG.md: версия {entry['version']} встречается дважды")
        seen.add(entry["version"])
        if not entry["changes"]:
            problems.append(f"CHANGELOG.md: у версии {entry['version']} нет ни одного пункта")
    return problems
