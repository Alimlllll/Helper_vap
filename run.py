"""
Точка входа для start.bat: запускает сервер и открывает браузер.

    python run.py                      # http://127.0.0.1:8000
    python run.py --port 9000 --no-browser
    python run.py --host 0.0.0.0       # доступ с других компьютеров сети
"""
import argparse, os, socket, sys, threading, webbrowser
from pathlib import Path

BASE = Path(__file__).parent
DB = BASE / "base" / "hints.db"


def free_port(host, port):
    for p in range(port, port + 20):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1" if host == "0.0.0.0" else host, p)) != 0:
                return p
    return port


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if not DB.exists():
        print("ВНИМАНИЕ: нет базы base/hints.db - список проверок будет пустым.\n"
              "Обновите программу (кнопка внизу слева) или соберите базу: builder\\build.bat")

    port = free_port(args.host, args.port)
    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{port}"
    print(f"\nПомощник валидации проверок: {url}\nДля остановки закройте окно или нажмите Ctrl+C\n")
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, [url]).start()

    os.environ["VH_HOST"], os.environ["VH_PORT"] = args.host, str(port)   # для перезапуска после обновления
    import uvicorn
    sys.path.insert(0, str(BASE))
    uvicorn.run("app:app", host=args.host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
