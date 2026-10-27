"""Самообновление из Bitbucket — по номеру версии, без git (схема Toolbox ARM).

* проверка — из ветки ``update.ref`` читается файл ``/raw/VERSION``. Номер больше
  установленного — есть обновление; тогда же читается ``/raw/CHANGELOG.md`` и
  показываются записи всех версий новее установленной. Коммиты без смены
  номера в VERSION обновлением не считаются;
* установка — zip ветки (``/archive?format=zip&at=<ветка>``) распаковывается в
  ``data/update/staging``. В архиве должен быть VERSION новее установленного
  (иначе ничего не меняется). Файлы раскладываются поверх папки проекта,
  заменённые сначала копируются в ``data/update/backup/<дата>``: при ошибке
  всё возвращается как было;
* перезапуск — помощник ждёт, пока процесс закроется, докладывает изменённые
  батники (cmd.exe читает их с диска по ходу выполнения — менять на лету нельзя)
  и снова запускает ``start.bat``. Тот сам доставит библиотеки, если изменился
  ``requirements.txt``.

Не трогаются никогда: ``data`` (логи, служебное), ``builder`` (часть автора), ``venv``, ``tmp``,
``.git`` и файлы из ``update.keep`` (по умолчанию ``config.yaml``). Файл,
удалённый из репозитория, удаляется и здесь — только если его положило прошлое
обновление (список — в ``data/update.json``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from . import versioning

ROOT = versioning.ROOT
DATA = ROOT / "data"
SKIP_DIRS = {".git", "data", "builder", "tmp", "venv", ".venv", "env", "__pycache__",
             ".pytest_cache", "node_modules"}
DEFERRED_SUFFIXES = (".bat", ".cmd")      # меняются только после выхода из cmd.exe
REQUIRED_FILES = ("app.py", "run.py", "static/index.html", "VERSION")
BOOT_ID = uuid.uuid4().hex[:12]           # другой после перезапуска — так страница его узнаёт

log = logging.getLogger("vh.update")


# ─────────────────────────── ошибки ───────────────────────────

class UpdateError(Exception):
    def __init__(self, code: str, message: str, hint: str | None = None,
                 details: str | None = None, status: int = 502):
        super().__init__(message)
        self.code, self.message, self.hint, self.details, self.status = code, message, hint, details, status

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "hint": self.hint,
                "details": self.details, "need_auth": self.code == "E_AUTH"}


def auth_error(message="Bitbucket просит логин и пароль", hint=None):
    return UpdateError("E_AUTH", message, hint or "Введите логин и пароль от учётной записи Omega.",
                       status=401)


NON_LATIN = ("Логин или пароль набран русскими буквами. Переключите раскладку на английскую "
             "и введите ещё раз.")


# ─────────────────────────── настройки ───────────────────────────

def _nan(v):
    return None if v is None or (isinstance(v, str) and v.strip().lower() in ("", "nan", "none", "null")) else v


def load_config(root: Path = ROOT) -> dict:
    path = root / "config.yaml"
    raw = {}
    if path.exists():
        import yaml
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    upd = raw.get("update") or {}
    net = raw.get("network") or {}
    keep = _nan(upd.get("keep"))
    keep = ["config.yaml"] if keep is None else ([keep] if isinstance(keep, str) else keep)
    verify = net.get("ssl_verify", False)
    if isinstance(verify, str) and verify.lower() in ("true", "false"):
        verify = verify.lower() == "true"
    return {
        "repo_url": _nan(upd.get("repo_url")),
        "ref": _nan(upd.get("ref")),
        "keep": {str(k).replace("\\", "/").strip("/") for k in keep},
        "check_on_start": bool(upd.get("check_on_start", True)),
        "ssl_verify": _nan(verify) if verify is not False else False,
        "timeout": int(net.get("timeout_s") or 60),
    }


# ─────────────────────────── вспомогательное ───────────────────────────

def _sha(path: Path) -> str:
    d = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 18), b""):
            d.update(chunk)
    return d.hexdigest()


def _rel_files(root: Path) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith((".pyc", ".pyo")):
                continue
            out.append(name if rel_dir == Path(".") else (rel_dir / name).as_posix())
    return out


def repo_api_base(url: str) -> str:
    """https://host/scm/PROJ/repo.git → https://host/rest/api/latest/projects/PROJ/repos/repo"""
    parsed = urlparse(url or "")
    m = re.search(r"/scm/([^/]+)/([^/]+?)(?:\.git)?/?$", parsed.path)
    if not m:
        raise UpdateError("E_REPO", "Не получается разобрать адрес репозитория",
                          "Ожидается https://<bitbucket>/scm/<проект>/<репозиторий>.git — "
                          "update.repo_url в config.yaml.", status=400)
    project, repo = m.groups()
    prefix = parsed.path[: m.start()]
    return f"{parsed.scheme}://{parsed.netloc}{prefix}/rest/api/latest/projects/{project}/repos/{repo}"


def _safe_extract(zip_path: Path, dest: Path) -> None:
    dest = dest.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if not str(target).startswith(str(dest)):
                raise UpdateError("E_UPDATE", "В архиве обновления подозрительный путь",
                                  details=info.filename)
        z.extractall(dest)


# ─────────────────────────── основной класс ───────────────────────────

class Updater:
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.data = root / "data"
        self.work = self.data / "update"
        self.record_path = self.data / "update.json"
        self.login_path = self.data / "login.json"
        self.cfg = load_config(root)
        self._creds: tuple[str, str] | None = None     # пароль — только в памяти
        self._lock = threading.Lock()
        self.job = {"state": "idle"}
        self._restarting = False
        self._setup_log()

    def _setup_log(self):
        try:
            (self.data / "logs").mkdir(parents=True, exist_ok=True)
            h = logging.FileHandler(self.data / "logs" / "update.log", encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            log.addHandler(h)
            log.setLevel(logging.INFO)
        except OSError:
            pass

    # ── логин ──
    def remembered_login(self) -> str | None:
        try:
            return json.loads(self.login_path.read_text(encoding="utf-8")).get("login")
        except (OSError, ValueError, AttributeError):
            return None

    def set_credentials(self, login: str, password: str) -> None:
        login = (login or "").strip()
        if not login or not password:
            raise UpdateError("E_AUTH", "Введите логин и пароль", status=400)
        try:
            f"{login}:{password}".encode("latin-1")
        except UnicodeEncodeError:
            raise UpdateError("E_AUTH", NON_LATIN, status=400)
        self._creds = (login, password)
        try:
            self.data.mkdir(parents=True, exist_ok=True)
            self.login_path.write_text(json.dumps({"login": login}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    # ── HTTP ──
    def _get(self, path: str, params=None, stream=False):
        import requests, urllib3
        if not self.cfg["repo_url"]:
            raise UpdateError("E_CONFIG", "Не указан адрес репозитория",
                              "Заполните update.repo_url в config.yaml.", status=409)
        verify = self.cfg["ssl_verify"]
        if verify is False:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        try:
            r = requests.get(repo_api_base(self.cfg["repo_url"]) + path, params=params,
                             auth=self._creds, verify=verify, timeout=self.cfg["timeout"], stream=stream)
        except requests.exceptions.RequestException as e:
            raise UpdateError("E_NETWORK", "Bitbucket не отвечает",
                              "Проверьте сеть и update.repo_url в config.yaml.", str(e))
        if r.status_code in (401, 403):
            had = self._creds is not None
            self._creds = None
            raise auth_error("Bitbucket не принял логин или пароль" if had else "Bitbucket просит логин и пароль")
        return r

    def _raw(self, name: str):
        return self._get(f"/raw/{name}", {"at": self.cfg["ref"]} if self.cfg["ref"] else None)

    def latest_version(self) -> str:
        r = self._raw(versioning.VERSION_FILE)
        if r.status_code == 404:
            raise UpdateError("E_REPO", "В Bitbucket не найден репозиторий, ветка или файл VERSION",
                              "Проверьте update.repo_url и update.ref в config.yaml.", r.text[:400])
        if r.status_code != 200:
            raise UpdateError("E_HTTP", f"Bitbucket вернул HTTP {r.status_code}", details=r.text[:400])
        r.encoding = "utf-8"
        text = r.text.lstrip("﻿").strip()
        if not versioning.is_valid(text):
            raise UpdateError("E_UPDATE", "В Bitbucket файл VERSION не в том формате",
                              "Нужна одна строка вида 1.0.001.", text[:200])
        return text

    def latest_changelog(self) -> list[dict]:
        try:
            r = self._raw(versioning.CHANGELOG_FILE)
        except UpdateError:
            return []
        if r.status_code != 200:
            return []
        r.encoding = "utf-8"
        return versioning.parse_changelog(r.text.lstrip("﻿"))

    # ── что установлено ──
    def record(self) -> dict:
        try:
            return json.loads(self.record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def current(self) -> dict:
        v = versioning.read_version(self.root)
        entry = next((e for e in versioning.read_changelog(self.root) if e["version"] == v), None)
        return {"version": None if v == versioning.UNKNOWN else v,
                "date": entry["date"] if entry else None,
                "installed_at": self.record().get("installed_at")}

    def info(self) -> dict:
        return {"current": self.current(), "configured": bool(self.cfg["repo_url"]),
                "check_on_start": self.cfg["check_on_start"], "boot": BOOT_ID,
                "authorized": self._creds is not None, "login": self.remembered_login(),
                "job": self.job}

    # ── проверка ──
    def check(self) -> dict:
        self.cfg = load_config(self.root)
        base = self.info()
        if not self.cfg["repo_url"]:
            return {**base, "available": False, "reason": "Не указан update.repo_url в config.yaml."}
        latest_v = self.latest_version()
        cur = base["current"]["version"]
        available = versioning.newer(latest_v, cur)
        changes, latest = [], {"version": latest_v, "date": None}
        if available:
            entries = self.latest_changelog()
            changes = versioning.entries_between(entries, cur, latest_v)
            top = next((e for e in entries if e["version"] == latest_v), None)
            latest["date"] = top["date"] if top else None
        return {**base, "latest": latest, "available": available, "changes": changes,
                "authorized": self._creds is not None}

    # ── установка ──
    def apply(self) -> dict:
        with self._lock:
            if self.job.get("state") == "running":
                return self.job
            self.job = {"state": "running", "message": "готовлюсь", "progress": 0.0, "log": []}
        threading.Thread(target=self._run_apply, daemon=True).start()
        return self.job

    def _step(self, message, progress=None):
        self.job["message"] = message
        if progress is not None:
            self.job["progress"] = progress
        self.job["log"].append(message)
        log.info(message)

    def _run_apply(self):
        try:
            result = self._apply()
            self.job.update(state="done", progress=1.0, result=result,
                            message=f"версия {result['version']} установлена — нужен перезапуск")
            log.info("готово: %s", result)
        except UpdateError as e:
            log.error("%s: %s %s", e.code, e.message, e.details or "")
            self.job.update(state="error", error=e.as_dict(), message=e.message)
        except Exception as e:   # noqa: BLE001
            log.exception("неожиданная ошибка")
            self.job.update(state="error", message="Неожиданная ошибка",
                            error={"code": "E_INTERNAL", "message": "Неожиданная ошибка",
                                   "details": repr(e), "hint": "Подробности в data/logs/update.log"})

    def _download(self, dest: Path):
        params = {"format": "zip"}
        if self.cfg["ref"]:
            params["at"] = self.cfg["ref"]
        r = self._get("/archive", params, stream=True)
        with r:
            if r.status_code != 200:
                raise UpdateError("E_HTTP", f"Bitbucket вернул HTTP {r.status_code}", details=r.text[:400])
            dest.mkdir(parents=True, exist_ok=True)
            archive = dest.parent / "update.zip"
            done = 0
            with open(archive, "wb") as f:
                for chunk in r.iter_content(1 << 18):
                    f.write(chunk)
                    done += len(chunk)
                    self.job["message"] = f"скачано {done / 1048576:.1f} МБ"
        try:
            _safe_extract(archive, dest)
        except zipfile.BadZipFile as e:
            raise UpdateError("E_UPDATE", "Скачанный архив повреждён", details=str(e))
        finally:
            archive.unlink(missing_ok=True)

    def _source_root(self, staging: Path) -> Path:
        if (staging / "app.py").exists():
            return staging
        entries = [p for p in staging.iterdir() if not p.name.startswith(".")]
        return entries[0] if len(entries) == 1 and entries[0].is_dir() else staging

    def _apply(self) -> dict:
        installed = versioning.read_version(self.root)
        staging = self.work / "staging"
        shutil.rmtree(staging, ignore_errors=True)
        self.work.mkdir(parents=True, exist_ok=True)

        self._step("скачиваю последнюю версию", 0.05)
        self._download(staging)
        source = self._source_root(staging)
        self._step("проверяю архив", 0.6)
        missing = [n for n in REQUIRED_FILES if not (source / n).exists()]
        if missing:
            raise UpdateError("E_UPDATE", "Скачанный архив не похож на этот проект",
                              "Проверьте update.repo_url и update.ref в config.yaml.",
                              "нет файлов: " + ", ".join(missing))
        version = versioning.read_version(source)
        if not versioning.newer(version, installed):
            shutil.rmtree(staging, ignore_errors=True)
            raise UpdateError("E_UPDATE", f"В архиве версия {version} — не новее установленной {installed}",
                              "Ничего не изменено.", status=409)

        new_files = _rel_files(source)
        old_files = set(self.record().get("files") or [])
        pending = self.work / "pending"
        shutil.rmtree(pending, ignore_errors=True)
        backup = self.work / "backup" / time.strftime("%Y%m%d-%H%M%S")
        keep = self.cfg["keep"]

        to_write, deferred = [], []
        for rel in new_files:
            if rel in keep and (self.root / rel).exists():
                continue
            src, dst = source / rel, self.root / rel
            if dst.is_file() and _sha(src) == _sha(dst):
                continue
            (deferred if rel.lower().endswith(DEFERRED_SUFFIXES) else to_write).append(rel)
        to_write.sort(key=lambda r: r == versioning.VERSION_FILE)   # VERSION — последним
        to_remove = sorted(r for r in old_files - set(new_files)
                           if r not in keep and (self.root / r).is_file()
                           and r.split("/")[0] not in SKIP_DIRS)

        self._step(f"раскладываю файлы: изменено {len(to_write) + len(deferred)}, "
                   f"удаляется {len(to_remove)}", 0.7)
        done: list[tuple[str, bool]] = []
        try:
            for rel in to_remove + to_write:
                dst = self.root / rel
                existed = dst.exists()
                if existed:
                    (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dst, backup / rel)
                done.append((rel, existed))
                if rel in to_remove:
                    dst.unlink()
                    self._step(f"удалён {rel}")
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_name(dst.name + ".vhupdate")
                shutil.copy2(source / rel, tmp)
                os.replace(tmp, dst)
                self._step(f"обновлён {rel}")
            for rel in deferred:
                (pending / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / rel, pending / rel)
                self._step(f"{rel} — заменится при перезапуске")
        except OSError as e:
            self._step(f"ошибка: {e} — возвращаю прежние файлы")
            for rel, existed in reversed(done):
                dst = self.root / rel
                try:
                    if existed:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup / rel, dst)
                    elif dst.exists():
                        dst.unlink()
                except OSError:
                    pass
            raise UpdateError("E_UPDATE", "Не удалось заменить файлы — всё возвращено как было",
                              "Возможно, файл открыт другой программой. Закройте её и повторите.", str(e))

        self.record_path.write_text(json.dumps({
            "version": version, "previous": installed, "ref": self.cfg["ref"],
            "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": new_files, "pending": deferred}, ensure_ascii=False, indent=1), encoding="utf-8")
        shutil.rmtree(staging, ignore_errors=True)
        return {"version": version, "previous": installed, "changed": len(to_write) + len(deferred),
                "removed": len(to_remove), "deferred": deferred, "restart_required": True,
                "requirements_changed": "requirements.txt" in to_write}

    # ── перезапуск ──
    def restart(self, host: str, port: int, delay: float = 1.0, exit_process=None) -> dict:
        with self._lock:
            if self._restarting:
                return {"restarting": True, "boot": BOOT_ID}
            self._restarting = True
        self.work.mkdir(parents=True, exist_ok=True)
        helper = self.work / "restart_helper.py"
        helper.write_text(HELPER_SOURCE, encoding="utf-8")
        args = [sys.executable, "-I", str(helper), "--root", str(self.root),
                "--pending", str(self.work / "pending"), "--log", str(self.work / "restart.log"),
                "--host", host, "--port", str(port), "--pid", str(os.getpid())]
        if hasattr(os, "getppid"):
            args += ["--pid", str(os.getppid())]
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("TOOLBOX_", "VH_"))}
        kw = dict(cwd=str(self.root), env=env, stdin=subprocess.DEVNULL,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        try:
            if os.name == "nt":
                base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                try:
                    subprocess.Popen(args, creationflags=base | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kw)
                except OSError:
                    subprocess.Popen(args, creationflags=base, **kw)
            else:
                subprocess.Popen(args, start_new_session=True, **kw)
        except OSError as e:
            self._restarting = False
            raise UpdateError("E_RESTART", "Не удалось запустить перезапуск",
                              "Закройте окно и запустите start.bat вручную.", str(e))
        log.info("перезапуск (pid %s)", os.getpid())
        threading.Timer(delay, exit_process or (lambda: os._exit(0))).start()
        return {"restarting": True, "boot": BOOT_ID}


# Помощник перезапуска: пишется в data/update/ из кода текущей версии и запускается
# отдельным процессом; импортов из проекта в нём нет — проект может быть наполовину другим.
HELPER_SOURCE = r'''"""Помощник валидации: дождаться выхода, доложить батники, запустить снова."""
import argparse, os, shutil, subprocess, sys, time

p = argparse.ArgumentParser()
p.add_argument("--root"); p.add_argument("--pending"); p.add_argument("--log")
p.add_argument("--host"); p.add_argument("--port")
p.add_argument("--pid", action="append", type=int, default=[])
a = p.parse_args()


def log(text):
    try:
        with open(a.log, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + text + "\n")
    except OSError:
        pass


def alive(pid):
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000 | 0x00100000, False, pid)
        if not h:
            return False
        try:
            return k.WaitForSingleObject(h, 0) == 0x102
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


log(f"жду завершения {a.pid}")
# Сначала — сам процесс сервера (до 60 с), потом его родитель cmd.exe (до 15 с):
# родителем может оказаться и долгоживущая программа (например, Toolbox ARM).
own, parents = a.pid[:1], [p for p in a.pid[1:] if p > 1]
deadline = time.time() + 60
while any(alive(pid) for pid in own) and time.time() < deadline:
    time.sleep(0.3)
deadline = time.time() + 15
while any(alive(pid) for pid in parents) and time.time() < deadline:
    time.sleep(0.3)
time.sleep(2.0)   # cmd.exe дочитывает start.bat и run_app.bat уже после выхода python

if a.pending and os.path.isdir(a.pending):
    for base, _dirs, files in os.walk(a.pending):
        for name in files:
            src = os.path.join(base, name)
            rel = os.path.relpath(src, a.pending)
            dst = os.path.join(a.root, rel)
            for attempt in range(20):
                try:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    log(f"заменён {rel}")
                    break
                except OSError as error:
                    if attempt == 19:
                        log(f"не удалось заменить {rel}: {error}")
                    time.sleep(0.5)
    shutil.rmtree(a.pending, ignore_errors=True)

args = ["--no-browser", "--host", a.host, "--port", a.port]
try:
    if os.name == "nt":
        subprocess.Popen(["cmd.exe", "/c", os.path.join(a.root, "start.bat"), *args], cwd=a.root,
                         creationflags=subprocess.CREATE_NEW_CONSOLE, close_fds=True)
    else:
        subprocess.Popen([sys.executable, os.path.join(a.root, "run.py"), *args],
                         cwd=a.root, start_new_session=True, close_fds=True)
    log("запущен заново")
except OSError as error:
    log(f"не удалось запустить: {error}")
'''
