import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import argparse
import time
import random
from config import load_config
from storage import Storage
from bot import InstaLingBot
from menu import show_main_menu
from daemon import run_daemon
from web_server import start_web_server
from users_manager import UsersManager, mask_login
from multi_scheduler import MultiScheduler
from logger import log

def main():
    parser = argparse.ArgumentParser(description="InstaLing Auto-Bot - Multi-User Edition")
    parser.add_argument("--menu", action="store_true", help="Uruchom interaktywne menu konsolowe (TUI)")
    parser.add_argument("--web", action="store_true", help="Uruchom serwer Web Panelu (interfejs w przeglądarce)")
    parser.add_argument("--port", type=int, default=5000, help="Port dla Web Panelu (domyślnie 5000)")
    parser.add_argument("--run", action="store_true", help="Wykonaj sesje w kolejce dla aktywnych uzytkownikow")
    parser.add_argument("--user", type=str, default="", help="Wykonaj sesje tylko dla wybranego pseudonimu")
    parser.add_argument("--plan", action="store_true", help="Opublikuj plan na dzis na Discordzie (#plan-na-dzis)")
    parser.add_argument("--week", action="store_true", help="Opublikuj plan tygodnia na Discordzie (#plan-tygodnia)")
    parser.add_argument("--daemon", action="store_true", help="Uruchom ciagly proces harmonogramu w tle (kolejka)")

    args = parser.parse_args()
    cfg = load_config()

    if args.web:
        start_web_server(port=args.port)
    elif args.plan:
        log("[*] Generowanie i publikowanie planu na dziś na Discordzie...")
        sched = MultiScheduler(cfg)
        sched.publish_today_plan_to_discord()
        log("[+] Plan na dziś został wysłany.")
    elif args.week:
        log("[*] Generowanie i publikowanie planu tygodnia na Discordzie...")
        sched = MultiScheduler(cfg)
        sched.publish_weekly_plan_to_discord()
        log("[+] Plan tygodnia został wysłany.")
    elif args.run:
        log("[*] Tryb wykonania sesji...")
        users_mgr = UsersManager()
        active = users_mgr.get_active_users()

        if args.user:
            active = [u for u in active if u.get("nickname", "").lower() == args.user.lower()]
            if not active:
                log(f"[!] Nie znaleziono użytkownika o pseudonimie: {args.user}")
                sys.exit(1)

        bot = InstaLingBot(cfg)
        any_failed = False

        for i, user in enumerate(active):
            nick = user.get("nickname", "Uczeń")
            log(f"\n==================================================")
            log(f"[*] Kolejka ({i+1}/{len(active)}): Rozpoczynam sesje dla {nick}")
            log(f"==================================================")

            res = bot.run_session(user=user)
            if not res.get("success", False):
                any_failed = True

            # Jeśli jest kolejny użytkownik, bezpieczna przerwa
            if i < len(active) - 1:
                wait_sec = random.uniform(25.0, 45.0)
                log(f"[*] Odczekanie {wait_sec:.0f}s przed nastepnym uzytkownikiem w kolejce...")
                time.sleep(wait_sec)

        sys.exit(1 if any_failed else 0)

    elif args.daemon:
        run_daemon()
    else:
        # Domyślnie menu konsolowe
        show_main_menu()

if __name__ == "__main__":
    main()
