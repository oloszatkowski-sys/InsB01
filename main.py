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
from timezone_utils import (
    now_warsaw,
    now_utc,
    today_warsaw,
    format_warsaw,
    format_utc,
    get_current_polish_tzname
)

def main():
    parser = argparse.ArgumentParser(description="InstaLing Auto-Bot - Multi-User Edition (Europe/Warsaw)")
    parser.add_argument("--menu", action="store_true", help="Uruchom interaktywne menu konsolowe (TUI)")
    parser.add_argument("--web", action="store_true", help="Uruchom serwer Web Panelu (interfejs w przeglądarce)")
    parser.add_argument("--port", type=int, default=5000, help="Port dla Web Panelu (domyślnie 5000)")
    parser.add_argument("--run", action="store_true", help="Inteligentne sprawdzenie i uruchomienie oczekującej sesji wg harmonogramu")
    parser.add_argument("--cron", action="store_true", help="Tryb cykliczny używany przez zadania w chmurze (GitHub Actions)")
    parser.add_argument("--morning", "--daily-check", action="store_true", dest="morning", help="Poranny przegląd o 06:30 (aktualizacja PLAN_TYGODNIA.md, wysyłka na Discord i ntfy)")
    parser.add_argument("--run-all", action="store_true", help="Wymuszone wykonanie sesji dla wszystkich aktywnych kont (jedno po drugim)")
    parser.add_argument("--user", type=str, default="", help="Wykonaj sesję tylko dla wybranego pseudonimu lub loginu")
    parser.add_argument("--plan", action="store_true", help="Opublikuj plan na dziś na Discordzie (#plan-na-dzis)")
    parser.add_argument("--week", action="store_true", help="Opublikuj plan tygodnia na Discordzie (#plan-tygodnia)")
    parser.add_argument("--reset-schedule", action="store_true", help="Zresetuj stary harmonogram i wygeneruj nowy plan tygodnia")
    parser.add_argument("--daemon", action="store_true", help="Uruchom ciągły proces harmonogramu w tle (kolejka lokalna)")

    args = parser.parse_args()
    cfg = load_config()
    sched = MultiScheduler(cfg)

    if args.web:
        start_web_server(port=args.port)

    elif args.reset_schedule:
        log("[*] Żądanie kontrolowanego resetu harmonogramu...")
        new_plan = sched.reset_schedule()
        sched.publish_weekly_plan_to_discord()
        sched.publish_today_plan_to_discord()
        log("[+] Harmonogram zresetowany i opublikowany na Discordzie.")

    elif args.morning:
        res = sched.run_morning_check()
        log(f"[+] Poranny przegląd 06:30 zrealizowany (data: {res.get('date')}).")
        sys.exit(0)

    elif args.plan:
        log(f"[*] Generowanie i publikowanie planu na dziś na Discordzie (strefa {get_current_polish_tzname()})...")
        sched.publish_today_plan_to_discord()
        log("[+] Plan na dziś został wysłany.")

    elif args.week:
        log(f"[*] Generowanie i publikowanie planu tygodnia na Discordzie (strefa {get_current_polish_tzname()})...")
        sched.publish_weekly_plan_to_discord()
        log("[+] Plan tygodnia został wysłany.")

    elif args.user:
        res = sched.run_single_user(args.user, trigger_reason="ręczne uruchomienie (--user)")
        try:
            sched.publish_today_plan_to_discord()
        except Exception:
            pass
        sys.exit(0 if res.get("success") else 1)

    elif args.run or args.cron:
        now_pl = now_warsaw()
        log(f"[*] Uruchomienie wg harmonogramu: {format_warsaw(now_pl)} | {format_utc()}")

        # Jeśli uruchomienie następuje w oknie porannym (06:xx) i poranny przegląd nie był jeszcze robiony, zrób go
        today_str = today_warsaw().isoformat()
        weekly = sched.get_or_create_weekly_schedule()
        if now_pl.hour == 6 and weekly.get("last_morning_check_date") != today_str:
            log("[*] Wykryto okno poranne 06:xx - wykonuję poranny przegląd...")
            sched.run_morning_check()

        # Upewniamy się, że ogłoszenia dzienne/tygodniowe są aktualne
        sched.check_and_publish_daily_announcements()

        # Sprawdzamy czy są sesje oczekujące w tym momencie
        due_slots = sched.get_due_slots()
        if not due_slots:
            today_slots = sched.get_today_slots()
            status_list = [f"{s['nickname']}: {s['scheduled_time']} ({s['status']})" for s in today_slots]
            log("[i] Żadna sesja nie oczekuje na wykonanie w tym momencie.")
            log("    Dzisiejszy harmonogram: " + " | ".join(status_list))
            sys.exit(0)

        # Wykonujemy MAKSYMALNIE 1 sesję na wywołanie crona, aby zachować odstęp czasowy
        results = sched.run_due_cycle(trigger_reason="harmonogram", max_sessions=1)
        any_failed = any(not r.get("success", False) for r in results)
        
        # Aktualizujemy plan na Discordzie po wykonaniu zadania
        try:
            sched.publish_today_plan_to_discord()
        except Exception:
            pass

        sys.exit(1 if any_failed else 0)

    elif args.run_all:
        log("[*] Wymuszone wykonanie sesji dla wszystkich kont...")
        users_mgr = UsersManager()
        active = users_mgr.get_active_users()
        any_failed = False

        for i, u in enumerate(active):
            nick = u.get("nickname", "Uczeń")
            log(f"\n[*] Kolejka ({i+1}/{len(active)}): Wykonuję sesję dla {nick}")
            res = sched.run_single_user(nick, trigger_reason="wymuszone uruchomienie (--run-all)")
            if not res.get("success"):
                any_failed = True

            if i < len(active) - 1:
                pause_s = random.uniform(30.0, 60.0)
                log(f"[*] Bezpieczny odstęp {pause_s:.0f}s przed kolejnym użytkownikiem...")
                time.sleep(pause_s)

        try:
            sched.publish_today_plan_to_discord()
        except Exception:
            pass

        sys.exit(1 if any_failed else 0)

    elif args.daemon:
        run_daemon()

    else:
        # Domyślnie menu konsolowe (TUI)
        show_main_menu()

if __name__ == "__main__":
    main()
