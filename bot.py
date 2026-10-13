import time
import random
from datetime import datetime
from typing import Dict, Any, Optional
from config import load_config
from storage import Storage
from solver import InstaLingSolver

INSTALING_LOGIN_URL = "https://instaling.pl/teacher.php?page=login"

class InstaLingBot:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()
        self.storage = Storage()

    def run_session(self) -> Dict[str, Any]:
        """Uruchamia pełną sesję: start przeglądarki, logowanie, rozwiązanie zadań i zapis."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {
                "success": False,
                "error": "Biblioteka Playwright nie jest zainstalowana. Uruchom w terminalu: pip install playwright && playwright install chromium"
            }

        login = self.config.get("login", "").strip()
        password = self.config.get("password", "").strip()

        if not login or not password:
            return {
                "success": False,
                "error": "Brak danych logowania (login lub hasło są puste). Skonfiguruj je w menu lub pliku config.json."
            }

        start_time = datetime.now()
        headless = bool(self.config.get("headless", True))
        mute_audio = bool(self.config.get("mute_audio", True))
        max_words = int(self.config.get("max_words_per_session", 45))

        print(f"[*] Uruchamianie bota InstaLing... (headless={headless})")

        with sync_playwright() as p:
            args = []
            if mute_audio:
                args.append("--mute-audio")

            browser = p.chromium.launch(
                headless=headless,
                args=args
            )
            
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

            try:
                # ==============================
                # 1. WEJŚCIE NA STRONĘ LOGOWANIA
                # ==============================
                print("[*] Otwieranie strony logowania InstaLing...")
                page.goto(INSTALING_LOGIN_URL, timeout=40000)
                page.wait_for_load_state("domcontentloaded")
                time.sleep(2.0)

                # ==============================
                # 2. LOGOWANIE
                # ==============================
                print("[*] Logowanie do konta ucznia...")
                login_input = page.locator("input#log_email").first
                login_input.fill(login)
                time.sleep(random.uniform(0.4, 0.7))

                pass_input = page.locator("input#log_password").first
                pass_input.fill(password)
                time.sleep(random.uniform(0.4, 0.8))

                submit_btn = page.locator('button:has-text("ZALOGUJ")').first
                submit_btn.click(force=True)
                time.sleep(3.5)

                # ==============================
                # 3. WERYFIKACJA ZALOGOWANIA
                # ==============================
                current_url = page.url
                if "page=login" in current_url and "student" not in current_url:
                    error_msg = page.locator(".alert-danger, .error-message, #error_box").all_inner_texts()
                    err_txt = " | ".join(error_msg) if error_msg else "Niepoprawny login lub hasło."
                    return {"success": False, "error": f"Błąd logowania: {err_txt}"}

                print(f"[+] Pomyślnie zalogowano! Panel: {current_url}")

                # ==============================
                # 4. WEJŚCIE DO SESJI Z PANELU
                # ==============================
                print("[*] Wyszukiwanie sesji...")
                session_btn = page.locator("a.btn-start-session, a:has-text('Dokończ sesję'), a:has-text('Zacznij codzienną sesję'), a:has-text('Zacznij sesję')").first
                if session_btn.count() == 0 or not session_btn.is_visible():
                    page_text = page.inner_text("body")
                    if "Wykonałeś już dzisiejszą sesję" in page_text or "sesja wykonana" in page_text.lower():
                        print("[i] Sesja na dzisiaj została już wcześniej wykonana!")
                        return {
                            "success": True,
                            "already_completed": True,
                            "message": "Dzisiejsza sesja była już ukończona."
                        }
                    return {"success": False, "error": "Nie znaleziono przycisku startu sesji na stronie głównej."}

                print(f"[*] Przechodzenie do sesji: '{session_btn.inner_text().strip()}'")
                session_btn.click()
                time.sleep(3.0)

                # ==============================
                # 5. EKRAN STARTOWY SESJI (Kontynuuj / Rozpocznij)
                # ==============================
                cont_btn = page.get_by_text("Kontynuuj sesję").first
                if cont_btn.count() > 0 and cont_btn.is_visible():
                    print("[*] Klikam 'Kontynuuj sesję'...")
                    cont_btn.click(force=True)
                    time.sleep(2.5)

                start_btn = page.get_by_text("Rozpocznij sesję").first
                if start_btn.count() > 0 and start_btn.is_visible():
                    print("[*] Klikam 'Rozpocznij sesję'...")
                    start_btn.click(force=True)
                    time.sleep(2.5)

                # ==============================
                # 6. PĘTLA ROZWIĄZYWANIA SŁÓWEK
                # ==============================
                print("[*] Rozpoczynanie rozwiązywania słówek...")
                solver = InstaLingSolver(page, self.config, self.storage)

                iterations = 0
                while iterations < max_words:
                    iterations += 1
                    time.sleep(random.uniform(0.6, 1.2))

                    if solver.is_session_finished():
                        print("[+] Sesja ukończona pomyślnie! Gratulacje!")
                        break

                    handled = solver.handle_single_word()
                    if not handled:
                        time.sleep(2.0)
                        if solver.is_session_finished():
                            print("[+] Sesja ukończona!")
                            break
                        print("[i] Zakończono pytania w tej sesji.")
                        break

                # ==============================
                # 7. WYLOGOWANIE I STATYSTYKI
                # ==============================
                time.sleep(random.uniform(2.0, 3.5))
                try:
                    logout_btn = page.locator("a:has-text('Wyloguj'), a[href*='logout']").first
                    if logout_btn.is_visible():
                        logout_btn.click(force=True)
                        time.sleep(1.0)
                except Exception:
                    pass

                duration_s = (datetime.now() - start_time).total_seconds()
                total = solver.session_words_count
                correct = solver.session_correct_count
                mistakes = solver.session_mistakes_count
                acc = round((correct / total * 100), 1) if total > 0 else 0.0

                result = {
                    "success": True,
                    "words_total": total,
                    "words_correct": correct,
                    "words_mistakes": mistakes,
                    "accuracy_percent": acc,
                    "duration_seconds": round(duration_s, 1),
                    "finished_at": datetime.now().isoformat()
                }

                self.storage.record_session(result)
                print(f"\n[✓] SESJA ZAKOŃCZONA SUKCESEM!")
                print(f"    Czas trwania: {duration_s:.1f} s | Rozwiązano słówek: {total}")
                print(f"    Poprawne: {correct} | Błędy: {mistakes} | Skuteczność: {acc}%\n")
                return result

            except Exception as e:
                err_str = str(e)
                print(f"[!] Błąd w trakcie wykonywania sesji: {err_str}")
                self.storage.record_session({
                    "success": False,
                    "error": err_str,
                    "duration_seconds": round((datetime.now() - start_time).total_seconds(), 1)
                })
                return {"success": False, "error": err_str}
            finally:
                context.close()
                browser.close()
