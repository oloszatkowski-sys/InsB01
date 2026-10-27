import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from datetime import datetime, date
from config import load_config, save_config, DEFAULT_CONFIG
from storage import Storage
from users_manager import UsersManager, mask_login
from multi_scheduler import MultiScheduler, DAY_NAMES_PL
from bot import InstaLingBot
from timezone_utils import now_warsaw, today_warsaw, format_warsaw, get_current_polish_tzname

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def print_header(plan=None):
    print("=" * 68)
    print("         🤖 INSTALING AUTO-BOT - PANEL MULTI-USER (POLSKA)       ")
    print("=" * 68)
    now_pl = now_warsaw()
    today_pl = today_warsaw()
    weekday_pl = DAY_NAMES_PL[today_pl.weekday()]
    print(f" 🇵🇱 Dzisiaj: {weekday_pl}, {today_pl.isoformat()} | {now_pl.strftime('%H:%M:%S')} {get_current_polish_tzname()} (Europe/Warsaw)")

    if plan:
        print(" Harmonogram na dziś (Zsynchronizowany z Discordem):")
        for p in plan:
            nick = p.get("nickname", "Uczeń")
            mask = mask_login(p.get("login", ""))
            t = p.get("scheduled_time", "--:--")
            is_off = p.get("is_off_day", False)
            completed = p.get("completed", False)
            comp_at = p.get("completed_at")
            acc = p.get("accuracy_percent")

            if is_off:
                print(f"  • {nick} ({mask}): 🏖️ Dzień wolny | Status: Dzień wolny")
            elif completed:
                fin_str = comp_at[11:16] if comp_at and len(comp_at) >= 16 else "Tak"
                acc_str = f" ({acc}%)" if acc is not None else ""
                print(f"  • {nick} ({mask}): ✅ {t} | Status: UKOŃCZONO o {fin_str}{acc_str}")
            elif p.get("status") == "W trakcie":
                print(f"  • {nick} ({mask}): ▶️ {t} | Status: W TRAKCIE...")
            elif p.get("status") == "Błąd":
                print(f"  • {nick} ({mask}): ⚠️ {t} | Status: BŁĄD SESJI")
            else:
                print(f"  • {nick} ({mask}): ⏰ {t} | Status: ⏳ Oczekuje")
    print("=" * 68)

def menu_users(users_mgr: UsersManager, sched: MultiScheduler):
    while True:
        clear_screen()
        print_header()
        print("\n--- [1] ZARZĄDZANIE UŻYTKOWNIKAMI (PROFILE) ---")
        users = users_mgr.get_users()
        if not users:
            print("Brak dodanych użytkowników.")
        else:
            print(f"{'NR':<3} | {'PSEUDONIM':<18} | {'LOGIN':<12} | {'STATUS':<10} | {'TELEFON (ntfy)':<14}")
            print("-" * 65)
            for i, u in enumerate(users):
                st = "Aktywny" if u.get("active", True) else "Wyłączony"
                nt = "✅ TAK" if u.get("track_in_ntfy", False) else "NIE"
                print(f"{i+1:<3} | {u.get('nickname', ''):<18} | {mask_login(u.get('login', '')):<12} | {st:<10} | {nt:<14}")

        print("\nOpcje:")
        print("1. Dodaj nowego użytkownika")
        print("2. Edytuj dane użytkownika (login / hasło / pseudonim)")
        print("3. Przełącz powiadomienia na telefon (ntfy.sh) dla konta")
        print("4. Włącz / Wyłącz profil")
        print("5. Usuń profil")
        print("0. Wróć do menu głównego")

        ch = input("\nWybór (0-5): ").strip()
        if ch == "1":
            nick = input("Podaj pseudonim (np. SZATEK-02): ").strip()
            login = input("Podaj login InstaLing (np. asa123456): ").strip()
            pwd = input("Podaj hasło InstaLing: ").strip()
            if nick and login and pwd:
                users.append({
                    "id": f"user_{len(users)+1}",
                    "nickname": nick,
                    "login": login,
                    "password": pwd,
                    "active": True,
                    "created_at": date.today().isoformat(),
                    "track_in_ntfy": False
                })
                users_mgr.save_users(users)
                sched.get_or_create_weekly_schedule(force_new=True)
                sched.publish_weekly_plan_to_discord()
                sched.publish_today_plan_to_discord()
                print("\n[OK] Dodano użytkownika i zaktualizowano plan na Discordzie!")
                time.sleep(1.5)
        elif ch == "2":
            idx = input("Podaj numer użytkownika do edycji: ").strip()
            if idx.isdigit() and 1 <= int(idx) <= len(users):
                u = users[int(idx) - 1]
                print(f"\nEdycja użytkownika: {u.get('nickname')}")
                new_nick = input(f"Nowy pseudonim (Enter aby zachować '{u.get('nickname')}'): ").strip()
                if new_nick: u["nickname"] = new_nick
                new_login = input(f"Nowy login (Enter aby zachować '{u.get('login')}'): ").strip()
                if new_login: u["login"] = new_login
                new_pass = input("Nowe hasło (Enter aby zachować): ").strip()
                if new_pass: u["password"] = new_pass
                users_mgr.save_users(users)
                sched.get_or_create_weekly_schedule(force_new=True)
                sched.publish_weekly_plan_to_discord()
                sched.publish_today_plan_to_discord()
                print("\n[OK] Zapisano zmiany i zaktualizowano Discord!")
                time.sleep(1.5)
        elif ch == "3":
            idx = input("Podaj numer użytkownika do ntfy.sh (tylko 1 może mieć telefon): ").strip()
            if idx.isdigit() and 1 <= int(idx) <= len(users):
                sel_idx = int(idx) - 1
                for i, u in enumerate(users):
                    u["track_in_ntfy"] = (i == sel_idx)
                users_mgr.save_users(users)
                print(f"\n[OK] Powiadomienia na telefon ntfy.sh ustawiono dla: {users[sel_idx].get('nickname')}")
                time.sleep(1.5)
        elif ch == "4":
            idx = input("Podaj numer użytkownika: ").strip()
            if idx.isdigit() and 1 <= int(idx) <= len(users):
                u = users[int(idx) - 1]
                u["active"] = not u.get("active", True)
                users_mgr.save_users(users)
                sched.get_or_create_weekly_schedule(force_new=True)
                sched.publish_today_plan_to_discord()
                print(f"\n[OK] Zmieniono status aktywności.")
                time.sleep(1.5)
        elif ch == "5":
            idx = input("Podaj numer użytkownika do usunięcia: ").strip()
            if idx.isdigit() and 1 <= int(idx) <= len(users):
                deleted = users.pop(int(idx) - 1)
                users_mgr.save_users(users)
                sched.get_or_create_weekly_schedule(force_new=True)
                sched.publish_today_plan_to_discord()
                print(f"\n[OK] Usunięto użytkownika {deleted.get('nickname')}.")
                time.sleep(1.5)
        elif ch == "0":
            break

def menu_schedule(cfg, sched: MultiScheduler):
    clear_screen()
    print_header()
    print("\n--- [2] TRYB HARMONOGRAMU (GODZINY I OKNO CZASOWE) ---")
    print(f"Aktualne okno losowania sesji: {cfg.get('random_window_start', '15:46')} - {cfg.get('random_window_end', '21:57')}")
    print("Wszystkie sesje użytkowników są rozkładane w tym oknie z odstępem min. 15 minut (Zero Kolizji).\n")

    w_start = input(f"Podaj początek okna (Enter aby zachować '{cfg.get('random_window_start')}'): ").strip()
    if w_start: cfg["random_window_start"] = w_start

    w_end = input(f"Podaj koniec okna (Enter aby zachować '{cfg.get('random_window_end')}'): ").strip()
    if w_end: cfg["random_window_end"] = w_end

    save_config(cfg)
    sched.get_or_create_weekly_schedule(force_new=True)
    sched.publish_weekly_plan_to_discord()
    sched.publish_today_plan_to_discord()
    print("\n[OK] Zaktualizowano okno czasowe i wygenerowano nowy spójny plan na Discordzie!")
    input("\nNaciśnij Enter, aby wrócić...")

def menu_missed_days(cfg, sched: MultiScheduler):
    clear_screen()
    print_header()
    print("\n--- [3] DNI WOLNE W TYGODNIU (ANTY-DETEKCJA) ---")
    print(f"Aktualny tryb: {cfg.get('miss_days_mode', 'none')}")
    print(f"Liczba dni wolnych w tygodniu na profil: {cfg.get('miss_days_count', 0)}")
    print("\nOpcje:")
    print("1. Codziennie (0 dni wolnych - 100% systematyczności)")
    print("2. Losowo 1 dzień wolny w tygodniu (dla każdego ucznia osobno)")
    print("3. Losowo 2 dni wolne w tygodniu")
    print("0. Wróć")

    c = input("\nWybór: ").strip()
    if c == "1":
        cfg["miss_days_mode"] = "none"
        cfg["miss_days_count"] = 0
    elif c == "2":
        cfg["miss_days_mode"] = "random"
        cfg["miss_days_count"] = 1
    elif c == "3":
        cfg["miss_days_mode"] = "random"
        cfg["miss_days_count"] = 2

    save_config(cfg)
    sched.get_or_create_weekly_schedule(force_new=True)
    sched.publish_weekly_plan_to_discord()
    sched.publish_today_plan_to_discord()
    print("\n[OK] Zapisano i zaktualizowano plan na Discordzie!")
    input("\nNaciśnij Enter, aby wrócić...")

def menu_anti_detection(cfg):
    clear_screen()
    print_header()
    print("\n--- [4] PARAMETRY ANTY-DETEKCJI I PISANIA ---")
    print(f"• Docelowa skuteczność ucznia: {cfg.get('target_accuracy_percent', 78)}%")
    print(f"• Szansa na literówkę i Backspace: {cfg.get('typo_chance_percent', 3)}%")
    print(f"• Prędkość wciskania klawiszy: {cfg.get('typing_speed_min_ms', 75)} - {cfg.get('typing_speed_max_ms', 170)} ms")
    print(f"• Czas namysłu nad zdaniem: {cfg.get('read_time_min_s', 0.25)} - {cfg.get('read_time_max_s', 5.0)} s")
    print("• Wpisywanie: 100% klawisz po klawiszu (brak schowka/Ctrl+V)\n")

    acc = input("Podaj docelową skuteczność w % (np. 80, Enter aby zachować): ").strip()
    if acc: cfg["target_accuracy_percent"] = float(acc)

    save_config(cfg)
    print("\n[OK] Zapisano ustawienia anty-detekcji.")
    input("\nNaciśnij Enter, aby wrócić...")

def menu_view_words(storage: Storage):
    clear_screen()
    print_header()
    print(f"\n--- [5] BAZA ZAPAMIĘTANYCH SŁÓWEK ({len(storage.words)} słówek) ---")
    if not storage.words:
        print("Baza słówek jest pusta.")
    else:
        for i, (k, v) in enumerate(list(storage.words.items())[:30]):
            prompt = v.get("prompt", k)
            ans = v.get("answer", "")
            print(f"  {i+1}. {prompt} -> {ans}")
        if len(storage.words) > 30:
            print(f"  ... i {len(storage.words) - 30} innych słówek.")

    print("\nOpcje: [1] Wyczyść bazę słówek | [Enter] Wróć")
    c = input("Wybór: ").strip()
    if c == "1":
        storage.clear_words()
        print("[OK] Wyczyszczono bazę słówek.")
        time.sleep(1.0)

def menu_history(storage: Storage):
    clear_screen()
    print_header()
    print("\n--- [6] HISTORIA SESJI ---")
    history = storage.history
    if not history:
        print("Brak historii wykonanych sesji.")
    else:
        print(f"{'DATA':<19} | {'UCZEŃ':<15} | {'STATUS':<8} | {'TRAFIENIA':<10} | {'SKUTECZNOŚĆ':<12}")
        print("-" * 75)
        for h in history[-15:]:
            ts = h.get("finished_at", h.get("timestamp", ""))[:19].replace("T", " ")
            nick = h.get("nickname", "Uczeń")
            stat = "SUKCES" if h.get("success") else "BŁĄD"
            corr = f"{h.get('words_correct', '-')}/{h.get('words_total', '-')}"
            acc = f"{h.get('accuracy_percent', '-')}%"
            print(f"{ts:<19} | {nick:<15} | {stat:<8} | {corr:<10} | {acc:<12}")

    input("\nNaciśnij Enter, aby wrócić...")

def run_test_now(cfg, users_mgr: UsersManager, sched: MultiScheduler):
    clear_screen()
    print_header()
    print("\n--- [7] URUCHOMIENIE SESJI NA ŻYWO ---")
    users = users_mgr.get_active_users()
    if not users:
        print("Brak aktywnych użytkowników!")
        input("\nNaciśnij Enter...")
        return

    print("Dostępni użytkownicy:")
    for i, u in enumerate(users):
        print(f"  [{i+1}] {u.get('nickname')} ({mask_login(u.get('login'))})")
    print("  [A] Uruchom wszystkich po kolei (Kolejka)")
    print("  [0] Anuluj")

    c = input("\nWybór: ").strip().lower()
    bot = InstaLingBot(cfg)

    if c == "a":
        for i, u in enumerate(users):
            nick = u.get("nickname", "Uczeń")
            print(f"\n[*] Uruchamiam sesję dla {nick}...")
            res = sched.run_single_user(nick, trigger_reason="uruchomienie z menu")
            if i < len(users) - 1:
                print("[*] Odczekanie 20s przed kolejnym kontem...")
                time.sleep(20)
    elif c.isdigit() and 1 <= int(c) <= len(users):
        target_u = users[int(c) - 1]
        nick = target_u.get("nickname", "Uczeń")
        print(f"\n[*] Uruchamiam sesję dla {nick}...")
        res = sched.run_single_user(nick, trigger_reason="uruchomienie z menu")

    input("\nNaciśnij Enter, aby wrócić...")

def show_main_menu():
    while True:
        cfg = load_config()
        storage = Storage()
        users_mgr = UsersManager()
        sched = MultiScheduler(cfg)
        plan = sched.get_today_slots()

        clear_screen()
        print_header(plan)
        print("\n [1] 👥 Zarządzanie użytkownikami (Profile / Loginy / Hasła)")
        print(" [2] ⏰ Okno godzinowe harmonogramu (Wspólne dla wszystkich)")
        print(" [3] 🎲 Częstotliwość dni wolnych (Anty-detekcja)")
        print(" [4] 🛡️ Parametry pisania i anty-detekcji")
        print(" [5] 📚 Baza zapamiętanych słówek")
        print(" [6] 📊 Historia sesji i statystyki")
        print(" [7] ▶️ Uruchom sesję teraz (Test na żywo)")
        print(" [8] 🌐 Uruchom Web Panel w przeglądarce")
        print(" [9] ⏳ Uruchom Harmonogram w tle (Daemon na komputerze)")
        print(" [P] 📢 Wyślij świeży Plan na Dziś i Tydzień na Discorda")
        print(" [R] 🔄 Zresetuj i wylosuj nowy Plan Tygodnia (Reset)")
        print(" [0] 🚪 Wyjście")

        choice = input("\nWybierz opcję: ").strip().lower()
        if choice == "1":
            menu_users(users_mgr, sched)
        elif choice == "2":
            menu_schedule(cfg, sched)
        elif choice == "3":
            menu_missed_days(cfg, sched)
        elif choice == "4":
            menu_anti_detection(cfg)
        elif choice == "5":
            menu_view_words(storage)
        elif choice == "6":
            menu_history(storage)
        elif choice == "7":
            run_test_now(cfg, users_mgr, sched)
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
        elif choice == "p":
            print("\nWysyłam zsynchronizowany plan na Discorda...")
            sched.publish_weekly_plan_to_discord()
            sched.publish_today_plan_to_discord()
            print("[OK] Wysłano na Discorda!")
            time.sleep(1.5)
        elif choice == "r":
            conf = input("\nCzy na pewno chcesz zresetować i wylosować od nowa Plan Tygodnia? (t/n): ").strip().lower()
            if conf in ["t", "tak", "y", "yes"]:
                print("\n[*] Resetowanie harmonogramu...")
                sched.reset_schedule()
                sched.publish_weekly_plan_to_discord()
                sched.publish_today_plan_to_discord()
                print("[OK] Wygenerowano nowy plan tygodnia i wysłano na Discorda!")
                time.sleep(2.0)
        elif choice == "0":
            print("\nDo widzenia!")
            sys.exit(0)

if __name__ == "__main__":
    show_main_menu()
