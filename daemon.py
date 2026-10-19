import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime
from config import load_config
from storage import Storage
from scheduler import Scheduler
from bot import InstaLingBot

def run_daemon():
    print("=" * 60)
    print("   🤖 INSTALING BOT - DAEMON (HARMONOGRAM W TLE)    ")
    print("=" * 60)
    print("[*] Demon uruchomiony. Sprawdzanie harmonogramu co minutę.")
    print("[*] Naciśnij Ctrl+C, aby przerwać.\n")

    last_logged_minute = -1

    while True:
        try:
            cfg = load_config()
            storage = Storage()
            scheduler = Scheduler(cfg, storage)
            status = scheduler.check_execution_status()

            now = datetime.now()
            # Co 30 minut wypisujemy przypomnienie o stanie
            if now.minute % 30 == 0 and now.minute != last_logged_minute:
                last_logged_minute = now.minute
                print(f"[{now.strftime('%H:%M:%S')}] Status: Dziś={status['weekday_name']}, Plan={status['planned_time']}, Ukończono={status['is_done']}, Roboczy={status['is_workday']}")

            if status["can_run_now"]:
                print("\n" + "=" * 60)
                print(f"[*] Wybiła zaplanowana godzina ({status['planned_time']})! Rozpoczynanie sesji...")
                print("=" * 60)
                bot = InstaLingBot(cfg)
                res = bot.run_session()
                print(f"[+] Zakończono sesję. Wynik: {res}")
                
                # Zaznaczamy dzień jako zrobiony
                scheduler.mark_done_today(now.date())
                print("[*] Dzień oznaczony jako ukończony. Oczekiwanie na jutro...\n")

            time.sleep(60)

        except KeyboardInterrupt:
            print("\n[!] Zatrzymano demona harmonogramu.")
            break
        except Exception as e:
            print(f"[!] Błąd w pętli demona: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_daemon()
