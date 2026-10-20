import sys
import time
from datetime import datetime, date
from config import load_config
from multi_scheduler import MultiScheduler
from logger import log

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

def run_daemon():
    print("=" * 60)
    print("   🤖 INSTALING BOT - DAEMON (HARMONOGRAM MULTI-USER)    ")
    print("=" * 60)
    log("[*] Demon uruchomiony. Zarządzanie kolejką wielu użytkowników.")
    log("[*] Naciśnij Ctrl+C, aby przerwać.\n")

    cfg = load_config()
    scheduler = MultiScheduler(cfg)

    # Przy starcie publikujemy plan dnia
    try:
        scheduler.publish_today_plan_to_discord()
    except Exception as e:
        log(f"[!] Nie udało się opublikować planu startowego: {e}")

    last_logged_minute = -1
    last_published_date = date.today().isoformat()

    while True:
        try:
            cfg = load_config()
            scheduler = MultiScheduler(cfg)
            today_str = date.today().isoformat()

            # Nowy dzień -> publikacja nowego planu na dziś
            if today_str != last_published_date and datetime.now().hour >= 6:
                log(f"[*] Nowy dzień ({today_str})! Generowanie i publikacja planu na dziś...")
                scheduler.publish_today_plan_to_discord()
                last_published_date = today_str

            # Sprawdzenie i ewentualne wykonanie sesji w kolejce
            scheduler.run_queue_cycle()

            now = datetime.now()
            if now.minute % 30 == 0 and now.minute != last_logged_minute:
                last_logged_minute = now.minute
                plan = scheduler.generate_today_plan()
                active_status = [f"{p['nickname']} ({p['scheduled_time']}: {p['status']})" for p in plan]
                log(f"[{now.strftime('%H:%M:%S')}] Status kolejki: " + " | ".join(active_status))

            time.sleep(60)

        except KeyboardInterrupt:
            log("\n[!] Zatrzymano demona harmonogramu.")
            break
        except Exception as e:
            log(f"[!] Błąd w pętli demona: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_daemon()
