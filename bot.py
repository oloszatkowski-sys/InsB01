import time
import random
from datetime import datetime
from typing import Dict, Any, Optional
from config import load_config
from storage import Storage
from solver import InstaLingSolver

INSTALING_LOGIN_URL = "https://instaling.pl/teacher.php?page=login"
INSTALING_MAIN_URL = "https://instaling.pl/teacher.php?page=teacherActions"

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

            try:
                # 1. Wejście na stronę logowania
                print("[*] Otwieranie strony logowania InstaLing...")
                page.goto(INSTALING_LOGIN_URL, timeout=40000)
                page.wait_for_load_state("domcontentloaded")
                time.sleep(1.5)

                # Akceptacja cookies/rodo jeśli występuje
                try:
                    cookie_btn = page.locator("button:has-text('Consent'), button:has-text('Accept all'), button:has-text('Zgadzam się'), button:has-text('Akceptuję'), .cookie-accept, .fc-button.fc-cta-consent")
                    if cookie_btn.count() > 0 and cookie_btn.first.is_visible():
                        cookie_btn.first.click()
                        time.sleep(0.5)
                except Exception:
                    pass

                # 2. Bezpieczne wpisywanie loginu i hasła (human-like)
                print("[*] Logowanie do konta ucznia...")
                login_input = page.locator("input#log_email, input#login, input[name='log_email'], input[name='login']").first
                login_input.click()
                login_input.press_sequentially(login, delay=random.randint(65, 130))
                time.sleep(random.uniform(0.4, 0.8))

                pass_input = page.locator("input#log_password, input[name='log_password'], input[name='password']").first
                pass_input.click()
                pass_input.press_sequentially(password, delay=random.randint(70, 140))
                time.sleep(random.uniform(0.5, 1.0))

                # Kliknięcie 'Zaloguj się'
                submit_btn = page.locator("button[type='submit'], input[type='submit'], .btn-login, button:has-text('Zaloguj')").first
                submit_btn.click()
                page.wait_for_load_state("networkidle", timeout=20000)
                time.sleep(2.0)

                # 3. Weryfikacja zalogowania
                if "page=login" in page.url:
                    # Sprawdź czy jest komunikat błędu
                    error_msg = page.locator(".alert-danger, .error-message, #error_box").all_inner_texts()
                    err_txt = " | ".join(error_msg) if error_msg else "Niepoprawny login lub hasło."
                    return {"success": False, "error": f"Błąd logowania: {err_txt}"}

                print("[+] Pomyślnie zalogowano do serwisu!")

                # 4. Znalezienie przycisku rozpoczęcia sesji
                print("[*] Wyszukiwanie sesji...")
                session_btn_selectors = [
                    "a:has-text('Zacznij codzienną sesję')",
                    "a:has-text('Dokończ sesję')",
                    "a:has-text('Zacznij sesję')",
                    ".btn-session",
                    "#start_session_button",
                    "#start_session_page",
                    "a[href*='action=start_session']"
                ]

                session_btn = None
                for sel in session_btn_selectors:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        session_btn = loc.first
                        break

                if not session_btn:
                    # Sprawdź czy sesja już dzisiaj została ukończona
                    page_text = page.inner_text("body")
                    if "Wykonałeś już dzisiejszą sesję" in page_text or "dzisiejsza sesja wykonana" in page_text:
                        print("[i] Sesja na dzisiaj została już wcześniej wykonana!")
                        return {
                            "success": True,
                            "already_completed": True,
                            "message": "Dzisiejsza sesja była już ukończona."
                        }
                    return {"success": False, "error": "Nie znaleziono przycisku startu sesji na stronie głównej."}

                session_btn.click()
                page.wait_for_load_state("domcontentloaded")
                time.sleep(2.0)

                # 5. Rozwiązywanie słówek w pętli
                print("[*] Rozpoczynanie rozwiązywania słówek...")
                solver = InstaLingSolver(page, self.config, self.storage)
                
                iterations = 0
                while iterations < max_words:
                    iterations += 1
                    time.sleep(random.uniform(0.5, 1.2))

                    if solver.is_session_finished():
                        print("[+] Wykryto zakończenie sesji! Sukces!")
                        break

                    handled = solver.handle_single_word()
                    if not handled:
                        # Ponowne sprawdzenie czy to koniec
                        time.sleep(1.5)
                        if solver.is_session_finished():
                            break
                        print("[i] Brak kolejnych pytań lub oczekiwanie na zmianę stanu.")
                        break

                # 6. Odczekanie chwili po sesji i wylogowanie
                time.sleep(random.uniform(2.5, 4.5))
                try:
                    logout_btn = page.locator("a:has-text('Wyloguj'), a[href*='logout']").first
                    if logout_btn.is_visible():
                        logout_btn.click()
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

                # Zapis do historii
                self.storage.record_session(result)
                print(f"[✓] Sesja zakończona pomyślnie w {duration_s:.1f}s. Rozwiązano: {total}, trafienia: {correct}, błędy: {mistakes} ({acc}%).")
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
