import sys
import time
import random
from datetime import datetime
from typing import Dict, Any, Optional, List
from config import load_config
from storage import Storage
from solver import InstaLingSolver
from notifier import Notifier
from logger import log
from users_manager import UsersManager, mask_login
from timezone_utils import now_warsaw, format_warsaw, now_utc, format_utc

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

INSTALING_LOGIN_URL = "https://instaling.pl/teacher.php?page=login"

class InstaLingBot:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()
        self.storage = Storage()
        self.notifier = Notifier(self.config)
        self.users_mgr = UsersManager()

    def run_session(self, user: Optional[Dict[str, Any]] = None, scheduled_time: Optional[str] = None) -> Dict[str, Any]:
        """Uruchamia pełną sesję dla wybranego użytkownika (lub domyślnego)."""
        if not user:
            user = self.users_mgr.get_ntfy_user()
            if not user:
                user = {
                    "nickname": "Główny",
                    "login": self.config.get("login", ""),
                    "password": self.config.get("password", ""),
                    "track_in_ntfy": True
                }

        nickname = user.get("nickname", "Uczeń")
        login = str(user.get("login", "")).strip()
        password = str(user.get("password", "")).strip()
        masked = mask_login(login)

        if not login or not password:
            return {
                "success": False,
                "error": f"Brak danych logowania dla {nickname} (login/hasło puste)."
            }

        start_dt = now_warsaw()
        start_epoch = time.time()
        headless = bool(self.config.get("headless", True))
        mute_audio = bool(self.config.get("mute_audio", True))
        # Zabezpieczenie przed zbyt dużą liczbą iteracji
        max_words = min(int(self.config.get("max_words_per_session", 45)), 50)
        session_logs: List[str] = []

        def track_log(msg: str):
            now_str = now_warsaw().strftime("%H:%M:%S")
            formatted = f"[{now_str}] {msg}"
            log(formatted)
            session_logs.append(formatted)

        track_log(f"🚀 [START] Rozpoczęcie procedury sesji dla ucznia: {nickname} (login: {masked})")
        track_log(f"⚙️ [KONFIGURACJA] Headless={headless}, wyciszenie dźwięku={mute_audio}, limit słówek={max_words}")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {
                "success": False,
                "error": "Biblioteka Playwright nie jest zainstalowana."
            }

        with sync_playwright() as p:
            args = []
            if mute_audio:
                args.append("--mute-audio")

            browser = p.chromium.launch(
                headless=headless,
                args=args
            )
            track_log(f"🌐 [PRZEGLĄDARKA] Uruchomiono silnik Chromium (wersja standardowa, locale=pl-PL)")
            
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="pl-PL"
            )
            page = context.new_page()

            # Skrypt automatycznie usuwający baner RODO co 200ms na każdej podstronie
            page.add_init_script("""
                setInterval(() => {
                    document.querySelectorAll('.fc-consent-root, .fc-dialog-overlay, .fc-dialog-container').forEach(e => e.remove());
                }, 200);
            """)
            track_log("🛡️ [FILTR] Aktywowano skrypt blokujący wyskakujące banery zgód RODO/Cookies")

            try:
                # ==============================
                # 1. WEJŚCIE NA STRONĘ LOGOWANIA
                # ==============================
                track_log(f"🔗 [NAWIGACJA] Łączenie z adresem logowania: {INSTALING_LOGIN_URL}")
                t_nav_start = time.time()
                resp = page.goto(INSTALING_LOGIN_URL, timeout=40000)
                page.wait_for_load_state("domcontentloaded")
                status_code = resp.status if resp else "200"
                nav_time = time.time() - t_nav_start
                track_log(f"📡 [SERWER] Strona logowania wczytana pomyślnie (kod HTTP {status_code}, czas: {nav_time:.2f}s)")
                time.sleep(1.5)

                # ==============================
                # 2. LOGOWANIE
                # ==============================
                track_log(f"🔑 [LOGOWANIE] Wprowadzanie identyfikatora ucznia: '{masked}'")
                login_input = page.locator("input#log_email").first
                login_input.fill(login)
                time.sleep(random.uniform(0.3, 0.6))

                track_log("🔒 [LOGOWANIE] Wprowadzanie hasła użytkownika (znaki ukryte)")
                pass_input = page.locator("input#log_password").first
                pass_input.fill(password)
                time.sleep(random.uniform(0.3, 0.6))

                track_log("🖱️ [LOGOWANIE] Kliknięcie przycisku 'ZALOGUJ' i oczekiwanie na autoryzację...")
                submit_btn = page.locator('button:has-text("ZALOGUJ")').first
                submit_btn.click(force=True)
                time.sleep(3.0)

                # ==============================
                # 3. WERYFIKACJA ZALOGOWANIA
                # ==============================
                current_url = page.url
                if "page=login" in current_url and "student" not in current_url:
                    error_msg = page.locator(".alert-danger, .error-message, #error_box").all_inner_texts()
                    err_txt = " | ".join(error_msg) if error_msg else "Niepoprawny login lub hasło."
                    track_log(f"❌ [BŁĄD LOGOWANIA] Odrzucono poświadczenia dla {nickname}: {err_txt}")
                    res = {"success": False, "error": f"Błąd logowania dla {nickname}: {err_txt}"}
                    self.notifier.send_session_summary(res, user, session_logs)
                    return res

                track_log(f"✅ [AUTORYZACJA] Zalogowano pomyślnie jako {nickname}! (Adres URL: {current_url})")

                # ==============================
                # 4. WEJŚCIE DO SESJI Z PANELU
                # ==============================
                track_log("🔍 [PANEL] Wyszukiwanie kafelka codziennej sesji na pulpicie ucznia...")
                session_btn = page.locator("a.btn-start-session, a:has-text('Dokończ sesję'), a:has-text('Zacznij codzienną sesję'), a:has-text('Zacznij sesję')").first
                if session_btn.count() == 0 or not session_btn.is_visible():
                    page_text = page.inner_text("body")
                    if "Wykonałeś już dzisiejszą sesję" in page_text or "sesja wykonana" in page_text.lower():
                        track_log(f"ℹ️ [PANEL] Informacja z systemu: {nickname} wykonał już dzisiejszą sesję wcześniej!")
                        res = {
                            "success": True,
                            "already_completed": True,
                            "message": f"Dzisiejsza sesja {nickname} była już ukończona."
                        }
                        self.notifier.send_session_summary(res, user, session_logs)
                        return res
                    track_log("❌ [PANEL] Nie odnaleziono aktywnego przycisku sesji na stronie głównej.")
                    res = {"success": False, "error": "Nie znaleziono przycisku startu sesji na stronie głównej."}
                    self.notifier.send_session_summary(res, user, session_logs)
                    return res

                track_log("▶️ [PANEL] Przycisk sesji aktywny — otwieranie formularza zadań...")
                session_btn.click()
                time.sleep(2.5)

                # ==============================
                # 5. EKRAN STARTOWY SESJI (Kontynuuj / Rozpocznij)
                # ==============================
                cont_btn = page.get_by_text("Kontynuuj sesję").first
                if cont_btn.count() > 0 and cont_btn.is_visible():
                    track_log("🔘 [SESJA] Wykryto przerwaną sesję — klikam 'Kontynuuj sesję'")
                    cont_btn.click(force=True)
                    time.sleep(2.0)

                start_btn = page.get_by_text("Rozpocznij sesję").first
                if start_btn.count() > 0 and start_btn.is_visible():
                    track_log("🔘 [SESJA] Ekran gotowości — klikam 'Rozpocznij sesję'")
                    start_btn.click(force=True)
                    time.sleep(2.0)

                # ==============================
                # 6. PĘTLA ROZWIĄZYWANIA SŁÓWEK
                # ==============================
                track_log("📚 [SESJA] Formularz zadań załadowany — start modułu rozwiązywania słówek InstaLing...")
                solver = InstaLingSolver(page, self.config, self.storage, log_fn=track_log)

                iterations = 0
                MAX_SESSION_SEC = 420  # 7 minut twardego limitu na sesję

                while iterations < max_words:
                    iterations += 1
                    time.sleep(random.uniform(0.6, 1.2))

                    # Zabezpieczenie przed zbyt długim działaniem
                    if (time.time() - start_epoch) > MAX_SESSION_SEC:
                        track_log(f"[!] Przekroczono limit czasu sesji ({MAX_SESSION_SEC}s). Bezpieczne zakończenie sesji.")
                        break

                    if solver.is_session_finished():
                        track_log(f"[+] [{nickname}] Sesja ukonczona pomyslnie! Gratulacje!")
                        break

                    handled = solver.handle_single_word()
                    if not handled:
                        time.sleep(2.0)
                        if solver.is_session_finished():
                            track_log(f"[+] [{nickname}] Sesja ukonczona!")
                            break
                        track_log(f"[i] [{nickname}] Zakonczono pytania w tej sesji.")
                        break

                # ==============================
                # 7. POWRÓT NA STRONĘ GŁÓWNĄ I WYLOGOWANIE
                # ==============================
                time.sleep(random.uniform(2.0, 3.5))

                # Krok A: Powrót na stronę główną
                try:
                    home_btn = page.locator("a:has-text('Wróć do strony głównej'), a:has-text('Strona główna'), a.btn-return, a[href*='mainPage']").first
                    if home_btn.count() > 0 and home_btn.is_visible():
                        track_log(f"🏠 [POWRÓT] Kliknięcie powrotu do strony głównej ucznia...")
                        home_btn.click(force=True)
                        time.sleep(random.uniform(2.0, 3.0))
                        track_log(f"✅ [POWRÓT] Pomyślnie powrócono do pulpitu głównego.")
                except Exception:
                    pass

                # Krok B: Wylogowanie
                try:
                    logout_btn = page.locator("a:has-text('Wyloguj'), a[href*='logout']").first
                    if logout_btn.count() > 0 and logout_btn.is_visible():
                        track_log(f"🚪 [WYLOGOWANIE] Kliknięcie 'Wyloguj' na koncie {nickname}...")
                        logout_btn.click(force=True)
                        time.sleep(1.5)
                        track_log(f"✅ [WYLOGOWANIE] Pomyślnie wylogowano. Sesja została bezpiecznie zamknięta.")
                except Exception:
                    pass

                end_dt = now_warsaw()
                duration_s = (end_dt - start_dt).total_seconds()
                total = solver.session_words_count
                correct = solver.session_correct_count
                mistakes = solver.session_mistakes_count
                acc = round((correct / total * 100), 1) if total > 0 else 0.0
                new_words_count = len({
                    w.get("prompt", "").strip()
                    for w in solver.resolved_words
                    if w.get("status") == "nowe" and w.get("prompt", "").strip()
                })
                autocorrect_count = len({
                    w.get("prompt", "").strip()
                    for w in solver.resolved_words
                    if w.get("status") == "autokorekta" and w.get("prompt", "").strip()
                })

                track_log(f"🏁 [STATYSTYKA KOŃCOWA] Rozwiązano łącznie: {total} pytań | Poprawne: {correct} ({acc}%) | Błędy: {mistakes}")
                track_log(f"🆕 [NOWE SŁÓWKA] Wykryto i zapamiętano: {new_words_count} nowych słówek")
                track_log(f"⏱️ [CZAS SESJI] Całkowity czas od zalogowania do wylogowania: {duration_s:.1f}s (~{duration_s/60:.1f} min)")

                result = {
                    "success": True,
                    "nickname": nickname,
                    "masked_login": masked,
                    "scheduled_time": scheduled_time or start_dt.strftime("%H:%M"),
                    "words_total": total,
                    "words_correct": correct,
                    "words_mistakes": mistakes,
                    "new_words_count": new_words_count,
                    "autocorrect_count": autocorrect_count,
                    "accuracy_percent": acc,
                    "duration_seconds": round(duration_s, 1),
                    "started_at_warsaw": format_warsaw(start_dt),
                    "completed_at_warsaw": format_warsaw(end_dt),
                    "finished_at": end_dt.isoformat(),
                    "words_details": solver.resolved_words
                }

                self.storage.record_session(result)
                track_log(f"\n[OK] SESJA DLA {nickname} ({masked}) ZAKONCZONA SUKCESEM!")
                track_log(f"    Czas: {format_warsaw(start_dt)} -> {format_warsaw(end_dt)} ({duration_s:.1f}s)")
                track_log(f"    Rozwiazano: {total} | Poprawne: {correct} ({acc}%)\n")

                if solver.resolved_words:
                    track_log("📚 SŁÓWKA ROZWIĄZANE W TEJ SESJI:")
                    for idx, w in enumerate(solver.resolved_words):
                        st = w.get("status", "")
                        tag = "✅ POPRAWNIE" if st == "poprawnie" else ("🆕 NOWE ZAPAMIĘTANO" if st == "nowe" else ("🔄 AUTOKOREKTA" if st == "autokorekta" else "⚠️ BŁĄD"))
                        track_log(f"  {idx+1:2d}. {w['prompt']} ➔ {w['answer']} [{tag}]")
                    track_log("")

                # Wysyłamy powiadomienie z podziałem na kanały Discord i ntfy
                self.notifier.send_session_summary(result, user, session_logs)
                return result

            except Exception as e:
                err_str = str(e)
                end_dt = now_warsaw()
                duration_s = (end_dt - start_dt).total_seconds()
                track_log(f"[!] Blad w trakcie wykonywania sesji dla {nickname}: {err_str}")
                result = {
                    "success": False,
                    "nickname": nickname,
                    "masked_login": masked,
                    "scheduled_time": scheduled_time or start_dt.strftime("%H:%M"),
                    "error": err_str,
                    "duration_seconds": round(duration_s, 1),
                    "started_at_warsaw": format_warsaw(start_dt),
                    "completed_at_warsaw": format_warsaw(end_dt)
                }
                self.storage.record_session(result)
                self.notifier.send_session_summary(result, user, session_logs)
                return result
            finally:
                context.close()
                browser.close()
