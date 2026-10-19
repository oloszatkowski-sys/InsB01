import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime
from config import load_config, save_config, DEFAULT_CONFIG
from storage import Storage
from scheduler import Scheduler, DAY_NAMES
from bot import InstaLingBot

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def print_header():
    print("=" * 60)
    print("        🤖 INSTALING AUTO-BOT - PANEL KONTROLNY        ")
    print("=" * 60)

def menu_credentials(cfg):
    clear_screen()
    print_header()
    print("\n--- [1] DANE LOGOWANIA ---")
    current_log = cfg.get("login", "")
    print(f"Obecny login: {current_log if current_log else '[brak]'}")
    has_pass = bool(cfg.get("password"))
    print(f"Hasło: {'********' if has_pass else '[brak]'}")
    
    new_login = input("\nPodaj nowy login (lub Enter aby zachować): ").strip()
    if new_login:
        cfg["login"] = new_login

    new_pass = input("Podaj nowe hasło (lub Enter aby zachować): ").strip()
    if new_pass:
        cfg["password"] = new_pass

    save_config(cfg)
    print("\n[✓] Zapisano dane logowania.")
    input("\nNaciśnij Enter, aby wrócić...")

def menu_schedule(cfg):
    clear_screen()
    print_header()
    print("\n--- [2] TRYB HARMONOGRAMU (GODZINY) ---")
    cur_mode = cfg.get("schedule_mode", "random")
    print(f"Aktualny tryb: {'LOSOWE GODZINY' if cur_mode == 'random' else 'STAŁA GODZINA'}")
    print(f"Stała godzina: {cfg.get('fixed_time', '17:30')}")
    print(f"Okno losowania: {cfg.get('random_window_start', '14:30')} - {cfg.get('random_window_end', '20:45')}")
    print(f"Losowy jitter: +/- {cfg.get('random_jitter_minutes', 15)} min")
    
    print("\nWybierz:")
    print("1. Tryb stałej godziny (np. zawsze o 17:30)")
    print("2. Tryb losowych godzin (np. losowo między 14:30 a 20:45 z losowym przesunięciem)")
    print("0. Wróć")
    
    choice = input("\nWybór: ").strip()
    if choice == "1":
        cfg["schedule_mode"] = "fixed"
        val = input(f"Podaj stałą godzinę HH:MM (obecna: {cfg.get('fixed_time', '17:30')}): ").strip()
        if val:
            cfg["fixed_time"] = val
    elif choice == "2":
        cfg["schedule_mode"] = "random"
        start_w = input(f"Początek okna HH:MM (obecny: {cfg.get('random_window_start', '14:30')}): ").strip()
        if start_w:
            cfg["random_window_start"] = start_w
        end_w = input(f"Koniec okna HH:MM (obecny: {cfg.get('random_window_end', '20:45')}): ").strip()
        if end_w:
            cfg["random_window_end"] = end_w
        jit = input(f"Losowy jitter w minutach (obecny: {cfg.get('random_jitter_minutes', 15)}): ").strip()
        if jit.isdigit():
            cfg["random_jitter_minutes"] = int(jit)

    save_config(cfg)
    print("\n[✓] Zapisano ustawienia harmonogramu.")
    input("\nNaciśnij Enter, aby wrócić...")

def menu_missed_days(cfg):
    clear_screen()
    print_header()
    print("\n--- [3] CZĘSTOTLIWOŚĆ WYPADKÓW (DNI WOLNE) ---")
    cur_mode = cfg.get("miss_days_mode", "random")
    count = cfg.get("miss_days_count", 1)
    fixed_days = cfg.get("miss_fixed_days", [5, 6])
    fixed_names = ", ".join([DAY_NAMES[i] for i in fixed_days if 0 <= i < 7])

    print(f"Aktualny tryb opuszczania dni: {cur_mode.upper()}")
    print(f"Liczba losowych dni wolnych: {count} dni w tygodniu")
    print(f"Stałe dni wolne: {fixed_names if fixed_names else 'Brak'}")

    print("\nWybierz:")
    print("1. Losowe dni wolne w tygodniu (np. 1 lub 2 dni - bot losowo 'zapomina')")
    print("2. Stałe dni wolne (np. zawsze sobota i niedziela)")
    print("3. Wyłącz dni wolne (bot robi lekcje codziennie 7/7)")
    print("0. Wróć")

    choice = input("\nWybór: ").strip()
    if choice == "1":
        cfg["miss_days_mode"] = "random"
        c = input("Ile losowych dni wolnych w tygodniu (1, 2, 3)? [domyślnie 1]: ").strip()
        if c.isdigit():
            cfg["miss_days_count"] = int(c)
    elif choice == "2":
        cfg["miss_days_mode"] = "fixed"
        print("Wybierz dni tygodnia (oddzielone przecinkami, np. 5,6 dla sob/ndz):")
        for i, d in enumerate(DAY_NAMES):
            print(f"  {i}: {d}")
        sel = input("Podaj numery dni: ").strip()
        if sel:
            try:
                cfg["miss_fixed_days"] = [int(x.strip()) for x in sel.split(",") if x.strip().isdigit()]
            except Exception:
                pass
    elif choice == "3":
        cfg["miss_days_mode"] = "none"
        cfg["miss_days_count"] = 0

    save_config(cfg)
    print("\n[✓] Zapisano ustawienia dni wolnych.")
    input("\nNaciśnij Enter, aby wrócić...")

def menu_anti_detection(cfg):
    clear_screen()
    print_header()
    print("\n--- [4] ANTY-DETEKCJA I SYMULACJA CZŁOWIEKA ---")
    print(f"1. Docelowa skuteczność sesji: {cfg.get('target_accuracy_percent', 91)}% (celowe błędy)")
    print(f"2. Szansa na literówkę i Backspace: {cfg.get('typo_chance_percent', 6)}%")
    print(f"3. Czas na czytanie zdania: {cfg.get('read_time_min_s', 1.8)}s - {cfg.get('read_time_max_s', 3.8)}s")
    print(f"4. Szybkość pisania (opóźnienie): {cfg.get('typing_speed_min_ms', 75)}ms - {cfg.get('typing_speed_max_ms', 170)}ms")
    print(f"5. Tryb ukrytej przeglądarki (Headless): {'Włączony (brak okna)' if cfg.get('headless', True) else 'Wyłączony (widać okno Chrome)'}")
    print("0. Wróć")

    choice = input("\nCo chcesz zmienić (1-5, 0=Wróć): ").strip()
    if choice == "1":
        acc = input("Podaj docelową skuteczność w % (np. 88-94): ").strip()
        if acc.replace(".", "").isdigit():
            cfg["target_accuracy_percent"] = float(acc)
    elif choice == "2":
        typo = input("Podaj szansę na literówkę w % (np. 5): ").strip()
        if typo.replace(".", "").isdigit():
            cfg["typo_chance_percent"] = float(typo)
    elif choice == "3":
        t1 = input("Minimalny czas czytania (s): ").strip()
        t2 = input("Maksymalny czas czytania (s): ").strip()
        if t1.replace(".", "").isdigit(): cfg["read_time_min_s"] = float(t1)
        if t2.replace(".", "").isdigit(): cfg["read_time_max_s"] = float(t2)
    elif choice == "4":
        s1 = input("Min opóźnienie klawisza (ms): ").strip()
        s2 = input("Max opóźnienie klawisza (ms): ").strip()
        if s1.isdigit(): cfg["typing_speed_min_ms"] = int(s1)
        if s2.isdigit(): cfg["typing_speed_max_ms"] = int(s2)
    elif choice == "5":
        cfg["headless"] = not cfg.get("headless", True)
        print(f"Zmieniono tryb okna na: {'Bez okna (Headless)' if cfg['headless'] else 'Z widocznym oknem'}")

    save_config(cfg)
    input("\nNaciśnij Enter, aby wrócić...")

def menu_view_words(storage: Storage):
    clear_screen()
    print_header()
    words = storage.words
    print(f"\n--- [5] BAZA ZAPAMIĘTANYCH SŁÓWEK (Łącznie: {len(words)}) ---")
    if not words:
        print("Baza słówek jest pusta. Bot nauczy się ich automatycznie podczas sesji!")
    else:
        print(f"{'ZAPYTANIE / POLSKI':<35} | {'POPRAWNA ODPOWIEDŹ':<25} | UŻYCIA")
        print("-" * 75)
        # Pokazujemy do 25 słówek
        items = list(words.items())[:25]
        for key, val in items:
            ans = val.get("answer", "")
            prompt = val.get("prompt", key)[:33]
            usage = val.get("usage_count", 1)
            print(f"{prompt:<35} | {ans:<25} | {usage}")
        if len(words) > 25:
            print(f"... oraz {len(words) - 25} innych słówek.")

    print("\nOpcje:")
    print("1. Wyczyść całą bazę słówek")
    print("0. Wróć")
    c = input("\nWybór: ").strip()
    if c == "1":
        conf = input("Czy na pewno chcesz usunąć wszystkie słówka? (tak/nie): ").strip().lower()
        if conf == "tak":
            storage.words = {}
            storage.save_words()
            print("[✓] Baza wyczyszczona.")

    input("\nNaciśnij Enter, aby wrócić...")

def menu_history(storage: Storage):
    clear_screen()
    print_header()
    history = storage.history
    print(f"\n--- [6] HISTORIA SESJI (Łącznie wpisów: {len(history)}) ---")
    if not history:
        print("Brak historii wykonanych sesji.")
    else:
        print(f"{'DATA I CZAS':<20} | {'STATUS':<10} | {'SŁÓWKA':<8} | {'TRAFIENIA':<10} | {'SKUTECZNOŚĆ':<12}")
        print("-" * 75)
        for h in history[-15:]:
            ts = h.get("timestamp", "")[:19].replace("T", " ")
            stat = "SUKCES" if h.get("success") else "BŁĄD"
            words = h.get("words_total", "-")
            corr = f"{h.get('words_correct', '-')}/{words}"
            acc = f"{h.get('accuracy_percent', '-')}%"
            print(f"{ts:<20} | {stat:<10} | {str(words):<8} | {corr:<10} | {acc:<12}")

    input("\nNaciśnij Enter, aby wrócić...")

def run_test_now(cfg):
    clear_screen()
    print_header()
    print("\n--- [7] TESTOWE URUCHOMIENIE SESJI NA ŻYWO ---")
    print("Zaraz nastąpi zalogowanie i wykonanie sesji InstaLing.")
    print("Upewnij się, że dane logowania są poprawne.\n")
    confirm = input("Uruchomić teraz? (t/n): ").strip().lower()
    if confirm in ["t", "tak", "y", "yes"]:
        bot = InstaLingBot(cfg)
        res = bot.run_session()
        print("\n" + "=" * 50)
        print("WYNIK KOŃCOWY:")
        print(res)
        print("=" * 50)
    input("\nNaciśnij Enter, aby wrócić...")

def show_main_menu():
    while True:
        cfg = load_config()
        storage = Storage()
        scheduler = Scheduler(cfg, storage)
        status = scheduler.check_execution_status()

        clear_screen()
        print_header()
        print(f" Dzisiaj: {status['weekday_name']}, {status['today']}")
        print(f" Dzień roboczy: {'TAK' if status['is_workday'] else 'NIE (Dzień wolny)'} | Dzisiaj ukończono: {'TAK' if status['is_done'] else 'NIE'}")
        print(f" Zaplanowana godzina: {status['planned_time']} | Wolne w tym tyg: {', '.join(status['off_days_this_week']) or 'Brak'}")
        print("=" * 60)
        print("\n [1] 🔑 Dane logowania (Login / Hasło)")
        print(" [2] ⏰ Tryb harmonogramu (Stała godzina / Losowe okna czasowe)")
        print(" [3] 🎲 Częstotliwość wypadków (Dni wolne w tygodniu)")
        print(" [4] 🛡️ Anty-detekcja (Skuteczność, pisanie, czas czytania)")
        print(" [5] 📚 Baza zapamiętanych słówek (Podgląd / Czyszczenie)")
        print(" [6] 📊 Historia sesji i statystyki")
        print(" [7] ▶️ Uruchom sesję teraz (Test na żywo)")
        print(" [8] 🌐 Uruchom Web Panel (Nowoczesny panel w przeglądarce)")
        print(" [9] ⏳ Uruchom Harmonogram w tle (Daemon na komputerze)")
        print(" [0] 🚪 Wyjście")

        choice = input("\nWybierz opcję (0-9): ").strip()
        if choice == "1":
            menu_credentials(cfg)
        elif choice == "2":
            menu_schedule(cfg)
        elif choice == "3":
            menu_missed_days(cfg)
        elif choice == "4":
            menu_anti_detection(cfg)
        elif choice == "5":
            menu_view_words(storage)
        elif choice == "6":
            menu_history(storage)
        elif choice == "7":
            run_test_now(cfg)
        elif choice == "8":
            print("\nUruchamianie serwera Web Panel...")
            from web_server import start_web_server
            start_web_server(port=5000)
            break
        elif choice == "9":
            print("\nUruchamianie pętli harmonogramu (Daemon)...")
            from daemon import run_daemon
            run_daemon()
            break
        elif choice == "0":
            print("\nDo widzenia!")
            sys.exit(0)

if __name__ == "__main__":
    show_main_menu()
