import http.server
import json
import os
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from config import load_config, save_config
from storage import Storage
from scheduler import Scheduler
from bot import InstaLingBot

WEB_DIR = Path(__file__).resolve().parent / "web"
latest_logs = []
run_lock = threading.Lock()
is_running = False

def log_event(msg: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    print(entry)
    latest_logs.append(entry)
    if len(latest_logs) > 200:
        latest_logs.pop(0)

class BotWebHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = self.path.split("?")[0]

        if url == "/api/status":
            cfg = load_config()
            storage = Storage()
            scheduler = Scheduler(cfg, storage)
            status = scheduler.check_execution_status()
            status["config"] = cfg
            status["words_count"] = len(storage.words)
            status["history_count"] = len(storage.history)
            status["is_running_now"] = is_running
            self._send_json(status)
            return

        elif url == "/api/words":
            storage = Storage()
            self._send_json(storage.words)
            return

        elif url == "/api/history":
            storage = Storage()
            self._send_json(storage.history)
            return

        elif url == "/api/logs":
            self._send_json({"logs": latest_logs, "is_running": is_running})
            return

        return super().do_GET()

    def do_POST(self):
        url = self.path.split("?")[0]
        content_len = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_len).decode("utf-8")
        body = json.loads(post_data) if post_data else {}

        if url == "/api/config":
            cfg = load_config()
            cfg.update(body)
            save_config(cfg)
            log_event("Zaktualizowano konfigurację przez Web Panel.")
            self._send_json({"success": True, "config": cfg})
            return

        elif url == "/api/words":
            storage = Storage()
            prompt = body.get("prompt", "").strip()
            answer = body.get("answer", "").strip()
            sentence = body.get("sentence", "").strip()
            if prompt and answer:
                storage.record_word(answer, prompt, sentence)
                log_event(f"Dodano słówko z panelu: '{prompt}' -> '{answer}'")
                self._send_json({"success": True})
            else:
                self._send_json({"success": False, "error": "Brak promptu lub odpowiedzi."}, status=400)
            return

        elif url == "/api/run":
            global is_running
            if is_running:
                self._send_json({"success": False, "error": "Sesja jest już w toku."}, status=400)
                return

            def runner_thread():
                global is_running
                with run_lock:
                    is_running = True
                    log_event("▶ Ręczne uruchomienie sesji z panelu WWW...")
                    try:
                        cfg = load_config()
                        bot = InstaLingBot(cfg)
                        res = bot.run_session()
                        log_event(f"Wynik sesji: {res}")
                        if res.get("success"):
                            sched = Scheduler(cfg, Storage())
                            sched.mark_done_today(datetime.now().date())
                    except Exception as e:
                        log_event(f"Błąd sesji: {e}")
                    finally:
                        is_running = False

            t = threading.Thread(target=runner_thread, daemon=True)
            t.start()
            self._send_json({"success": True, "message": "Rozpoczęto wykonywanie sesji w tle."})
            return

        self.send_error(404, "Endpoint not found")

    def do_DELETE(self):
        url = self.path.split("?")[0]
        if url == "/api/words":
            storage = Storage()
            storage.words = {}
            storage.save_words()
            log_event("Wyczyszczono bazę słówek.")
            self._send_json({"success": True})
            return
        self.send_error(404, "Endpoint not found")

def start_web_server(port: int = 5000, open_browser: bool = True):
    server_address = ("", port)
    httpd = http.server.HTTPServer(server_address, BotWebHandler)
    url = f"http://localhost:{port}"
    print(f"\n[🌐] Serwer Web Panelu działa pod adresem: {url}")
    print("Naciśnij Ctrl+C, aby zatrzymać serwer.\n")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nZatrzymywanie serwera Web Panelu...")
        httpd.server_close()

if __name__ == "__main__":
    start_web_server()
