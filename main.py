import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import argparse
from config import load_config
from storage import Storage
from scheduler import Scheduler
from bot import InstaLingBot
from menu import show_main_menu
from daemon import run_daemon
from web_server import start_web_server

def main():
    parser = argparse.ArgumentParser(description="InstaLing Auto-Bot - Automatyczna nauka i harmonogram")
    parser.add_argument("--menu", action="store_true", help="Uruchom interaktywne menu konsolowe (TUI)")
    parser.add_argument("--web", action="store_true", help="Uruchom serwer Web Panelu (interfejs w przeglądarce)")
    parser.add_argument("--port", type=int, default=5000, help="Port dla Web Panelu (domyślnie 5000)")
    parser.add_argument("--run", action="store_true", help="Wykonaj sesję natychmiast (np. dla GitHub Actions / cron)")
    parser.add_argument("--daemon", action="store_true", help="Uruchom ciągły proces harmonogramu w tle")
    parser.add_argument("--check", action="store_true", help="Sprawdź status harmonogramu na dzisiaj i zakończ")

    args = parser.parse_args()

    if args.web:
        start_web_server(port=args.port)
    elif args.run:
        print("[*] Tryb natychmiastowy: Wykonywanie sesji...")
        cfg = load_config()
        bot = InstaLingBot(cfg)
        res = bot.run_session()
        print(f"Wynik: {res}")
        sys.exit(0 if res.get("success") else 1)
    elif args.daemon:
        run_daemon()
    elif args.check:
        cfg = load_config()
        storage = Storage()
        sched = Scheduler(cfg, storage)
        st = sched.check_execution_status()
        print("\n--- STATUS HARMONOGRAMU ---")
        for k, v in st.items():
            print(f"{k}: {v}")
    else:
        # Domyślnie menu konsolowe
        show_main_menu()

if __name__ == "__main__":
    main()
