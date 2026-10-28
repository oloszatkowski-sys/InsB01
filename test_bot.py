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
        print(f"✅ [2/{total}] Konfiguracja: OK (Odstęp min_user_gap: {gap} min, limit słówek: {cfg.get('max_words_per_session')})")
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
        return True
    else:
        print(f"⚠️ OSTRZEŻENIE: Zliczono {passed}/{total} zaliczonych testów.")
        print("=" * 60)
        return False

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
