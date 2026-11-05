import sys
import time
import random
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
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

    def check_dashboard_completion(self, page) -> Tuple[bool, str]:
        """
        Weryfikuje na pulpicie ucznia czy dzisiejsza sesja jest w 100% ukończona (zielony znak lub brak przycisków startu).
        """
        try:
            body_txt = page.inner_text("body").lower()

            # 1. Sprawdzamy czy widnieje przycisk 'Dokończ sesję' (sesja wymaga dokończenia!)
            finish_btn = page.locator("a:has-text('Dokończ sesję'), button:has-text('Dokończ sesję'), a:has-text('Dokoncz sesje'), a[href*='app.php']:has-text('Dokończ')").first
            if finish_btn.count() > 0 and finish_btn.is_visible():
                return False, "Wykryto aktywny przycisk 'Dokończ sesję' (sesja wymaga dokończenia!)"

            # 2. Sprawdzamy czy widnieje przycisk 'Rozpocznij codzienną sesję'
            start_btn = page.locator("a.btn-start-session, a:has-text('Rozpocznij codzienną sesję'), a:has-text('Zacznij codzienną sesję'), a:has-text('Zacznij sesję')").first
            if start_btn.count() > 0 and start_btn.is_visible():
                return False, "Wykryto przycisk startu nowej sesji"

            # 3. Sprawdzamy komunikaty o ukończeniu
            done_phrases = [
                "wykonałeś już dzisiejszą sesję", "wykonałaś już dzisiejszą sesję",
                "wykonales juz dzisiejsza sesje", "wykonalas juz dzisiejsza sesje",
                "dzisiejsza sesja została wykonana", "dzisiejsza sesja zostala wykonana",
                "dzisiejsza sesja wykonana", "twoja dzisiejsza sesja została zakończona",
                "twoja dzisiejsza sesja zostala zakonczona", "sesja została wykonana",
                "sesja wykonana"
            ]
            for p in done_phrases:
                if p in body_txt:
                    return True, f"Komunikat: '{p}'"

            # 4. Sprawdzamy zielony wskaźnik wykonania
            done_indicators = page.locator(".session-done, .badge-success, .btn-success, .done, i.fa-check, svg.done, .text-success").all()
            for ind in done_indicators:
                if ind.is_visible():
                    return True, "Wykryto zielony wskaźnik wykonania sesji na pulpicie"

            # 5. Jeśli brak 'Rozpocznij codzienną sesję' i brak 'Dokończ sesję', a jest 'Odrób sesję'
            if "odrób sesję" in body_txt and "rozpocznij codzienną sesję" not in body_txt and "dokończ sesję" not in body_txt:
                return True, "Brak przycisku sesji codziennej (dzisiejsza sesja jest zaliczona)"

            return False, "Brak jednoznacznego potwierdzenia wykonania"
        except Exception as e:
            return False, f"Błąd weryfikacji: {e}"

    def run_session(self, user: Optional[Dict[str, Any]] = None, scheduled_time: Optional[str] = None, slot_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
                # 1. WEJŚCIE NA STRONĘ LOGOWANIA (z 3 próbami i domcontentloaded)
                # ==============================
                max_nav_attempts = 3
                nav_success = False
                last_nav_err = None

                for nav_i in range(1, max_nav_attempts + 1):
                    try:
                        track_log(f"🔗 [NAWIGACJA] Próba {nav_i}/{max_nav_attempts}: Łączenie z {INSTALING_LOGIN_URL} (domcontentloaded)...")
                        t_nav_start = time.time()
                        resp = page.goto(INSTALING_LOGIN_URL, timeout=25000, wait_until="domcontentloaded")
                        page.wait_for_selector("input#log_email, #login_form, form", timeout=12000)
                        nav_time = time.time() - t_nav_start
                        status_code = resp.status if resp else "200"
                        track_log(f"📡 [SERWER] Strona logowania wczytana pomyślnie (kod HTTP {status_code}, czas: {nav_time:.2f}s)")
                        nav_success = True
                        break
                    except Exception as nav_e:
                        last_nav_err = nav_e
                        track_log(f"⚠️ [NAWIGACJA] Próba {nav_i}/{max_nav_attempts} nie powiodła się: {nav_e}")
                        if nav_i < max_nav_attempts:
                            time.sleep(3.5)

                if not nav_success:
                    raise RuntimeError(f"Błąd połączenia ze stroną logowania InstaLing po {max_nav_attempts} próbach: {last_nav_err}")

                time.sleep(1.0)

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
                # 4. GŁÓWNA PĘTLA WYKONYWANIA I DOKAŃCZANIA SESJI (Master Completion Loop)
                # ==============================
                # Zasada: sprawdzamy czy na pulpicie jest zielony znak / potwierdzenie ukończenia.
                # Jeśli nie lub sesja została przerwana (np. po 5 słówkach), klikamy 'Dokończ sesję' i dokańczamy sesję!
                MAX_PASSES = 4
                current_pass = 0
                all_resolved_words = []
                total_words = 0
                total_correct = 0
                total_mistakes = 0
                session_confirmed_done = False

                # Najpierw weryfikujemy stan początkowy na pulpicie
                is_done_init, reason_init = self.check_dashboard_completion(page)
                if is_done_init:
                    track_log(f"🟢 [ZIELONY ZNAK / POTWIERDZENIE] {nickname} ma już zaliczoną dzisiejszą sesję ({reason_init})!")
                    res = {
                        "success": True,
                        "already_completed": True,
                        "message": f"Dzisiejsza sesja {nickname} była już ukończona."
                    }
                    self.notifier.send_session_summary(res, user, session_logs)
                    return res

                while current_pass < MAX_PASSES:
                    current_pass += 1
                    track_log(f"🚀 [ETAP SESJI {current_pass}/{MAX_PASSES}] Uruchamiam/dokańczam sesję dla {nickname}...")

                    # Szukamy przycisku wejścia do sesji (Dokończ sesję ma najwyższy priorytet!)
                    session_btn = page.locator(
                        "a:has-text('Dokończ sesję'), button:has-text('Dokończ sesję'), a:has-text('Dokoncz sesje'), "
                        "a.btn-start-session, a:has-text('Rozpocznij codzienną sesję'), a:has-text('Zacznij codzienną sesję'), "
                        "a:has-text('Zacznij sesję'), a:has-text('Kontynuuj sesję'), button:has-text('Kontynuuj sesję')"
                    ).first

                    if session_btn.count() > 0 and session_btn.is_visible():
                        b_txt = session_btn.inner_text().strip()
                        track_log(f"▶️ [PANEL] Wykryto przycisk '{b_txt}' — otwieram sesję...")
                        session_btn.click()
                        time.sleep(2.5)

                    # Ekran startowy / wznowienia wewnątrz sesji
                    cont_btn = page.locator("a:has-text('Kontynuuj sesję'), button:has-text('Kontynuuj sesję'), #continue_session").first
                    if cont_btn.count() > 0 and cont_btn.is_visible():
                        track_log(f"🔘 [SESJA] Ekran wznowienia — klikam '{cont_btn.inner_text().strip()}'")
                        cont_btn.click(force=True)
                        time.sleep(2.0)

                    start_btn = page.locator("a:has-text('Rozpocznij sesję'), button:has-text('Rozpocznij sesję'), #start_session").first
                    if start_btn.count() > 0 and start_btn.is_visible():
                        track_log(f"🔘 [SESJA] Ekran gotowości — klikam '{start_btn.inner_text().strip()}'")
                        start_btn.click(force=True)
                        time.sleep(2.0)

                    # Moduł rozwiązywania słówek w tym etapie
                    solver = InstaLingSolver(page, self.config, self.storage, log_fn=track_log)
                    iterations = 0
                    max_words_pass = 50

                    while iterations < max_words_pass:
                        iterations += 1
                        time.sleep(random.uniform(0.5, 1.0))

                        if (time.time() - start_epoch) > 600:
                            track_log("[!] Osiągnięto limit czasu sesji (600s).")
                            break

                        if solver.is_session_finished():
                            track_log(f"🎉 [SESJA] Ekran ukończenia sesji wykryty w etapie {current_pass}!")
                            break

                        handled = solver.handle_single_word()
                        if not handled:
                            time.sleep(2.0)
                            if solver.is_session_finished():
                                track_log("🎉 [SESJA] Sesja ukończona po ostatnim pytaniu!")
                                break
                            break

                    total_words += solver.session_words_count
                    total_correct += solver.session_correct_count
                    total_mistakes += solver.session_mistakes_count
                    all_resolved_words.extend(solver.resolved_words)

                    # Powrót do pulpitu w celu weryfikacji czy sesja jest w 100% zaliczona
                    time.sleep(2.0)
                    try:
                        home_btn = page.locator("a:has-text('Wróć do strony głównej'), a:has-text('Strona główna'), a.btn-return, a[href*='mainPage']").first
                        if home_btn.count() > 0 and home_btn.is_visible():
                            track_log("🏠 [POWRÓT] Powrót na stronę główną w celu weryfikacji stanu...")
                            home_btn.click(force=True)
                            time.sleep(2.5)
                        else:
                            page.goto("https://instaling.pl/student/pages/mainPage.php", timeout=20000)
                            time.sleep(2.5)
                    except Exception:
                        page.goto("https://instaling.pl/student/pages/mainPage.php", timeout=20000)
                        time.sleep(2.5)

                    # WERYFIKACJA ZIELONEGO ZNAKU / BRAKU PRZYCISKU 'DOKOŃCZ SESJĘ'
                    is_done_now, reason_now = self.check_dashboard_completion(page)
                    if is_done_now:
                        track_log(f"🟢 [ZIELONY ZNAK ZNALEZIONY] Sesja {nickname} została w 100% ukończona ({reason_now})!")
                        session_confirmed_done = True
                        break
                    else:
                        track_log(f"⚠️ [SESJA NIEUKOŃCZONA] Na pulpicie nadal brak potwierdzenia ({reason_now})! Zrobiono dotąd {total_words} słówek. Dokańczam sesję w kolejnym etapie...")

                # Wylogowanie po pełnym ukończeniu
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
                total = total_words
                correct = total_correct
                mistakes = total_mistakes
                acc = round((correct / total * 100), 1) if total > 0 else 0.0
                new_words_count = len({
                    w.get("prompt", "").strip()
                    for w in all_resolved_words
                    if w.get("status") == "nowe" and w.get("prompt", "").strip()
                })
                autocorrect_count = len({
                    w.get("prompt", "").strip()
                    for w in all_resolved_words
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
                    "words_details": all_resolved_words
                }

                self.storage.record_session(result)
                track_log(f"\n[OK] SESJA DLA {nickname} ({masked}) ZAKONCZONA SUKCESEM!")
                track_log(f"    Czas: {format_warsaw(start_dt)} -> {format_warsaw(end_dt)} ({duration_s:.1f}s)")
                track_log(f"    Rozwiazano: {total} | Poprawne: {correct} ({acc}%)\n")

                if all_resolved_words:
                    track_log("📚 SŁÓWKA ROZWIĄZANE W TEJ SESJI:")
                    for idx, w in enumerate(all_resolved_words):
                        st = w.get("status", "")
                        tag = "✅ POPRAWNIE" if st == "poprawnie" else ("🆕 NOWE ZAPAMIĘTANO" if st == "nowe" else ("🔄 AUTOKOREKTA" if st == "autokorekta" else "⚠️ BŁĄD"))
                        track_log(f"  {idx+1:2d}. {w['prompt']} ➔ {w['answer']} [{tag}]")
                    track_log("")

                # Wysyłamy powiadomienie z podziałem na kanały Discord i ntfy
                self.notifier.send_session_summary(result, user, session_logs)
                return result

            except Exception as e:
                tb_str = traceback.format_exc()
                err_str = str(e)
                end_dt = now_warsaw()
                duration_s = (end_dt - start_dt).total_seconds()
                track_log(f"[!] Błąd w trakcie wykonywania sesji dla {nickname}: {err_str}")
                track_log(f"[!] Szczegóły śladu błędu:
{tb_str}")

                curr_attempt = (slot_info.get("error_count", 0) + 1) if slot_info else 1
                max_retries = int(self.config.get("max_error_retries", 3))
                retry_min = int(self.config.get("error_retry_delay_minutes", 60))
                retry_after_dt = end_dt + timedelta(minutes=retry_min)

                result = {
                    "success": False,
                    "nickname": nickname,
                    "masked_login": masked,
                    "scheduled_time": scheduled_time or start_dt.strftime("%H:%M"),
                    "error": err_str,
                    "traceback": tb_str,
                    "error_count": curr_attempt,
                    "max_retries": max_retries,
                    "retry_after_warsaw": format_warsaw(retry_after_dt),
                    "duration_seconds": round(duration_s, 1),
                    "started_at_warsaw": format_warsaw(start_dt),
                    "completed_at_warsaw": format_warsaw(end_dt),
                    "session_logs": list(session_logs)
                }
                self.storage.record_session(result)
                self.notifier.send_session_summary(result, user, session_logs)
                return result
            finally:
                context.close()
                browser.close()
