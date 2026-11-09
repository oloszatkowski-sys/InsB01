import sys
import os
from pathlib import Path

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
    parser.add_argument("--stats", action="store_true", help="Opublikuj globalne statystyki bota na Discordzie (#statystyki)")
    parser.add_argument("--test", "--test-discord", action="store_true", dest="test", help="Uruchom pełny zestaw testów z powiadomieniami na Discord i ntfy")
    parser.add_argument("--reset-schedule", action="store_true", help="Zresetuj stary harmonogram i wygeneruj nowy plan tygodnia")
    parser.add_argument("--daemon", action="store_true", help="Uruchom ciągły proces harmonogramu w tle (kolejka lokalna)")
    parser.add_argument("--wykrywanie", "--audit", action="store_true", dest="audit", help="Wykonaj audyt detekcji nauczyciela i wyślij mega-raport do #wykrywanie")

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

    elif args.audit:
        log("[*] Uruchamianie audytu bezpieczeństwa i detekcji nauczyciela (#wykrywanie)...")
        bot = InstaLingBot(cfg)
        active = sched.users_mgr.get_active_users()
        target_list = [u for u in active if args.user in (u.get("nickname"), u.get("login"))] if args.user else active
        for u in target_list:
            bot.audit_teacher_detection(u)
        log("[+] Audyt detekcji nauczyciela został ukończony i opublikowany na kanale #wykrywanie.")
        sys.exit(0)

    elif args.stats:
        log(f"[*] Wysyłanie globalnych statystyk bota na kanał #statystyki...")
        sched.notifier.send_bot_global_statistics()
        log("[+] Statystyki bota zostały wysłane na Discord.")

    elif args.test:
        from test_bot import run_tests
        sys.argv.append("--discord")
        success = run_tests()
        sys.exit(0 if success else 1)

    elif args.user:
        res = sched.run_single_user(args.user, trigger_reason="ręczne uruchomienie (--user)")
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

        # Inteligentna pętla sesji:
        # Wykonuje wszystkie sesje na dziś, dopóki mieszczą się w oknie pracy runnera (do 330 min na GitHub Actions)
        # z wbudowanym precyzyjnym zegarem i 45-minutową ochroną antykolizyjną.
        executed_all = []
        start_mono = time.monotonic()
        max_runner_duration_sec = 330 * 60 if os.getenv("GITHUB_ACTIONS") == "true" else 7200

        while True:
            elapsed = time.monotonic() - start_mono
            remaining_runner_budget = max_runner_duration_sec - elapsed
            if remaining_runner_budget <= 300:
                log("[i] Zbliża się limit czasu pracy runnera. Bezpiecznie kończę pętlę na ten cykl.")
                break

            max_wait = max(0, int(remaining_runner_budget - 300))
            if max_wait <= 0:
                break

            results = sched.run_due_cycle(trigger_reason="harmonogram", max_sessions=1, max_wait_seconds=max_wait)
            if not results:
                today_slots = sched.get_today_slots()
                pending = [s for s in today_slots if not s.get("is_off_day") and not s.get("completed", False)]
                status_list = [f"{s['nickname']}: {s['scheduled_time']} ({s['status']})" for s in today_slots]
                if not pending:
                    log("[+] Wszystkie zaplanowane sesje na dzisiaj zostały w 100% ukończone!")
                else:
                    log("[i] Żadna sesja nie oczekuje na wykonanie w bieżącym oknie czasowym.")
                log("    Dzisiejszy harmonogram: " + " | ".join(status_list))
                break

            executed_all.extend(results)

            # Natychmiastowa synchronizacja z Git po ukończeniu sesji
            sched.sync_git_repo_if_ci("Auto: Aktualizacja planu tygodnia i stanu sesji [skip ci]")

            # Sprawdzamy stan pozostałych sesji na dzisiaj
            today_slots = sched.get_today_slots()
            pending = [s for s in today_slots if not s.get("is_off_day") and not s.get("completed", False)]
            if not pending:
                log("[+] Wszystkie zaplanowane sesje na dzisiaj zostały zrealizowane!")
                break

            log(f"[*] Na dzisiaj pozostało jeszcze {len(pending)} sesji. Oczekuję na kolejną...")

        any_failed = any(not r.get("success", False) for r in executed_all)
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

        sys.exit(1 if any_failed else 0)

    elif args.daemon:
        run_daemon()

    else:
        # Domyślnie menu konsolowe (TUI)
        show_main_menu()

if __name__ == "__main__":
    main()
