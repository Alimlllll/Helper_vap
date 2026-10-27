"""
Сборка базы подсказок — часть АВТОРА (папка builder/, в репозиторий не попадает).

    build.bat                                   # то же через батник (venv, зависимости)

    python precompute.py                                   # без моделей: теги по словарю, TF-IDF
    python precompute.py --llm api:GigaChat-2              # теги и объяснения по API (GigaChat и др.)
    python precompute.py --llm api:GigaChat-2-Max          # другая модель того же API
    python precompute.py --llm ollama:qwen2.5:7b           # локальная Ollama
    python precompute.py --llm api:GigaChat-2 --emb intfloat/multilingual-e5-base
    python precompute.py --llm api:GigaChat-2 --no-cache   # не брать ответы из кэша

API: адрес — переменная окружения GIGACHAT_API_URL, токен — JPY_API_TOKEN.

Вход:  builder/data/checks/*.json  (в файле — одна проверка или список проверок)
Выход: base/hints.db в папке приложения (SQLite) — его читает приложение пользователей.
       Папка base/ хранится в репозитории вместе с кодом и приезжает с обновлением.
Пути можно поменять: --src <папка с JSON>, --out <файл базы>.

Единица подсказки — ЗАДАЧА (task) из гипотезы похожей проверки. Если у гипотезы
нет задач, подсказкой становится сама гипотеза.
"""
import argparse, json, os, re, sqlite3, time
from pathlib import Path
import numpy as np

BASE = Path(__file__).resolve().parent          # builder/
APP_DIR = BASE.parent                            # приложение пользователей
SRC_DIR = BASE / "data" / "checks"
DB = APP_DIR / "base" / "hints.db"
LLM = None               # задаётся --llm
LLM_TEMPERATURE = 0.01
LLM_TIMEOUT = 120        # секунд на один запрос
LLM_RETRIES = 3          # повторы при 429/5xx и обрывах связи
LLM_CACHE = True         # кэш ответов модели; --no-cache — выключить
LLM_CACHE_FILE = BASE / "cache" / "llm_cache.json"
API_URL_ENV = "GIGACHAT_API_URL"     # переменная окружения с адресом API (без /chat/completions)
API_TOKEN_ENV = "JPY_API_TOKEN"      # переменная окружения с токеном
OLLAMA_URL = "http://localhost:11434"
SCHEMA_VERSION = 1   # формат базы; приложение проверяет его при открытии

# ---- Таксономия процедур («суть» проверки). Ключи — регулярные выражения по нижнему регистру.
TAXONOMY = {
    "сравнение цен с рынком": [r"рыночн", r"внешн(ей|ие|их) (сет|источник)", r"интернет", r"маркетплейс", r"открытых источник", r"завыш"],
    "конкурентная процедура": [r"конкурент", r"коммерческ\w* предлож", r"выбор\w* поставщик", r"торг", r"тендер", r"закупочн"],
    "соответствие спецификации": [r"спецификац", r"характеристик", r"сопоставим"],
    "соответствие нормативным требованиям": [r"сертификат", r"декларац\w* соответств", r"-фз", r"техрегламент", r"тр тс", r"пожарн", r"законодательств"],
    "контроль качества": [r"входн\w* контрол", r"качеств", r"приёмк|приемк", r"дефект"],
    "аффилированность": [r"аффилир", r"конфликт\w* интерес", r"связ\w* .*учредител"],
    "полномочия подписанта": [r"полномоч", r"подписант", r"доверенност"],
    "соблюдение сроков": [r"срок", r"просроч", r"исполнительск"],
    "выборочное тестирование": [r"выборк", r"репрезентатив"],
    "подтверждение исполнения": [r"\bакт(ы|ов|ами|ах)\b", r"фактическ\w* оказ", r"объём\w* услуг|объем\w* услуг", r"смет"],
    "ответственность и организация": [r"виновн", r"ответственн", r"проектн\w* команд", r"назначен"],
}

SIM_TOP_K = 8            # сколько похожих проверок брать
SIM_MIN = 0.15           # минимальная похожесть
W_TAGS, W_TEXT = 0.6, 0.4
DEDUP_TFIDF, DEDUP_EMB = 0.35, 0.85   # порог объединения одинаковых задач
CONFIRMED_BOOST = 1.5    # задача, по которой нарушение подтвердилось, весит больше
TYPICAL_SHARE = 0.5      # задача есть в ≥50% открытых проверок → «типовая»
TYPICAL_MIN = 3
# Задачи, которые всегда считаются типовыми (оформление, а не суть). Регулярные выражения.
TYPICAL_PATTERNS = [r"написан\w* акта", r"хронолог"]


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


# ---------------- загрузка ----------------

def load_checks():
    raw = []
    for f in sorted(SRC_DIR.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        raw.extend(d if isinstance(d, list) else [d])
    checks = []
    for r in raw:
        c = {
            "id": str(r.get("id")),
            "number": r.get("number"),
            "title": clean(r.get("name")) or f"Проверка {r.get('number')}",
            "purpose": clean(r.get("program_tasks")),
            "metrics": clean(r.get("program_metics") or r.get("program_metrics")),
            "background": clean(r.get("program_points")),
            "items": [],   # задачи (или гипотезы без задач)
        }
        for h in r.get("hypos") or []:
            ht = clean(h.get("hypo_title"))
            tasks = h.get("hypo_tasks") or []
            if not tasks and ht:
                tasks = [{"task_title": ht, "task_confirmed": h.get("hypo_confirmed"),
                          "task_results": h.get("hypo_results")}]
            for t in tasks:
                tt = clean(t.get("task_title"))
                if not tt:
                    continue
                conf = t.get("task_confirmed")
                c["items"].append({
                    "task": tt, "hypo": ht,
                    "confirmed": conf if conf is not None else h.get("hypo_confirmed"),
                    "results": clean(t.get("task_results")),
                    "invoice": clean(t.get("task_invoice")),
                    "method": clean(t.get("task_method")),
                })
        c["opened"] = bool(c["items"])
        hyp = list(dict.fromkeys(i["hypo"] for i in c["items"] if i["hypo"]))
        c["text"] = ". ".join([c["title"], c["purpose"], c["metrics"], c["background"], *hyp,
                               *(i["task"] for i in c["items"])])
        c["short"] = ". ".join([c["title"], c["purpose"], c["metrics"]])
        checks.append(c)
    return checks


# ---------------- теги и объяснения ----------------

def tags_by_keywords(text):
    t = text.lower()
    return sorted(tag for tag, kws in TAXONOMY.items() if any(re.search(k, t) for k in kws))


# ---------------- языковая модель (API или Ollama) ----------------
# LLM = "api:<модель>"    — OpenAI-совместимый POST {адрес}/chat/completions (GigaChat и др.)
# LLM = "ollama:<модель>" — локальная Ollama. Без префикса — считается API.

import hashlib

LLM_STATS = {"calls": 0, "cached": 0, "errors": 0, "tokens": 0, "last_error": ""}
_llm_cache = None


def parse_llm(spec):
    """'api:GigaChat-2' → ('api', 'GigaChat-2'); 'ollama:qwen2.5:7b' → ('ollama', 'qwen2.5:7b')."""
    if not spec:
        return None, None
    backend, sep, model = str(spec).partition(":")
    if sep and backend.strip().lower() in ("api", "ollama"):
        return backend.strip().lower(), model.strip()
    return "api", str(spec).strip()


def _api_conf():
    url = (os.getenv(API_URL_ENV) or "").rstrip("/")
    token = os.getenv(API_TOKEN_ENV)
    if not url:
        raise RuntimeError(f"Не задан адрес API: переменная окружения {API_URL_ENV}")
    if not token:
        raise RuntimeError(f"Не задан токен API: переменная окружения {API_TOKEN_ENV}")
    return url, {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def list_api_models():
    """Модели, доступные по API (GET {адрес}/models)."""
    import requests
    url, headers = _api_conf()
    r = requests.get(url + "/models", headers=headers, timeout=LLM_TIMEOUT)
    r.raise_for_status()
    return sorted(m.get("id", "?") for m in r.json().get("data", []))


def _api_chat(model, prompt):
    import requests
    url, headers = _api_conf()
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "n": 1, "temperature": LLM_TEMPERATURE}
    err = None
    for attempt in range(LLM_RETRIES + 1):
        try:
            r = requests.post(url + "/chat/completions", headers=headers, json=body, timeout=LLM_TIMEOUT)
        except requests.RequestException as e:   # обрыв связи, таймаут — повторяем
            err = e
        else:
            if r.ok:
                d = r.json()
                LLM_STATS["tokens"] += (d.get("usage") or {}).get("total_tokens", 0)
                return d["choices"][0]["message"]["content"]
            err = RuntimeError(f"API ответил {r.status_code}: {r.text[:300]}")
            if r.status_code not in (408, 429, 500, 502, 503, 504):
                raise err                        # 401, 404 и т.п. — повтор не поможет
        if attempt < LLM_RETRIES:
            time.sleep(2 * 2 ** attempt)         # 2, 4, 8 с
    raise err


def _ollama(model, prompt, as_json):
    import urllib.request
    body = {"model": model, "prompt": prompt, "stream": False,
            "options": {"temperature": LLM_TEMPERATURE}}
    if as_json:
        body["format"] = "json"
    req = urllib.request.Request(OLLAMA_URL.rstrip("/") + "/api/generate", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=LLM_TIMEOUT).read())
    LLM_STATS["tokens"] += d.get("prompt_eval_count", 0) + d.get("eval_count", 0)
    return d["response"]


def _cache():
    global _llm_cache
    if _llm_cache is None:
        _llm_cache = {}
        if LLM_CACHE and LLM_CACHE_FILE.exists():
            try:
                _llm_cache = json.loads(LLM_CACHE_FILE.read_text(encoding="utf-8"))
            except ValueError:
                _llm_cache = {}
    return _llm_cache


def llm(prompt, as_json=False, model=None, use_cache=True):
    """Один запрос к модели. model — строка как в LLM; по умолчанию берётся LLM."""
    backend, name = parse_llm(model or LLM)
    if not backend:
        raise RuntimeError("Модель не задана (LLM = None)")
    key = hashlib.sha1(f"{backend}|{name}|{LLM_TEMPERATURE}|{prompt}".encode("utf-8")).hexdigest()
    cache = _cache()
    if use_cache and LLM_CACHE and key in cache:
        LLM_STATS["cached"] += 1
        return cache[key]
    LLM_STATS["calls"] += 1
    try:
        text = _api_chat(name, prompt) if backend == "api" else _ollama(name, prompt, as_json)
    except Exception as e:
        LLM_STATS["errors"] += 1
        LLM_STATS["last_error"] = str(e)[:300]
        raise
    if LLM_CACHE:
        cache[key] = text
        LLM_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = LLM_CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, LLM_CACHE_FILE)
    return text


def parse_json(text):
    """JSON из ответа модели: модели по API часто оборачивают его в ```json … ``` или добавляют слова."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"[\[{].*[\]}]", text, re.S)
        if not m:
            raise ValueError("в ответе нет JSON: " + text[:200])
        return json.loads(m.group(0))


def llm_report():
    s = LLM_STATS
    line = f"Модель {LLM}: запросов {s['calls']}, из кэша {s['cached']}, ошибок {s['errors']}, токенов {s['tokens']}"
    if s["errors"]:
        line += f"\n  последняя ошибка: {s['last_error']}  (для этих мест взят запасной вариант без модели)"
    return line


def tags_by_llm(text, model=None):
    prompt = ("Ты помощник аудитора. Определи методические процедуры проверки (суть, а не предмет). "
              "Выбери теги ТОЛЬКО из списка: " + "; ".join(TAXONOMY) +
              '. Ответь только JSON вида {"tags": [...]}, без пояснений.\n\nПроверка:\n' + text[:4000])
    known = {t.lower(): t for t in TAXONOMY}
    try:
        d = parse_json(llm(prompt, as_json=True, model=model))
        d = d.get("tags", []) if isinstance(d, dict) else d
        tags = [known[x.strip().lower()] for x in d if isinstance(x, str) and x.strip().lower() in known]
    except Exception:
        tags = []
    return sorted(set(tags) or tags_by_keywords(text))


def reason_by_tags(c, o):
    common = sorted(set(c["tags"]) & set(o["tags"]))
    only_o = sorted(set(o["tags"]) - set(c["tags"]))
    only_c = sorted(set(c["tags"]) - set(o["tags"]))
    parts = ["Общее: " + (", ".join(common) if common else "близкие по тексту описания")]
    if only_o:
        parts.append("только в источнике: " + ", ".join(only_o))
    if only_c:
        parts.append("только в этой проверке: " + ", ".join(only_c))
    return "; ".join(parts) + "."


def reason_by_llm(c, o, model=None):
    prompt = ("Ты помощник аудитора. Кратко (1–2 предложения, по-русски) объясни, чем по сути (методике) "
              "похожи две проверки и какое различие важно при переносе задач из второй в первую. Без вступлений.\n\n"
              f"Проверка 1: {c['text'][:1500]}\n\nПроверка 2: {o['text'][:1500]}")
    try:
        return llm(prompt, model=model).strip()
    except Exception:
        return reason_by_tags(c, o)


# ---------------- векторы ----------------

def embed(texts, emb_model):
    if not texts:
        return np.zeros((0, 1), dtype=np.float32)
    if emb_model:
        from sentence_transformers import SentenceTransformer
        m = SentenceTransformer(emb_model)
        return np.asarray(m.encode(texts, normalize_embeddings=True), dtype=np.float32)
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize
    X = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True).fit_transform(texts)
    return normalize(X).astype(np.float32)  # разрежённая матрица


def dot(A, B):
    r = A @ B.T
    return r.toarray() if hasattr(r, "toarray") else np.asarray(r)


def jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 0.0


# ---------------- main ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", help="модель: api:GigaChat-2, api:GigaChat-2-Max, ollama:qwen2.5:7b")
    ap.add_argument("--no-cache", action="store_true", help="не брать ответы модели из кэша")
    ap.add_argument("--emb", help="модель sentence-transformers, напр. intfloat/multilingual-e5-base")
    ap.add_argument("--dedup", type=float, help="порог объединения задач")
    ap.add_argument("--src", type=Path, help="папка с JSON проверок (по умолчанию builder/data/checks)")
    ap.add_argument("--out", type=Path, help="файл базы (по умолчанию base/hints.db приложения)")
    args = ap.parse_args()
    global SRC_DIR, DB, LLM, LLM_CACHE
    LLM = args.llm
    LLM_CACHE = not args.no_cache
    SRC_DIR = args.src or SRC_DIR
    DB = args.out or DB
    dedup = args.dedup or (DEDUP_EMB if args.emb else DEDUP_TFIDF)

    checks = load_checks()
    if not checks:
        raise SystemExit(f"Нет JSON проверок в {SRC_DIR}")
    print(f"Проверок: {len(checks)}, из них без задач: {sum(not c['opened'] for c in checks)}")

    for c in checks:
        c["tags"] = tags_by_llm(c["text"], args.llm) if args.llm else tags_by_keywords(c["text"])
        print(f"  {c['number']}: {c['tags']}")
    if LLM:
        print(llm_report())

    # Для неоткрытых проверок есть только описание — тогда сравниваем «короткие» описания.
    E_full = embed([c["text"] for c in checks], args.emb)
    E_short = embed([c["short"] for c in checks], args.emb)
    sim_full, sim_short = dot(E_full, E_full), dot(E_short, E_short)

    all_items = [(ci, it) for ci, c in enumerate(checks) for it in c["items"]]
    QE = embed([it["task"] for _, it in all_items], args.emb)
    QS = dot(QE, QE) if all_items else np.zeros((0, 0))

    # «Типовые» задачи: похожая задача встречается в большой доле проверок
    opened = max(1, sum(c["opened"] for c in checks))
    typical = []
    for k in range(len(all_items)):
        cnt = len({all_items[m][0] for m in np.where(QS[k] >= dedup)[0]})
        by_pattern = any(re.search(p, all_items[k][1]["task"].lower()) for p in TYPICAL_PATTERNS)
        typical.append(by_pattern or (cnt >= TYPICAL_MIN and cnt / opened >= TYPICAL_SHARE))

    # Пишем во временный файл и подменяем в конце: запущенное приложение
    # всё это время видит прежнюю базу, а не наполовину собранную.
    DB.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = DB.with_suffix(".db.tmp")
    tmp_db.unlink(missing_ok=True)
    db = sqlite3.connect(tmp_db)
    db.executescript("""
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE checks(id TEXT PRIMARY KEY, number TEXT, title TEXT, purpose TEXT, metrics TEXT,
                            background TEXT, tags TEXT, opened INTEGER, items TEXT);
        CREATE TABLE similar(check_id TEXT, similar_id TEXT, score REAL, common_tags TEXT, reason TEXT);
        CREATE TABLE hints(check_id TEXT, hint_no INTEGER, task TEXT, hypo TEXT, score REAL,
                           typical INTEGER, confirmed INTEGER, total INTEGER, covered TEXT, sources TEXT);
    """)
    for c in checks:
        db.execute("INSERT INTO checks VALUES(?,?,?,?,?,?,?,?,?)",
                   (c["id"], str(c["number"]), c["title"], c["purpose"], c["metrics"], c["background"],
                    json.dumps(c["tags"], ensure_ascii=False), int(c["opened"]),
                    json.dumps(c["items"], ensure_ascii=False)))

    for i, c in enumerate(checks):
        sims = []
        for j, o in enumerate(checks):
            if i == j or not o["opened"]:
                continue  # неоткрытая проверка не может быть источником задач
            ts = sim_full[i, j] if c["opened"] else sim_short[i, j]
            s = W_TAGS * jaccard(c["tags"], o["tags"]) + W_TEXT * float(ts)
            if s >= SIM_MIN:
                sims.append((s, j))
        sims = sorted(sims, reverse=True)[:SIM_TOP_K]
        weight = {j: s for s, j in sims}
        for s, j in sims:
            o = checks[j]
            common = sorted(set(c["tags"]) & set(o["tags"]))
            reason = reason_by_llm(c, o, args.llm) if args.llm else reason_by_tags(c, o)
            db.execute("INSERT INTO similar VALUES(?,?,?,?,?)",
                       (c["id"], o["id"], round(s, 3), json.dumps(common, ensure_ascii=False), reason))

        # Задачи похожих проверок → объединяем дубли
        idx = [k for k, (ci, _) in enumerate(all_items) if ci in weight]
        clusters = []
        for k in sorted(idx, key=lambda k: -weight[all_items[k][0]]):
            for cl in clusters:
                if QS[k, cl[0]] >= dedup:
                    cl.append(k)
                    break
            else:
                clusters.append([k])

        own = [k for k, (ci, _) in enumerate(all_items) if ci == i]  # задачи самой проверки
        hints = []
        for cl in clusters:
            src = {}
            for k in cl:
                ci, it = all_items[k]
                o = checks[ci]
                s = src.setdefault(o["id"], {"check_id": o["id"], "number": o["number"],
                                             "score": round(weight[ci], 3), "items": []})
                s["items"].append(it)
            conf = sum(1 for k in cl if all_items[k][1]["confirmed"])
            score = sum(weight[all_items[k][0]] * (CONFIRMED_BOOST if all_items[k][1]["confirmed"] else 1)
                        for k in cl)
            rep = all_items[cl[0]][1]
            # есть ли похожая задача уже в программе этой проверки
            covered = ""
            if own:
                best = max(own, key=lambda m: QS[cl[0], m])
                if QS[cl[0], best] >= dedup:
                    covered = all_items[best][1]["task"]
            hints.append((int(any(typical[k] for k in cl)), -score, rep["task"], rep["hypo"],
                          conf, len(cl), covered, list(src.values())))
        hints.sort(key=lambda h: (h[0], h[1]))  # сначала содержательные, типовые в конце
        for no, (typ, nscore, task, hypo, conf, total, covered, src) in enumerate(hints, 1):
            db.execute("INSERT INTO hints VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (c["id"], no, task, hypo, round(-nscore, 3), typ, conf, total, covered,
                        json.dumps(src, ensure_ascii=False)))

    meta = {"schema_version": SCHEMA_VERSION, "built_at": time.strftime("%Y-%m-%d %H:%M"),
            "checks": len(checks), "opened": sum(c["opened"] for c in checks),
            "llm": args.llm or "", "emb": args.emb or "", "dedup": dedup}
    db.executemany("INSERT INTO meta VALUES(?,?)", [(k, str(v)) for k, v in meta.items()])
    db.commit()
    db.close()
    os.replace(tmp_db, DB)
    if LLM:
        print(llm_report())
    print(f"Готово: {DB}")
    print(f"База от {meta['built_at']}: {meta['checks']} проверок ({meta['opened']} с задачами)")


if __name__ == "__main__":
    main()
