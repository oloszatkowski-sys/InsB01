import sys
import time
from config import load_config
from multi_scheduler import MultiScheduler
from logger import log
from timezone_utils import now_warsaw, today_warsaw, format_warsaw, get_current_polish_tzname

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

def run_daemon():
    print("=" * 65)
    print("   🤖 INSTALING BOT - DAEMON (HARMONOGRAM MULTI-USER)    ")
    print(f"   🇵🇱 Czas w Polsce: {format_warsaw(now_warsaw())} ({get_current_polish_tzname()})")
    print("=" * 65)
    log("[*] Demon uruchomiony. Zarządzanie zadaniami w strefie Europe/Warsaw.")
    log("[*] Naciśnij Ctrl+C, aby przerwać.\n")

    cfg = load_config()
    scheduler = MultiScheduler(cfg)

    # Przy starcie publikujemy plan dnia
    try:
        scheduler.publish_today_plan_to_discord()
    except Exception as e:
        log(f"[!] Nie udało się opublikować planu startowego: {e}")

    last_logged_minute = -1
    last_published_date = today_warsaw().isoformat()

    while True:
        try:
            cfg = load_config()
            scheduler = MultiScheduler(cfg)
            today_str = today_warsaw().isoformat()
            now_pl = now_warsaw()

            # Nowy dzień -> publikacja nowego planu na dziś o poranku (np. po 6:00)
            if today_str != last_published_date and now_pl.hour >= 6:
                log(f"[*] Nowy dzień w Polsce ({today_str})! Generowanie i publikacja planu na dziś...")
                scheduler.publish_today_plan_to_discord()
                last_published_date = today_str

            # Sprawdzenie i wykonanie oczekującej sesji (maksymalnie 1 sesja na cykl)
            scheduler.run_due_cycle(trigger_reason="harmonogram (demon)")

            # Log statusu co 30 minut
            if now_pl.minute % 30 == 0 and now_pl.minute != last_logged_minute:
                last_logged_minute = now_pl.minute
                today_slots = scheduler.get_today_slots()
                active_status = [f"{p['nickname']} ({p['scheduled_time']}: {p['status']})" for p in today_slots]
                log(f"[{format_warsaw(now_pl)}] Status harmonogramu: " + " | ".join(active_status))

            time.sleep(30)

        except KeyboardInterrupt:
            log("\n[!] Zatrzymano demona harmonogramu.")
            break
        except Exception as e:
            log(f"[!] Błąd w pętli demona: {e}")
            time.sleep(30)

if __name__ == "__main__":
    run_daemon()
