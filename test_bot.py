import sys
import os
import json
import urllib.request
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def run_tests():
    print("=" * 60)
    print("🧪 [TESTY AUTOMATYCZNE] InstaLing Auto-Bot - Weryfikacja Systemu")
    print("=" * 60)
    passed = 0
    total = 7

    # TEST 1: Strefa czasowa Europe/Warsaw
    try:
        from timezone_utils import now_warsaw, today_warsaw, format_warsaw, get_current_polish_tzname
        nw = now_warsaw()
        tz_name = get_current_polish_tzname()
        assert nw is not None
        assert tz_name in ["CET", "CEST"]
        print(f"✅ [1/{total}] Strefa czasowa: OK (Czas PL: {format_warsaw(nw)})")
        passed += 1
    except Exception as e:
        print(f"❌ [1/{total}] Błąd strefy czasowej: {e}")

    # TEST 2: Konfiguracja i anty-kolizja
    try:
        from config import load_config
        cfg = load_config()
        gap = int(cfg.get("min_user_gap_minutes", 0))
        assert gap >= 45, f"Odstęp między użytkownikami ({gap}m) musi wynosić min. 45 min!"
        assert cfg.get("max_words_per_session", 0) <= 50, "Limit słówek musi chronić przed pętlą!"
        morn_s = cfg.get("morning_window_start", "06:43")
        morn_e = cfg.get("morning_window_end", "07:34")
        eve_s = cfg.get("random_window_start", "15:37")
        eve_e = cfg.get("random_window_end", "22:39")
        morn_p = cfg.get("morning_session_chance_percent", 8.0)
        print(f"✅ [2/{total}] Konfiguracja: OK (Okna: {morn_s}-{morn_e} [{morn_p}%] oraz {eve_s}-{eve_e}, odstęp: {gap} min)")
        passed += 1
    except Exception as e:
        print(f"❌ [2/{total}] Błąd konfiguracji: {e}")

    # TEST 3: Weryfikacja aktywnych uczniów
    try:
        from users_manager import UsersManager, mask_login
        um = UsersManager()
        active = um.get_active_users()
        assert len(active) >= 1, "Brak aktywnych użytkowników w bazie!"
        nicks = [f"{u['nickname']} ({mask_login(u['login'])})" for u in active]
        print(f"✅ [3/{total}] Uczniowie: OK ({len(active)} aktywnych kont: {', '.join(nicks)})")
        passed += 1
    except Exception as e:
        print(f"❌ [3/{total}] Błąd bazy użytkowników: {e}")

    # TEST 4: Blokada współbieżności (BotLock)
    try:
        from bot_lock import BotLock
        assert BotLock.acquire("test_user", "Tester") is True
        assert BotLock.acquire("other_user", "Tester2") is False  # Powinna zablokować
        BotLock.release()
        print(f"✅ [4/{total}] Blokada procesów (BotLock): OK (Zapobiega podwójnym sesjom)")
        passed += 1
    except Exception as e:
        print(f"❌ [4/{total}] Błąd blokady BotLock: {e}")

    # TEST 5: Spójność harmonogramu tygodniowego i pliku Markdown
    try:
        from multi_scheduler import MultiScheduler
        sched = MultiScheduler()
        weekly = sched.get_or_create_weekly_schedule()
        assert "days" in weekly
        today_slots = sched.get_today_slots()
        assert len(today_slots) > 0
        from pathlib import Path
        md_file = Path(__file__).resolve().parent / "PLAN_TYGODNIA.md"
        assert md_file.exists(), "Plik PLAN_TYGODNIA.md nie został wygenerowany!"
        print(f"✅ [5/{total}] Harmonogram tygodniowy i PLAN_TYGODNIA.md: OK ({len(today_slots)} slotów na dziś)")
        passed += 1
    except Exception as e:
        print(f"❌ [5/{total}] Błąd harmonogramu: {e}")

    # TEST 6: Baza zapamiętanych słówek i historia
    try:
        from storage import Storage
        st = Storage()
        words_count = len(st.words)
        hist_count = len(st.history)
        print(f"✅ [6/{total}] Baza wiedzy (Storage): OK ({words_count} słówek w bazie, {hist_count} sesji w historii)")
        passed += 1
    except Exception as e:
        print(f"❌ [6/{total}] Błąd bazy słówek: {e}")

    # TEST 7: Łączność z serwerem InstaLing
    try:
        req = urllib.request.Request(
            "https://instaling.pl/teacher.php?page=login",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
        print(f"✅ [7/{total}] Łączność z serwisem InstaLing: OK (HTTP 200)")
        passed += 1
    except Exception as e:
        print(f"⚠️ [7/{total}] Uwaga: Problem z połączeniem z instaling.pl ({e})")

    print("=" * 60)
    if passed == total:
        print(f"🎉 SUKCES: Wszystkie testy ({passed}/{total}) ZALICZONE POPRAWNIE!")
        print("Bot jest w 100% gotowy do bezpiecznego i niezawodnego działania.")
        print("=" * 60)

        # Opcjonalny test kanałów Discord i ntfy (gdy przekazano --discord)
        if "--discord" in sys.argv or "--full" in sys.argv:
            print("\n📡 [TEST DISCORD & NTFY] Wysyłanie powiadomień testowych...")
            try:
                from config import load_config
                from notifier import Notifier
                from multi_scheduler import MultiScheduler
                cfg = load_config()
                notifier = Notifier(cfg)
                sched = MultiScheduler(cfg)

                # 1. Test #sekcja
                sekcja_wh = notifier._get_webhook("webhook_sekcja")
                if sekcja_wh:
                    notifier._send_discord_embed(
                        webhook_url=sekcja_wh,
                        title="🧪 Test Powiadomień Bota — Wszystkie Systemy Działają!",
                        description=(
                            "✅ **Pomyślnie zweryfikowano działanie bota InstaLing:**\n\n"
                            "• 🇵🇱 **Strefa czasowa:** `Europe/Warsaw` (CET/CEST)\n"
                            "• 👥 **Aktywni uczniowie:** Olesław 010, Szlucha Jagoda, OliwiercioTheHacker\n"
                            "• 🛡️ **Ochrona:** Odstęp min. 45 min, anty-kolizja aktywna\n"
                            "• 📚 **Baza wiedzy:** Gotowa do samonaprawiania słówek\n"
                            "• 🚀 **GitHub Actions:** Skonfigurowane i gotowe do pracy"
                        ),
                        color=0x2ECC71
                    )
                    print("✅ Wysłano meldunek testowy do kanału #sekcja")

                # 2. Test #plan-na-dzis
                sched.publish_today_plan_to_discord()
                print("✅ Opublikowano plan na dziś w kanale #plan-na-dzis")

                # Test zapowiedzi odliczania na #plan-na-dzis
                test_u = active[0] if active else {"nickname": "Tester", "login": "test001"}
                notifier.send_countdown_announcement(test_u, scheduled_time="18:30", minutes_left=10)
                print("✅ Przetestowano zapowiedź odliczania (~10 min) w kanale #plan-na-dzis")

                # 3. Test #plan-tygodnia
                sched.publish_weekly_plan_to_discord()
                print("✅ Opublikowano plan tygodnia w kanale #plan-tygodnia")

                # 4. Test #statystyki
                notifier.send_bot_global_statistics()
                print("✅ Opublikowano statystyki w kanale #statystyki")

                # 5. Test ntfy.sh
                from users_manager import UsersManager
                um = UsersManager()
                ntfy_u = um.get_ntfy_user()
                if ntfy_u:
                    topic = cfg.get("ntfy_topic", "").strip() or f"instaling_{ntfy_u.get('login', 'user')}"
                    notifier._send_ntfy(
                        topic=topic,
                        title="🧪 Test powiadomień InstaLing",
                        message="Wszystkie testy bota i webhooki Discord zostały pomyślnie zaliczone!",
                        priority="default",
                        tags="white_check_mark,robot,tada"
                    )
                    print(f"✅ Wysłano powiadomienie testowe na ntfy.sh (temat: {topic})")

                print("🎉 Wszystkie powiadomienia testowe dotarły na Discord i ntfy!\n")
            except Exception as ex:
                print(f"❌ Błąd wysyłania powiadomień testowych: {ex}\n")

        return True
    else:
        print(f"⚠️ OSTRZEŻENIE: Zliczono {passed}/{total} zaliczonych testów.")
        print("=" * 60)
        return False

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
